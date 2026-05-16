/**
 * WebSocket 服务器
 * 接收 AstrBot 消息并转发给 Yunzai 插件系统
 */

import { WebSocketServer } from 'ws'
import { buildEvent } from './event-builder.js'
import { setWsConnection, ensureBotMock } from './mock-bot.js'

const WS_PORT = Number(process.env.ASTRBOT_WS_PORT) || 8766
const WS_HOST = process.env.ASTRBOT_WS_HOST || '0.0.0.0'

let wss = null
let pluginsLoader = null

/**
 * 启动 WebSocket 服务器
 */
export async function start() {
    // 确保 Bot mock 已初始化
    ensureBotMock()

    // 动态导入 PluginsLoader（skip_login 模式下已加载完成）
    try {
        const mod = await import('../../lib/plugins/loader.js')
        pluginsLoader = mod.default
    } catch (err) {
        console.error('[AstrBotAdapter] 加载 PluginsLoader 失败:', err)
        return
    }

    if (wss) {
        console.log('[AstrBotAdapter] WebSocket 服务器已在运行')
        return
    }

    wss = new WebSocketServer({ host: WS_HOST, port: WS_PORT })

    wss.on('listening', () => {
        console.log(`[AstrBotAdapter] WebSocket 服务器已启动: ws://${WS_HOST}:${WS_PORT}`)
    })

    wss.on('connection', (ws, req) => {
        console.log(`[AstrBotAdapter] 新连接: ${req.socket.remoteAddress}`)
        setWsConnection(ws)

        // 发送连接成功确认
        ws.send(JSON.stringify({ type: 'connected', msg: 'Yunzai adapter ready' }))

        ws.on('message', async (data) => {
            try {
                const payload = JSON.parse(data.toString())
                await handleMessage(ws, payload)
            } catch (err) {
                console.error('[AstrBotAdapter] 消息解析错误:', err)
                ws.send(JSON.stringify({ type: 'error', msg: 'Invalid JSON' }))
            }
        })

        ws.on('close', () => {
            console.log('[AstrBotAdapter] 连接已断开')
            setWsConnection(null)
        })

        ws.on('error', (err) => {
            console.error('[AstrBotAdapter] WebSocket 错误:', err)
            setWsConnection(null)
        })
    })

    wss.on('error', (err) => {
        console.error('[AstrBotAdapter] WebSocketServer 错误:', err)
    })
}

/**
 * 处理 AstrBot 发来的消息
 */
async function handleMessage(ws, payload) {
    switch (payload.type) {
        case 'message':
            await handleIncomingMessage(ws, payload)
            break

        case 'ping':
            ws.send(JSON.stringify({ type: 'pong', time: Date.now() }))
            break

        default:
            console.warn(`[AstrBotAdapter] 未知消息类型: ${payload.type}`)
    }
}

/**
 * 处理业务消息：构造事件对象并交给 Yunzai 插件系统
 */
async function handleIncomingMessage(ws, data) {
    if (!pluginsLoader) {
        console.error('[AstrBotAdapter] PluginsLoader 未就绪')
        ws.send(JSON.stringify({ type: 'error', msg: 'PluginsLoader not ready' }))
        return
    }

    // 构造 icqq 风格事件对象
    const e = buildEvent(data, ws)

    // 调试日志
    const logPrefix = e.isGroup ? `[群${e.group_id}]` : '[私聊]'
    console.log(`[AstrBotAdapter] ${logPrefix} ${e.sender?.card || e.user_id}: ${e.raw_message || ''}`)

    try {
        // 交给 Yunzai 处理（这是核心入口）
        await pluginsLoader.deal(e)
    } catch (err) {
        console.error('[AstrBotAdapter] 插件处理错误:', err)
        // 向 AstrBot 返回错误提示
        ws.send(JSON.stringify({
            type: 'reply',
            target_type: e.group_id ? 'group' : 'private',
            target_id: e.group_id || e.user_id,
            content: [{ type: 'text', data: '处理出错，请查看日志' }],
            time: Date.now()
        }))
    }
}

export default { start }
