# HomeOps

内网服务器的运维工具集成平台，把零散的基础设施入口整合到一个统一的 Web 界面。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端 | Django 6.1 + DRF + SimpleJWT，PostgreSQL 17 + pgvector，uWSGI |
| 异步任务 | Celery + Redis（Broker 与任务结果后端） |
| 前端 | Vue 3 + Vite + [Vben Admin](https://vben.pro)（Naive UI），Nginx |
| 认证 | 账号密码 + GitLab OIDC（mozilla-django-oidc） |
| 日志 | structlog + django-structlog，DEBUG 下彩色文本，生产 JSON |
| 部署 | Docker Compose，GitLab CI（self-hosted runner 构建并推送镜像至 Harbor） |

## 目录结构

```
backend/    Django 项目（accounts 应用：认证与用户信息接口）
frontend/   Vben Admin 单页应用（web/ 为业务代码）
docker/     各服务 Dockerfile 与数据挂载目录（postgres、redis、elasticsearch）
docs/       OIDC 登录、前后端改动等设计文档
```

## 快速开始

在项目根目录创建 `.env`（已 gitignore），至少包含：`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`OIDC_RP_CLIENT_ID`、`OIDC_RP_CLIENT_SECRET`，可选 `LOG_LEVEL`、`ALLOWED_HOSTS`、`FRONTEND_URL` 等。

PostgreSQL 数据保存在 `docker/postgres/data`，首次初始化时会自动启用 `vector` 扩展。本配置不读取或迁移旧 MySQL 数据。

```bash
docker compose up -d --build
```

- 前端：<http://localhost:9000>
- 后端 API：<http://localhost:8000/api/>
- Elasticsearch：<http://localhost:9200>

前端开发调试：

```bash
cd frontend && pnpm install && pnpm dev
```

Vite 已配置 `/api` 代理到 `localhost:8000`。

## Celery

Compose 默认启动 Redis 和 `celery-worker`。Redis 的 0 号库用作 Broker，1 号库保存任务结果；数据保存在 `docker/redis/data`，且仅在 Compose 内网开放。

在各 Django 应用的 `tasks.py` 中使用 `@shared_task` 声明任务，Celery 会自动发现。可通过环境变量 `CELERY_BROKER_URL` 和 `CELERY_RESULT_BACKEND` 覆盖默认连接。

Worker 默认最多同时执行 5 个任务，可在 `.env` 中设置 `CELERY_WORKER_CONCURRENCY=6` 等值调整并发数。

完整说明见 [Celery 使用指南](docs/celery-usage-guide.md)。

```bash
# 查看 Worker 日志
docker compose logs -f celery-worker

# 检查 Worker 与 Broker 的连通性
docker compose exec backend celery -A backend inspect ping
```

## CI/CD

push 到 `main` 或在 GitLab 页面手动 Run pipeline，均由 `gti-host` runner 构建前后端镜像并推送到 Harbor。部署在服务器上手动执行：

```bash
docker compose pull && docker compose up -d
```

> 项目处于早期阶段，功能持续补充中。
