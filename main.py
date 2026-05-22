import asyncio
import base64
import json
from dataclasses import asdict
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import (
    At, Image, Plain, Reply, File, Record, Video, Node, Nodes,
)
from astrbot.core.platform.astr_message_event import MessageSesion
from astrbot.core.platform.message_type import MessageType
from astrbot.core.star.filter.event_message_type import EventMessageType
import websockets.client
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from .models import Message as YzMessage
from .models import MessageReceive, MessageSend


@register(
    "astrbot_plugin_yunzai_adapter",
    "User",
    "Yunzai-Bot 适配器，将 AstrBot 消息转发给 Yunzai 处理并回传结果",
    "1.0.0",
)
class YunzaiAdapter(Star):
    """Yunzai 适配器主类"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        # 兼容旧版 AstrBot 插件 API（部分版本只传 context）
        self.config = config or getattr(context, "config", None)
        # 如果 config 仍未获取到，尝试从配置文件直接读取
        if not self.config:
            try:
                cfg_path = Path("/AstrBot/data/config/astrbot_plugin_yunzai_adapter_config.json")
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        self.config = json.load(f)
            except Exception:
                pass
        self.is_connect = False
        # 安全读取配置，兼容 config 为 dict（文件读取）或对象（API传递）的情况
        def _get(key: str, default):
            if isinstance(self.config, dict):
                return self.config.get(key, default)
            return getattr(self.config, key, default) if self.config else default

        self.ws_host = _get("WS_HOST", "127.0.0.1")
        self.ws_port = _get("WS_PORT", 8766)
        prefixes = _get("YUNZAI_ONLY_PREFIXES", [])
        self.yunzai_only_prefixes = [
            prefix for prefix in (prefixes or [])
            if isinstance(prefix, str) and prefix
        ]
        self.yunzai_root = (_get("YUNZAI_ROOT", "") or "")
        self.ws = None
        self.recv_task = None
        # 保存等待 Yunzai 回复的原始事件对象（QQ 等持久会话平台异步回复用）
        self.pending_events: dict[str, AstrMessageEvent] = {}
        # WebChat 等平台需要同步等待回复，用 Future 跨协程传递结果
        self.pending_futures: dict[str, asyncio.Future] = {}

    def _is_yunzai_only_message(self, event: AstrMessageEvent) -> bool:
        """检查消息是否只应由 Yunzai 处理"""
        if not self.yunzai_only_prefixes:
            return False
        raw_text = event.message_str.lstrip()
        if not raw_text:
            return False
        return any(raw_text.startswith(prefix) for prefix in self.yunzai_only_prefixes)

    def _safe_pop_pending(self, key: str):
        """安全地从 pending_events 中移除指定 key，用于延迟清理"""
        self.pending_events.pop(key, None)

    async def connect(self):
        """建立与 Yunzai 的 WebSocket 连接"""
        if self.is_connect:
            return

        ws_url = f"ws://{self.ws_host}:{self.ws_port}"
        logger.info(f"[YunzaiAdapter] 正在连接 Yunzai: {ws_url} ...")

        try:
            self.ws = await websockets.client.connect(
                ws_url, max_size=2**26, open_timeout=5, ping_timeout=10
            )
            self.is_connect = True
            logger.info(f"[YunzaiAdapter] 已连接到 Yunzai: {ws_url}")
            # 启动接收循环
            self.recv_task = asyncio.create_task(self._recv_loop())
        except Exception as e:
            logger.error(f"[YunzaiAdapter] 连接 Yunzai 失败: {e}")
            self.is_connect = False

    async def _ensure_connected(self):
        """确保连接可用，若断开则尝试重连"""
        if not self.is_connect or not self.ws or self.ws.closed:
            self.is_connect = False
            await self.connect()

    @filter.event_message_type(EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        """监听所有消息并转发给 Yunzai"""
        await self._ensure_connected()

        if not self.is_connect or not self.ws:
            logger.warning("[YunzaiAdapter] WebSocket 未连接，消息未转发")
            return

        # 只转发以配置前缀开头的消息给 Yunzai，其他消息直接跳过
        # 避免所有消息都涌向 Yunzai 导致重复回复和无关指令被处理
        if not self._is_yunzai_only_message(event):
            logger.debug(f"[YunzaiAdapter] 消息未命中前缀，跳过转发: {event.message_str[:30]}")
            return

        # 转换消息链为 Yunzai 格式
        yunzai_messages = await self._convert_to_yunzai_msgs(event)
        if not yunzai_messages:
            logger.debug("[YunzaiAdapter] 消息为空，跳过转发")
            return

        # 获取发送者信息
        sender_name = event.get_sender_name() or "未知用户"
        sender = {
            "nickname": sender_name,
            "card": sender_name,
        }

        # 判断消息类型
        msg_type = event.get_message_type()
        is_group = msg_type == MessageType.GROUP_MESSAGE
        message_type = "group" if is_group else "private"

        self_id = str(event.get_self_id() or "")
        user_id = str(event.get_sender_id() or "")
        group_id = str(event.get_group_id() or "") if is_group else None

        # 构造 Yunzai 消息
        payload = MessageReceive(
            type="message",
            bot_self_id=self_id,
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
            sender=sender,
            message=yunzai_messages,
            msg_id=event.get_session_id() or f"{user_id}_{int(asyncio.get_event_loop().time() * 1000)}",
        )

        try:
            # 手动构造字典，避免 asdict() 对嵌套 dataclass 的类型敏感问题
            payload_dict = {
                "type": payload.type,
                "bot_self_id": payload.bot_self_id,
                "message_type": payload.message_type,
                "user_id": payload.user_id,
                "group_id": payload.group_id,
                "sender": payload.sender,
                "message": [{"type": m.type, "data": m.data} for m in payload.message],
                "msg_id": payload.msg_id,
            }
            await self.ws.send(json.dumps(payload_dict, ensure_ascii=False))
            logger.info(f"[YunzaiAdapter] 转发消息: {event.message_str[:50]}")
        except Exception as e:
            logger.error(f"[YunzaiAdapter] 发送消息失败: {e}")
            return

        # 判断平台：WebChat 必须同步等待回复，因为 HTTP 响应结束后无法异步发送
        is_webchat = event.get_platform_name() == "webchat"

        if is_webchat:
            # WebChat：同步等待 Yunzai 回复，在同一 HTTP 请求内返回
            future = asyncio.get_event_loop().create_future()
            self.pending_futures[payload.msg_id] = future
            try:
                reply_chain = await asyncio.wait_for(future, timeout=30)
                await event.send(reply_chain)
                logger.info("[YunzaiAdapter] WebChat 同步回复已发送")
            except asyncio.TimeoutError:
                logger.warning("[YunzaiAdapter] WebChat 等待 Yunzai 回复超时")
            except Exception as e:
                logger.error(f"[YunzaiAdapter] WebChat 发送同步回复失败: {e}")
            finally:
                self.pending_futures.pop(payload.msg_id, None)
        else:
            # QQ 等持久会话平台：保存事件，异步等待回复
            self.pending_events[payload.msg_id] = event
            self.pending_events[user_id] = event

        # 独占前缀消息阻断 AstrBot 后续处理（LLM 等）
        if self._is_yunzai_only_message(event):
            event.stop_event()
            logger.info("[YunzaiAdapter] 消息命中独占前缀，已阻断 AstrBot 后续流程")

    async def _recv_loop(self):
        """持续接收 Yunzai 的回复"""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    await self._handle_reply(data)
                except Exception as e:
                    logger.error(f"[YunzaiAdapter] 处理回复出错: {e}")
        except ConnectionClosedError:
            logger.warning("[YunzaiAdapter] WebSocket 连接已断开")
        except Exception as e:
            logger.error(f"[YunzaiAdapter] 接收循环异常: {e}")
        finally:
            self.is_connect = False

    async def _handle_reply(self, data: dict):
        """处理 Yunzai 发回的回复"""
        msg_type = data.get("type")
        if msg_type == "connected":
            logger.info(f"[YunzaiAdapter] Yunzai 确认连接: {data.get('msg')}")
            return

        if msg_type == "pong":
            return

        if msg_type != "reply":
            logger.warning(f"[YunzaiAdapter] 未知消息类型: {msg_type}")
            return

        content = data.get("content", [])
        if not content:
            logger.debug("[YunzaiAdapter] 收到空回复，跳过")
            return

        target_type = data.get("target_type", "private")
        target_id = data.get("target_id")
        bot_self_id = data.get("bot_self_id", "")
        msg_id = data.get("msg_id")

        if not target_id:
            logger.warning("[YunzaiAdapter] 回复缺少 target_id")
            return

        # 转换消息为 AstrBot 格式
        astrbot_chain = MessageChain()
        astrbot_msgs = await self._convert_from_yunzai_msgs(content)
        astrbot_chain.chain.extend(astrbot_msgs)

        # 1) WebChat 同步等待模式：通过 Future 传递结果
        future = self.pending_futures.pop(msg_id, None) if msg_id else None
        if future and not future.done():
            future.set_result(astrbot_chain)
            logger.info(f"[YunzaiAdapter] 回复已写入 Future（WebChat 同步等待）: {len(astrbot_msgs)} 条消息")
            return

        # 2) QQ 等持久会话平台：通过保存的 event 异步发送
        event = None
        if msg_id and msg_id in self.pending_events:
            # msg_id 匹配时不立即 pop，允许同一消息的多条回复（如签到中的"签到中..."+图片+撤回）
            event = self.pending_events[msg_id]
        elif target_id in self.pending_events:
            event = self.pending_events.pop(target_id)

        if event:
            logger.info(f"[YunzaiAdapter] 通过 event.send() 发送回复: {len(astrbot_msgs)} 条消息")
            try:
                await event.send(astrbot_chain)
            except Exception as e:
                logger.error(f"[YunzaiAdapter] event.send() 失败: {e}")
            # 只清理 target_id，msg_id 延迟清理以支持后续回复
            self.pending_events.pop(target_id, None)
            if msg_id and msg_id in self.pending_events:
                # 延迟 60 秒后清理 msg_id，给 Yunzai 的多条回复留时间窗口
                asyncio.get_event_loop().call_later(60, self._safe_pop_pending, msg_id)
            return

        # 3) Fallback: 通过 MessageSesion 发送（适用于其他持久会话平台）
        msg_type_enum = (
            MessageType.GROUP_MESSAGE
            if target_type == "group"
            else MessageType.FRIEND_MESSAGE
        )
        session = MessageSesion(bot_self_id, msg_type_enum, target_id)
        logger.info(f"[YunzaiAdapter] 通过 send_message 发送回复: {len(astrbot_msgs)} 条消息")
        await self.context.send_message(session, astrbot_chain)

    async def _convert_to_yunzai_msgs(self, event: AstrMessageEvent) -> list:
        """AstrBot 消息链 → Yunzai 消息格式"""
        result = []
        messages = event.get_messages()

        for msg in messages:
            if isinstance(msg, Plain):
                if msg.text:
                    result.append(YzMessage(type="text", data=msg.text))

            elif isinstance(msg, Image):
                img = await self._convert_image_to_yunzai(msg)
                if img:
                    result.append(img)

            elif isinstance(msg, At):
                result.append(YzMessage(type="at", data=str(msg.qq)))

            elif isinstance(msg, Reply):
                result.append(YzMessage(type="reply", data=str(msg.id)))

            elif isinstance(msg, File):
                # 文件简化处理，发送文件名
                result.append(YzMessage(type="text", data=f"[文件: {msg.name}]"))

            else:
                logger.debug(f"[YunzaiAdapter] 未处理的消息类型: {type(msg)}")

        return result

    async def _convert_image_to_yunzai(self, img_msg: Image) -> YzMessage | None:
        """将 AstrBot Image 转换为 Yunzai 格式"""
        img_path = getattr(img_msg, "path", None) or getattr(img_msg, "url", None)
        if not img_path:
            logger.warning("[YunzaiAdapter] 图片消息缺少路径")
            return None

        # 在线图片直接透传 URL
        if isinstance(img_path, str) and img_path.startswith("http"):
            return YzMessage(type="image", data=img_path)

        # 本地文件转 base64
        file_path = Path(str(img_path))
        if not file_path.exists():
            logger.warning(f"[YunzaiAdapter] 图片文件不存在: {img_path}")
            return None

        try:
            with open(file_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
            return YzMessage(type="image", data=f"base64://{img_data}")
        except Exception as e:
            logger.error(f"[YunzaiAdapter] 图片转 base64 失败: {e}")
            return None

    async def _convert_from_yunzai_msgs(self, content: list) -> list:
        """Yunzai 消息格式 → AstrBot 消息链"""
        result = []

        for item in content:
            msg_type = item.get("type")
            msg_data = item.get("data", "")

            if msg_type == "text":
                result.append(Plain(msg_data))

            elif msg_type == "image":
                img = self._convert_image_from_yunzai(msg_data)
                if img:
                    result.append(img)

            elif msg_type == "at":
                try:
                    result.append(At(qq=str(msg_data)))
                except Exception:
                    pass

            elif msg_type == "reply":
                try:
                    result.append(Reply(id=str(msg_data)))
                except Exception:
                    pass

            elif msg_type == "record":
                # 语音暂不支持直接播放，转为文本提示
                result.append(Plain("[语音消息]"))

            elif msg_type == "video":
                result.append(Plain("[视频消息]"))

            elif msg_type == "file":
                result.append(Plain(f"[文件: {msg_data}]"))

            else:
                logger.debug(f"[YunzaiAdapter] 未处理的回复类型: {msg_type}")

        return result

    def _convert_image_from_yunzai(self, img_data: str) -> Image | None:
        """将 Yunzai 图片数据转为 AstrBot Image"""
        if not img_data:
            return None

        try:
            if img_data.startswith("base64://"):
                return Image.fromBase64(img_data[9:])
            elif img_data.startswith("http"):
                return Image.fromURL(img_data)
            else:
                # 处理 file:// 协议前缀（Yunzai 本地图片常见格式）
                raw_path = img_data
                if raw_path.startswith("file://"):
                    raw_path = raw_path[7:]  # 去掉 file:// 前缀

                # 尝试作为本地路径解析（支持绝对路径和相对路径）
                path = Path(raw_path)
                if not path.is_absolute() and self.yunzai_root:
                    # 相对路径且配置了 Yunzai 根目录，拼接为绝对路径
                    path = Path(self.yunzai_root) / path

                if path.exists():
                    return Image.fromFileSystem(str(path.resolve()))
                logger.warning(f"[YunzaiAdapter] 无法识别的图片数据: {img_data[:50]}...")
                return None
        except Exception as e:
            logger.error(f"[YunzaiAdapter] 图片转换失败: {e}")
            return None
