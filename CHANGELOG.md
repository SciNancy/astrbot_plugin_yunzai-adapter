# 更新日志

## 2026-05-31

- **修复**：Yunzai 发送多条消息时 AstrBot 只转发一条的问题
  - AstrBot 端：`main.py` 中保存 `group_id` 到 `pending_events`，让群聊时 `target_id` 匹配能工作；增加详细调试日志便于排查
  - Yunzai 端：`mock-bot.js` 的 `sendOutgoingMsg` 函数之前丢失了 `msg_id`/`user_id`/`group_id`/`bot_self_id`，导致插件通过 `e.group.sendMsg()` / `Bot.sendGroupMsg()` 等间接路径发送的后续消息无法被 AstrBot 匹配到原始 event
- **文件**：`main.py`、`mock-bot.js`、`event-builder.js`

## 2026-05-20

- **功能**：添加独占前缀过滤机制，只有匹配 `YUNZAI_ONLY_PREFIXES` 配置前缀的消息才会转发给 Yunzai，并阻断 AstrBot LLM 后续处理
- **文件**：`main.py`
