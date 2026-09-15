# HomeOps

内网服务器的运维工具集成平台，把零散的基础设施入口整合到一个统一的 Web 界面。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端 | Django 6.1 + DRF + SimpleJWT，MySQL 8.4，uWSGI |
| 前端 | Vue 3 + Vite + [Vben Admin](https://vben.pro)（Naive UI），Nginx |
| 认证 | 账号密码 + GitLab OIDC（mozilla-django-oidc） |
| 日志 | structlog + django-structlog，DEBUG 下彩色文本，生产 JSON |
| 部署 | Docker Compose，GitLab CI（self-hosted runner 构建并推送镜像至 Harbor） |

## 目录结构

```
backend/    Django 项目（accounts 应用：认证与用户信息接口）
frontend/   Vben Admin 单页应用（web/ 为业务代码）
docker/     各服务 Dockerfile 与数据挂载目录（mysql、elasticsearch）
docs/       OIDC 登录、前后端改动等设计文档
```

## 快速开始

在项目根目录创建 `.env`（已 gitignore），至少包含：`MYSQL_ROOT_PASSWORD`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD`、`OIDC_RP_CLIENT_ID`、`OIDC_RP_CLIENT_SECRET`，可选 `LOG_LEVEL`、`ALLOWED_HOSTS`、`FRONTEND_URL` 等。

```bash
docker compose up -d
```

- 前端：<http://localhost:9000>
- 后端 API：<http://localhost:8000/api/>
- Elasticsearch：<http://localhost:9200>

前端开发调试：

```bash
cd frontend && pnpm install && pnpm dev
```

Vite 已配置 `/api` 代理到 `localhost:8000`。

## CI/CD

push 到 `main` 或在 GitLab 页面手动 Run pipeline，均由 `gti-host` runner 构建前后端镜像并推送到 Harbor。部署在服务器上手动执行：

```bash
docker compose pull && docker compose up -d
```

> 项目处于早期阶段，功能持续补充中。
