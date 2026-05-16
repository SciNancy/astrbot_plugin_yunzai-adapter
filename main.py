import asyncio
import base64
import json
from pathlib import Path

import msgspec
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

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.is_connect = False
        self.ws_host = getattr(self.config, "WS_HOST", "127.0.0.1")
        self.ws_port = getattr(self.config, "WS_PORT", 8766)
        self.yunzai_only_prefixes = [
            prefix
            for prefix in getattr(self.config, "YUNZAI_ONLY_PREFIXES", [])
            if isinstance(prefix, str) and prefix
        ]
        self.ws = None
        self.recv_task = None

    def _is_yunzai_only_message(self, event: AstrMessageEvent) -> bool:
        """检查消息是否只应由 Yunzai 处理"""
        if not self.yunzai_only_prefixes:
            return False
        raw_text = event.message_str.lstrip()
        if not raw_text:
            return False
        return any(raw_text.startswith(prefix) for prefix in self.yunzai_only_prefixes)

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
            await self.ws.send(msgspec.json.encode(payload).decode("utf-8"))
            logger.info(f"[YunzaiAdapter] 转发消息: {event.message_str[:50]}")
        except Exception as e:
            logger.error(f"[YunzaiAdapter] 发送消息失败: {e}")
            return

        # 如果配置了独占前缀，阻断 AstrBot 后续处理
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

        if not target_id:
            logger.warning("[YunzaiAdapter] 回复缺少 target_id")
            return

        # 构造 AstrBot 会话对象
        msg_type_enum = (
            MessageType.GROUP_MESSAGE
            if target_type == "group"
            else MessageType.FRIEND_MESSAGE
        )
        session = MessageSesion(bot_self_id, msg_type_enum, target_id)

        # 转换消息为 AstrBot 格式
        astrbot_chain = MessageChain()
        astrbot_msgs = await self._convert_from_yunzai_msgs(content)
        astrbot_chain.chain.extend(astrbot_msgs)

        logger.info(f"[YunzaiAdapter] 接收回复，即将发送: {len(astrbot_msgs)} 条消息")
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
                # 尝试作为本地路径
                path = Path(img_data)
                if path.exists():
                    return Image.fromFileSystem(str(path))
                logger.warning(f"[YunzaiAdapter] 无法识别的图片数据: {img_data[:50]}...")
                return None
        except Exception as e:
            logger.error(f"[YunzaiAdapter] 图片转换失败: {e}")
            return None
