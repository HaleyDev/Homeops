FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /homeops

# 先单独复制依赖清单（利用层缓存：代码改动时不会重新安装依赖）
COPY requirements.txt .

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc libc6-dev pkg-config \
    && pip install --no-cache-dir \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        -r requirements.txt \
    && apt-get purge -y gcc libc6-dev pkg-config \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8000

# 等 30 秒让数据库就绪，先执行迁移再启动（等待时长可用环境变量 DB_WAIT_SECONDS 覆盖）
CMD ["sh", "-c", "sleep ${DB_WAIT_SECONDS:-30} && python manage.py migrate --noinput && exec uwsgi --ini uwsgi.ini"]
