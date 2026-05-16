/**
 * Mock Bot、群、好友等 icqq 对象
 * 将插件发出的消息通过 WebSocket 转发回 AstrBot
 */

let wsConnection = null

export function setWsConnection(ws) {
    wsConnection = ws
}

export function getWsConnection() {
    return wsConnection
}

/**
 * 创建模拟群对象
 * @param {string} groupId 群ID
 * @param {string} userId 当前用户ID（用于at和权限mock）
 */
export function createMockGroup(groupId, userId) {
    return {
        group_id: groupId,
        name: `群${groupId}`,
        mute_left: 0,

        async sendMsg(msg) {
            return await sendOutgoingMsg(msg, 'group', groupId)
        },

        async recallMsg(msgId) {
            console.log(`[MockGroup] 撤回消息: ${msgId}`)
            return true
        },

        pickMember(uid) {
            return {
                get info() {
                    return {
                        user_id: uid,
                        card: `用户${uid}`,
                        nickname: `用户${uid}`,
                        is_owner: false,
                        is_admin: false
                    }
                }
            }
        }
    }
}

/**
 * 创建模拟好友对象
 * @param {string} userId 用户ID
 */
export function createMockFriend(userId) {
    return {
        user_id: userId,
        nickname: `用户${userId}`,

        async sendMsg(msg) {
            return await sendOutgoingMsg(msg, 'private', userId)
        },

        async recallMsg(msgId) {
            console.log(`[MockFriend] 撤回消息: ${msgId}`)
            return true
        }
    }
}

/**
 * 确保 Bot 全局变量具备必要的方法
 */
export function ensureBotMock() {
    if (!global.Bot) {
        global.Bot = {}
    }
    const bot = global.Bot

    // 确保有 uin
    if (!bot.uin) {
        bot.uin = bot.self_id || '88888'
    }

    // Bot[uin] 指向自己（Yunzai skip_login 已做，这里做保险）
    if (!bot[bot.uin]) {
        bot[bot.uin] = bot
    }

    // 好友列表
    if (!bot.fl) {
        bot.fl = new Map()
    }

    // 群列表
    if (!bot.gl) {
        bot.gl = new Map()
    }

    // pickUser：返回模拟好友对象
    if (!bot.pickUser) {
        bot.pickUser = (uid) => createMockFriend(uid)
    }

    // pickGroup：返回模拟群对象
    if (!bot.pickGroup) {
        bot.pickGroup = (gid) => createMockGroup(gid)
    }

    // sendPrivateMsg：转发私聊
    if (!bot.sendPrivateMsg) {
        bot.sendPrivateMsg = async (user_id, msg) => {
            return await sendOutgoingMsg(msg, 'private', user_id)
        }
    }

    // sendGroupMsg：转发群聊
    if (!bot.sendGroupMsg) {
        bot.sendGroupMsg = async (group_id, msg) => {
            return await sendOutgoingMsg(msg, 'group', group_id)
        }
    }
}

/**
 * 将插件发出的消息转发给 AstrBot
 */
async function sendOutgoingMsg(msg, targetType, targetId) {
    if (!wsConnection || wsConnection.readyState !== 1) {
        console.warn('[AstrBotAdapter] WebSocket 未连接，消息丢弃')
        return { message_id: 'mock-' + Date.now() }
    }

    const content = parseMsgToJson(msg)
    const payload = {
        type: 'reply',
        target_type: targetType,
        target_id: targetId,
        content: content,
        time: Date.now()
    }

    wsConnection.send(JSON.stringify(payload))
    return { message_id: 'mock-' + Date.now() }
}

/**
 * 将 icqq 格式的消息解析为 JSON 数组
 * 支持字符串、segment 对象、segment 数组
 */
export function parseMsgToJson(msg) {
    if (!msg) return []

    // 字符串直接转 text
    if (typeof msg === 'string') {
        return [{ type: 'text', data: msg }]
    }

    // 单个 segment 对象
    if (msg.type) {
        return [segmentToJson(msg)]
    }

    // 数组
    if (Array.isArray(msg)) {
        const result = []
        for (const item of msg) {
            if (typeof item === 'string') {
                if (item) result.push({ type: 'text', data: item })
            } else if (item && item.type) {
                result.push(segmentToJson(item))
            }
        }
        return result
    }

    // 未知类型，尝试 JSON 序列化
    return [{ type: 'text', data: String(msg) }]
}

/**
 * 单个 icqq segment 转 JSON
 */
function segmentToJson(seg) {
    switch (seg.type) {
        case 'text':
            return { type: 'text', data: seg.text || seg.data || '' }

        case 'image':
            // file 可能是 base64 字符串、URL、Buffer
            let imgData = seg.file || seg.url || ''
            if (Buffer.isBuffer(imgData)) {
                imgData = 'base64://' + imgData.toString('base64')
            }
            return { type: 'image', data: imgData }

        case 'at':
            return { type: 'at', data: String(seg.qq || seg.id || '') }

        case 'face':
            return { type: 'face', data: String(seg.id || '') }

        case 'reply':
            return { type: 'reply', data: String(seg.id || '') }

        case 'video':
            return { type: 'video', data: seg.file || seg.url || '' }

        case 'record':
            return { type: 'record', data: seg.file || seg.url || '' }

        case 'file':
            return { type: 'file', data: seg.name || seg.file || '' }

        case 'node':
            // 合并转发节点，简化处理
            return { type: 'node', data: seg.data || seg.id || '' }

        default:
            return { type: seg.type || 'unknown', data: seg.data || seg.text || String(seg) }
    }
}
