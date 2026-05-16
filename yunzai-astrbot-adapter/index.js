import WsServer from './ws-server.js'

/**
 * AstrBot 适配器插件入口
 * 在 Yunzai 插件加载时自动启动 WebSocket 服务器
 */
export default class AstrBotAdapter {
    constructor() {
        this.name = 'AstrBot适配器'
        this.dsc = '通过 WebSocket 与 AstrBot 双向通信'
        this.event = 'message'
        this.priority = 1
        // 不注册任何命令规则，纯适配器
        this.rule = []

        // 启动 WebSocket 服务器
        WsServer.start()
    }
}
