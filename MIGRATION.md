# 迁移指南：从本地 Docker 到远程服务器

本文档说明如何将本地 Docker 测试环境完整迁移到远程服务器。

## 需要迁移的数据

| 目录/文件 | 内容 | 是否必须 |
|-----------|------|----------|
| `Docker/yunzai/config/` | Yunzai 配置（bot.yaml、redis.yaml 等） | 是 |
| `Docker/yunzai/plugins/` | Yunzai 插件（miao-plugin、适配器等） | 是 |
| `Docker/data/` | AstrBot 数据（插件配置、知识库、用户数据） | 是 |
| `Docker/redis-data/` | Redis 持久化数据（用户配置、缓存） | 推荐 |
| `Docker/docker-compose.yml` | 容器编排配置 | 是 |
| `Docker/yunzai/Dockerfile` | Yunzai 镜像构建文件 | 是 |

## 迁移步骤

### 1. 本地打包

```bash
cd /path/to/astrbot-a-yunzai/Docker

# 创建迁移包（排除日志和临时文件）
tar czf ../migration.tar.gz \
    --exclude='*.log' \
    --exclude='__pycache__' \
    --exclude='node_modules' \
    yunzai/ data/ redis-data/ docker-compose.yml
```

### 2. 上传到远程服务器

```bash
# 方式 A：scp
scp migration.tar.gz root@your-server-ip:/opt/

# 方式 B：rsync（推荐，支持断点续传）
rsync -avz --progress migration.tar.gz root@your-server-ip:/opt/
```

### 3. 远程服务器解压并启动

```bash
ssh root@your-server-ip

# 解压
cd /opt
mkdir -p astrbot-yunzai && cd astrbot-yunzai
tar xzf ../migration.tar.gz

# 启动（首次会自动构建 Yunzai 镜像）
docker-compose up -d

# 查看状态
docker-compose ps
docker-compose logs -f yunzai
```

### 4. 验证

```bash
# 测试 WebSocket 连通性
docker exec astrbot python3 -c "
import asyncio, websockets
async def test():
    async with websockets.connect('ws://yunzai:8766') as ws:
        print('连接成功')
asyncio.run(test())
"
```

## Redis 数据说明

- Redis 默认使用内存存储，容器重建后数据丢失
- `docker-compose.yml` 已配置 `./redis-data:/data` 持久化卷
- 如需导出/导入特定数据：

```bash
# 导出 Redis 数据
docker exec redis redis-cli SAVE
docker cp redis:/data/dump.rdb ./redis-backup.rdb

# 导入 Redis 数据
docker cp ./redis-backup.rdb redis:/data/dump.rdb
docker restart redis
```

## 网络配置注意事项

远程服务器需要开放以下端口：

| 端口 | 用途 | 是否必须暴露到公网 |
|------|------|-------------------|
| 6185 | AstrBot WebUI / ChatUI | 按需（建议加反代+认证） |
| 8766 | Yunzai WebSocket | 否（仅容器内通信） |
| 6379 | Redis | 否（仅容器内通信） |

**安全建议：**
- 6185 端口不要直接暴露在公网，通过 Nginx/Caddy 反代并加 HTTPS
- 或使用 SSH 隧道本地访问：`ssh -L 6185:localhost:6185 root@your-server-ip`
