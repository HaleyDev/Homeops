FROM python:3.13

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /homeops

# 安装系统依赖（libpq-dev 供 psycopg2，default-libmysqlclient-dev + pkg-config 供 mysqlclient）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000
