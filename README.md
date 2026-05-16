# Yunzai-Bot × AstrBot 桥接适配器

将 Miao-Yunzai + miao-plugin 通过 WebSocket 桥接到 AstrBot，由 AstrBot 负责 QQ 通信，Yunzai 只处理业务逻辑。

## 架构

```
用户 QQ → OneBot/LLOneBot → AstrBot → WebSocket → Yunzai (skip_login)
                                              ↓
                                        miao-plugin 处理
                                              ↓
                                        图片/文本回复
                                              ↓
                                        WebSocket → AstrBot → 用户 QQ
```

## 项目结构

```
.
├── yunzai-astrbot-adapter/          # Yunzai 端适配器插件
│   ├── index.js                     # 插件入口
│   ├── ws-server.js                 # WebSocket 服务器
│   ├── event-builder.js             # icqq 事件对象构造
│   ├── mock-bot.js                  # Bot/群/好友 Mock
│   └── package.json
│
├── astrbot_plugin_yunzai_adapter/   # AstrBot 端适配器插件
│   ├── main.py                      # 插件主逻辑
│   ├── models.py                    # 消息结构定义
│   ├── metadata.yaml                # 插件元数据
│   └── _conf_schema.json            # 配置定义
│
└── docker-compose.yml               # Docker 编排（可选）
```

## 快速部署

### 1. Yunzai 端配置

将 `yunzai-astrbot-adapter/` 复制到 Yunzai 的 `plugins/` 目录下：

```bash
cp -r yunzai-astrbot-adapter/ /path/to/Miao-Yunzai/plugins/
```

修改 `Miao-Yunzai/config/config/bot.yaml`（或创建该文件）：

```yaml
# 跳过 QQ 登录，直接加载插件
skip_login: true
```

启动 Yunzai：

```bash
cd /path/to/Miao-Yunzai
pnpm install  # 确保依赖已安装
node .
```

日志中应出现：

```
[AstrBotAdapter] WebSocket 服务器已启动: ws://0.0.0.0:8766
```

### 2. AstrBot 端配置

将 `astrbot_plugin_yunzai_adapter/` 复制到 AstrBot 的插件目录（通常是 `data/plugins/` 或你配置的插件目录）。

在 AstrBot 管理面板或配置文件中添加：

```yaml
astrbot_plugin_yunzai_adapter:
  WS_HOST: "127.0.0.1"
  WS_PORT: 8766
  YUNZAI_ONLY_PREFIXES:
    - "#"
    - "*"
```

- `WS_HOST` / `WS_PORT`: Yunzai WebSocket 服务器地址
- `YUNZAI_ONLY_PREFIXES`: 只转发给 Yunzai 的消息前缀，为空则转发所有消息

重启 AstrBot，日志中应出现：

```
[YunzaiAdapter] 已连接到 Yunzai: ws://127.0.0.1:8766
```

### 3. 测试

在 QQ 群或私聊中发送：

```
#帮助
```

应收到 miao-plugin 的帮助图片。

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

## 更新兼容性

- **Yunzai 更新**: 直接覆盖本体文件，保留 `plugins/yunzai-astrbot-adapter/` 和 `config/` 即可。适配器不修改任何核心代码。
- **AstrBot 更新**: 适配器作为普通插件，不受影响。

## 常见问题

### Yunzai 提示 "未找到 e.runtime，请升级至最新版 Yunzai"

这是 miao-plugin 的提示，不影响功能。某些老版本插件可能需要 Runtime，而 `Runtime.init(e)` 在 `deal(e)` 中已被调用。

### 图片无法显示

确保 Yunzai Docker 镜像中安装了 Chromium，或在 `config/bot.yaml` 中指定 `chromium_path`。

### 权限命令报错

当前 mock 的群成员权限默认都是普通成员。如需管理员/群主权限，需要修改 `mock-bot.js` 中的 `createMockGroup` 权限返回值。
