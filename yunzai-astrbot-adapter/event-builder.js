/**
 * 将 AstrBot 消息转换为 icqq 风格的事件对象
 * 供 PluginsLoader.deal(e) 处理
 */

import {
    setWsConnection,
    ensureBotMock,
    createMockGroup,
    createMockFriend,
    parseMsgToJson,
    getWsConnection
} from './mock-bot.js'

/**
 * 根据 AstrBot 消息构造 Yunzai 事件对象
 * @param {Object} data AstrBot 发来的消息数据
 * @param {WebSocket} ws WebSocket 连接
 * @returns {Object} icqq 风格事件对象
 */
export function buildEvent(data, ws) {
    // 确保 Bot 全局变量和 mock 方法就绪
    ensureBotMock()
    setWsConnection(ws)

    const botUin = global.Bot.uin
    const isGroup = (data.message_type === 'group')
    const userId = String(data.user_id || '')
    const groupId = isGroup ? String(data.group_id || '') : undefined

    // 发送者信息
    const sender = data.sender || { nickname: '未知用户', card: '' }
    if (!sender.card) sender.card = sender.nickname || '未知用户'

    // 转换消息格式（AstrBot → icqq segment）
    const message = convertIncomingMessages(data.message || data.content || [])

    // 提取纯文本作为 raw_message
    const rawMessage = message
        .filter(m => m.type === 'text')
        .map(m => m.text)
        .join('')

    // 会话信息，用于 reply 时回传
    const session = {
        target_type: isGroup ? 'group' : 'private',
        target_id: isGroup ? groupId : userId,
        user_id: userId,
        group_id: groupId,
        msg_id: data.msg_id || String(Date.now()),
        bot_self_id: data.bot_self_id || botUin
    }

    // 构造核心事件对象
    const e = {
        post_type: 'message',
        message_type: data.message_type || 'private',
        sub_type: 'normal',
        self_id: botUin,
        user_id: userId,
        group_id: groupId,
        message: message,
        raw_message: rawMessage,
        sender: sender,
        time: Math.floor(Date.now() / 1000),
        message_id: session.msg_id,

        // 这是 Yunzai 会包装为 e.replyNew 的原始 reply
        // 插件最终调用的 e.reply 会先经过 Yunzai 的包装层处理 at/quote 等
        reply: async (msg, quote) => {
            return await handleReply(msg, quote, session)
        }
    }

    // 绑定 bot（Yunzai deal() 中会再次 defineProperty，这里先提供默认值）
    Object.defineProperty(e, 'bot', {
        value: global.Bot[botUin] || global.Bot,
        writable: true,
        configurable: true
    })

    // 绑定群对象（私聊时不设置）
    if (isGroup && groupId) {
        e.group = createMockGroup(groupId, userId)
    }

    // 绑定好友对象（群聊时可选，某些插件会检查）
    e.friend = createMockFriend(userId)

    // 绑定 member 对象（群聊权限检查需要）
    if (isGroup) {
        e.member = {
            card: sender.card,
            nickname: sender.nickname,
            is_owner: false,
            is_admin: false,
            // _info 被 checkMemberInfo 等代码检查存在性
            _info: {
                card: sender.card,
                nickname: sender.nickname,
                is_owner: false,
                is_admin: false
            }
        }
    }

    return e
}

/**
 * AstrBot 消息格式 → icqq segment 格式
 */
function convertIncomingMessages(msgs) {
    const result = []
    for (const msg of msgs) {
        if (!msg || !msg.type) continue

        switch (msg.type) {
            case 'text':
                result.push({ type: 'text', text: msg.data || msg.text || '' })
                break

            case 'image':
                // AstrBot 发来的是 data（base64 或 URL）
                // icqq 用 file 存储，Yunzai dealMsg() 会读取 val.url
                const imgData = msg.data || msg.url || ''
                result.push({ type: 'image', file: imgData, url: imgData })
                break

            case 'at':
                result.push({ type: 'at', qq: Number(msg.data || msg.qq || 0) })
                break

            case 'face':
                result.push({ type: 'face', id: Number(msg.data || msg.id || 0) })
                break

            case 'reply':
                result.push({ type: 'reply', id: String(msg.data || msg.id || '') })
                break

            case 'file':
                result.push({ type: 'file', name: msg.name || msg.data || '', fid: msg.fid || '' })
                break

            default:
                // 未知类型透传
                result.push({ type: msg.type, ...msg })
        }
    }
    return result
}

/**
 * 处理插件回复，通过 WebSocket 发回 AstrBot
 */
async function handleReply(msg, quote, session) {
    const ws = getWsConnection()
    if (!ws || ws.readyState !== 1) {
        console.warn('[AstrBotAdapter] WebSocket 未连接，回复已丢弃')
        return { message_id: 'mock-' + Date.now() }
    }

    const content = parseMsgToJson(msg)
    const payload = {
        type: 'reply',
        target_type: session.target_type,
        target_id: session.target_id,
        user_id: session.user_id,
        group_id: session.group_id,
        msg_id: session.msg_id,
        bot_self_id: session.bot_self_id,
        content: content,
        quote: !!quote,
        time: Date.now()
    }

    ws.send(JSON.stringify(payload))

    // 返回模拟的 msgRes，满足部分插件对 message_id 的依赖
    return { message_id: 'mock-' + Date.now() }
}
