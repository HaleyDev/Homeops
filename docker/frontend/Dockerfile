########## 构建阶段 ##########
# 构建上下文为 frontend/ 目录（见 docker-compose.yml 的 build.context）
FROM node:24-alpine AS builder

ENV CI=true \
    NODE_OPTIONS=--max-old-space-size=8192 \
    COREPACK_NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /homeops

# 通过 corepack 启用 packageManager 字段锁定的 pnpm 版本
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc turbo.json ./
COPY internal ./internal
COPY packages ./packages
COPY web/package.json ./web/

RUN pnpm install --frozen-lockfile

COPY web ./web
RUN pnpm build:web

########## 运行阶段 ##########
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /homeops/web/dist /usr/share/nginx/html

EXPOSE 80
