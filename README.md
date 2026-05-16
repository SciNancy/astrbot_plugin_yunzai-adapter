# AstrBot Yunzai 适配器插件

AstrBot 端插件，通过 WebSocket 将消息转发给 Yunzai-Bot（Miao-Yunzai）处理，实现 AstrBot 负责通信、Yunzai 负责业务逻辑的分离架构。

## 配套组件

| 组件 | 仓库 | 说明 |
|------|------|------|
| **AstrBot 端** | 本仓库 | WebSocket 客户端，转发消息 |
| **Yunzai 端** | [yunzai-astrbot-adapter](https://github.com/SciNancy/yunzai-astrbot-adapter) | WebSocket 服务器，接收并处理消息 |

## 安装

在 AstrBot 管理面板 → 插件市场 → 安装插件，输入：

```
https://github.com/SciNancy/astrbot_plugin_yunzai-adapter
```

或手动复制本仓库文件到 AstrBot 的 `data/plugins/` 目录下。

## 配置

在 AstrBot 管理面板或配置文件中添加：

```yaml
astrbot_plugin_yunzai_adapter:
  WS_HOST: "127.0.0.1"      # Yunzai WebSocket 服务器地址
  WS_PORT: 8766             # Yunzai WebSocket 服务器端口
  YUNZAI_ONLY_PREFIXES:     # 只转发给 Yunzai 的消息前缀
    - "#"
    - "*"
```

- `WS_HOST` / `WS_PORT`: 与 Yunzai 端 `ASTRBOT_WS_HOST` / `ASTRBOT_WS_PORT` 环境变量一致
- `YUNZAI_ONLY_PREFIXES`: 为空则转发所有消息；配置后只有匹配前缀的消息才转发给 Yunzai，同时阻断 AstrBot 后续处理

## 消息协议

### AstrBot → Yunzai

```json
{
    "type": "message",
    "bot_self_id": "123456789",
    "message_type": "group",
    "user_id": "987654321",
    "group_id": "111222333",
    "message": [
        { "type": "text", "data": "#帮助" },
        { "type": "image", "data": "base64://..." }
    ],
    "sender": { "nickname": "用户", "card": "群名片" },
    "msg_id": "uuid"
}
```

### Yunzai → AstrBot

```json
{
    "type": "reply",
    "target_type": "group",
    "target_id": "111222333",
    "content": [
        { "type": "text", "data": "回复文本" },
        { "type": "image", "data": "base64://..." }
    ],
    "time": 1234567890
}
```

## 常见问题

**Yunzai 端 WebSocket 连不上？**

检查 Yunzai 端适配器是否已启动，以及 `WS_HOST` / `WS_PORT` 配置是否一致。

**消息发了但 Yunzai 没响应？**

检查 `YUNZAI_ONLY_PREFIXES` 配置，确保消息前缀在列表中。

## 许可证

MIT
