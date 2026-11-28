# Celery 使用指南

本文面向 HomeOps 的开发与部署人员，说明如何在当前 Django + Docker Compose 环境中创建、调用、监控和排查 Celery 异步任务。

## 1. 当前架构

```text
Django / DRF
    │ delay() / apply_async()
    ▼
Redis 0 号库（Broker）
    │
    ▼
celery-worker
    │ 执行任务，可访问 PostgreSQL 和其他内部服务
    ▼
Redis 1 号库（Result Backend）
    │
    ▼
AsyncResult 查询状态和返回值
```

| 项目 | 当前配置 |
| --- | --- |
| Celery 应用 | `backend` |
| Broker | `redis://redis:6379/0` |
| Result Backend | `redis://redis:6379/1` |
| Worker 服务 | `celery-worker` |
| 默认单 Worker 并发 | 5 |
| 参数及结果序列化 | JSON |
| 结果保留时间 | 1 天 |
| Redis 持久化 | AOF |
| Redis 数据目录 | `docker/redis/data` |
| Redis 网络 | 仅 Compose 内网，不映射宿主机端口 |

相关实现：

- [Celery 应用初始化](../backend/backend/celery.py)
- [Django 中的 Celery 配置](../backend/backend/settings.py)
- [Redis 与 Worker 的 Compose 配置](../docker-compose.yml)
- [Python 依赖](../backend/requirements.txt)

## 2. 启动和停止

### 2.1 启动 Celery 相关服务

```bash
docker compose up -d --build backend celery-worker redis
```

`db` 是后端和 Worker 的依赖，如果尚未运行，Compose 也会一并启动。

### 2.2 查看运行状态

```bash
docker compose ps
```

应至少看到：

- `backend`
- `db`
- `redis`
- `celery-worker`

### 2.3 停止 Worker

```bash
docker compose stop celery-worker
```

停止 Worker 后，新任务仍会由后端写入 Broker，但不会被处理。恢复 Worker：

```bash
docker compose start celery-worker
```

### 2.4 停止全部服务

```bash
docker compose stop
```

停止服务前请确认队列中的任务情况。不要清理 Redis 数据目录，否则可能丢失尚未执行的任务和任务结果。

## 3. 验证安装和完整任务链路

### 3.1 检查 Redis

```bash
docker compose exec redis redis-cli ping
```

预期输出：

```text
PONG
```

### 3.2 检查 Worker

```bash
docker compose exec backend celery -A backend inspect ping
```

预期结果包含：

```text
1 node online.
```

### 3.3 执行健康检查任务

项目内置了 `backend.celery_healthcheck`，用于验证 Broker、Worker 和 Result Backend 的完整链路：

```bash
docker compose exec backend python manage.py shell -c \
  "from backend.celery import celery_healthcheck; result = celery_healthcheck.delay(); print(result.get(timeout=10))"
```

预期输出：

```text
ok
```

这里的 `result.get()` 仅用于健康检查，不建议在真实 Web 请求中等待耗时任务。

## 4. 创建业务任务

### 4.1 选择任务所属应用

任务应放在所属 Django 应用的 `tasks.py` 中，例如：

```text
backend/accounts/tasks.py
backend/ai_assistant/tasks.py
backend/system_setting/tasks.py
```

对应应用必须已加入 `INSTALLED_APPS`。Celery 会通过 `autodiscover_tasks()` 自动加载这些文件。

### 4.2 创建第一个示例任务

以下示例需要自行创建 `backend/accounts/tasks.py`：

```python
from celery import shared_task


@shared_task(name='accounts.add')
def add(x: int, y: int) -> int:
    return x + y
```

建议：

- 使用 `@shared_task`，减少业务模块与项目 Celery 实例之间的耦合。
- 为任务设置唯一、稳定的名称。
- 参数和返回值保持 JSON 可序列化。
- 传数据库主键，不传 Django Model 实例、数据库连接或文件句柄。

### 4.3 重启 Worker 加载任务

```bash
docker compose restart celery-worker
```

检查任务是否注册：

```bash
docker compose exec backend celery -A backend inspect registered
```

输出中应包含：

```text
accounts.add
backend.celery_healthcheck
```

## 5. 调用任务

### 5.1 在 Django Shell 中验证

```bash
docker compose exec backend python manage.py shell -c \
  "from accounts.tasks import add; result = add.delay(2, 3); print('task_id:', result.id); print('result:', result.get(timeout=10))"
```

预期输出类似：

```text
task_id: 1e27a5a9-7fb4-43d1-894d-63caf3b09f7b
result: 5
```

### 5.2 `delay()` 与 `apply_async()`

立即执行：

```python
result = add.delay(2, 3)
```

等价于：

```python
result = add.apply_async(args=[2, 3])
```

延迟 10 秒执行：

```python
result = add.apply_async(args=[2, 3], countdown=10)
```

指定在某一时间执行可以使用 `eta`。`countdown` 和 `eta` 不需要 Celery Beat；Beat 用于周期性计划任务。

### 5.3 在 API 中创建任务

真实接口通常返回 HTTP 202 和 `task_id`：

```python
from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import add


class AddTaskView(APIView):

    def post(self, request):
        result = add.delay(2, 3)
        return Response({'task_id': result.id}, status=202)
```

前端保存 `task_id`，再通过状态查询接口或消息通知获取结果，不要让创建任务的请求长时间阻塞。

## 6. 查询任务状态和结果

```python
from backend.celery import app


result = app.AsyncResult('任务 ID')

print(result.id)
print(result.state)

if result.successful():
    print(result.result)
```

常见状态：

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 等待执行，或任务 ID 不存在、结果已过期 |
| `STARTED` | Worker 已开始执行 |
| `SUCCESS` | 执行成功 |
| `FAILURE` | 执行失败 |
| `RETRY` | 等待重试 |

注意：

- `PENDING` 不一定代表任务仍在队列中，需要结合 Worker 和日志判断。
- 结果默认只保留一天。
- API 不应直接把完整异常堆栈或内部敏感信息返回给前端。
- 不要在 Celery 任务内部同步等待另一个任务的 `get()`，避免 worker 资源被耗尽。

## 7. 并发控制

### 7.1 当前默认配置

Worker 启动命令包含：

```text
--concurrency=${CELERY_WORKER_CONCURRENCY:-5}
```

未配置环境变量时，一个 Worker 容器最多同时执行 5 个任务，第 6 个任务会在队列中等待。

### 7.2 调整为 6 个并发

在项目根目录的 `.env` 中添加：

```dotenv
CELERY_WORKER_CONCURRENCY=6
```

重新创建 Worker，使 Compose 启动命令生效：

```bash
docker compose up -d --force-recreate celery-worker
```

不要只执行 `docker compose restart celery-worker`，因为 `restart` 不会应用 Compose 中的新启动命令。

查看实际 Worker 配置：

```bash
docker compose exec backend celery -A backend inspect stats
```

### 7.3 Worker 容器数与总并发

默认使用 `prefork` 进程池。总并发近似为：

```text
Worker 容器数 × 每个 Worker 的 concurrency
```

例如：

```bash
docker compose up -d --scale celery-worker=3
```

若每个 Worker 并发为 5，则理论上最多同时执行 15 个任务。

如果要求整个系统最多同时执行 5 个任务，应保持：

- 一个 `celery-worker` 容器；
- `CELERY_WORKER_CONCURRENCY=5`；
- 不通过 `--scale` 增加 Worker。

提高并发前应评估 CPU、内存、数据库连接数和外部服务限流，不是越大越好。

## 8. 失败重试与执行时间

任务模板示例：

```python
from celery import shared_task


@shared_task(
    name='accounts.fetch_remote_data',
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_kwargs={'max_retries': 3, 'countdown': 5},
    soft_time_limit=240,
    time_limit=300,
)
def fetch_remote_data(self, resource_id: int) -> dict:
    # 在这里执行实际的远程调用和数据库操作。
    return {'resource_id': resource_id, 'status': 'success'}
```

配置含义：

- `autoretry_for`：只对指定异常自动重试。
- `max_retries`：最大重试次数。
- `countdown`：重试前等待秒数。
- `soft_time_limit`：软时间限制，任务可捕获异常并清理资源。
- `time_limit`：硬时间限制，防止任务无限执行。

所有可能重试或被重新投递的任务都应尽量保证幂等，即重复执行不会产生额外副作用。

## 9. 数据库事务注意事项

不推荐在事务提交前立即发送任务：

```python
server = Server.objects.create(...)
sync_server.delay(server.id)
```

Worker 可能先开始执行，却读不到尚未提交的数据。推荐：

```python
from django.db import transaction


server = Server.objects.create(...)
transaction.on_commit(lambda: sync_server.delay(server.id))
```

任务内部再根据主键查询最新数据。

## 10. 常用运维命令

```bash
# 查看 Worker 日志
docker compose logs --tail=100 -f celery-worker

# 查看 Redis 日志
docker compose logs --tail=100 -f redis

# 查看在线 Worker
docker compose exec backend celery -A backend inspect ping

# 查看已注册任务
docker compose exec backend celery -A backend inspect registered

# 查看正在执行的任务
docker compose exec backend celery -A backend inspect active

# 查看带 ETA、等待执行的任务
docker compose exec backend celery -A backend inspect scheduled

# 查看 Worker 已预取但尚未开始执行的任务
docker compose exec backend celery -A backend inspect reserved

# 查看并发和运行统计
docker compose exec backend celery -A backend inspect stats

# 查看 Redis 各逻辑库的键数量
docker compose exec redis redis-cli info keyspace
```

除非明确需要清空任务，否则不要随意执行：

- `celery purge`
- `redis-cli FLUSHDB`
- `redis-cli FLUSHALL`

这些操作可能造成任务或结果丢失。

## 11. 修改后的重启方式

| 修改内容 | 推荐操作 |
| --- | --- |
| 只修改已有任务函数代码 | `docker compose restart celery-worker` |
| 新增 `tasks.py` 或新任务 | `docker compose restart celery-worker`，调用方后端必要时一并重启 |
| 修改 Worker 并发或启动命令 | `docker compose up -d --force-recreate celery-worker` |
| 修改 Python 依赖 | `docker compose up -d --build backend celery-worker` |
| 修改 Broker 或 Result Backend | 同时重新创建 `backend` 和 `celery-worker` |
| 修改 Redis 配置 | `docker compose up -d --force-recreate redis celery-worker backend` |

修改 Broker 或 Result Backend 前应先处理队列中的未完成任务，避免切换后任务无人消费或结果无法查询。

## 12. 故障排查

| 现象 | 检查方向 |
| --- | --- |
| `Connection refused` | Redis 是否运行；Broker 是否指向 `redis://redis:6379/0` |
| 任务一直是 `PENDING` | Worker 是否在线；两端 Broker 是否一致；结果是否已过期 |
| `Received unregistered task` | 是否重启 Worker；任务是否位于已安装应用的 `tasks.py`；任务名是否一致 |
| Worker 完全没有任务日志 | 是否使用了不同 Redis 地址、不同 Redis DB 或不同队列 |
| 任务成功但查询不到结果 | 两端 Result Backend 是否一致；是否设置了 `ignore_result=True`；结果是否过期 |
| 新增任务后找不到 | 是否重启 Worker；对应 App 是否加入 `INSTALLED_APPS` |
| 任务读取不到刚创建的数据 | 是否在数据库事务提交前发送任务；改用 `transaction.on_commit()` |
| Worker 出现数据库连接错误 | PostgreSQL 是否健康；Worker 数据库配置是否正确；连接数是否耗尽 |
| 修改并发后没有生效 | 是否使用 `up --force-recreate` 重新创建 Worker |
| 任务重复产生副作用 | 是否发生重试或重复投递；任务是否具备幂等保护 |

排查时建议按以下顺序：

1. `docker compose ps` 检查容器状态。
2. 检查 Redis `PING`。
3. 检查 Celery `inspect ping`。
4. 检查 `inspect registered`。
5. 查看 Worker 日志中的任务接收和异常信息。
6. 核对后端与 Worker 的 Broker、Result Backend 环境变量。

## 13. 后续按需扩展

当前基础配置不需要以下组件，但可按业务需求增加：

| 扩展 | 使用场景 |
| --- | --- |
| Celery Beat | 每小时、每天等周期性任务 |
| `django-celery-beat` | 通过 Django Admin 或数据库管理周期计划 |
| Flower | Web 页面监控 Worker、任务和失败信息 |
| `django-celery-results` | 将任务结果存入 PostgreSQL |
| 自定义 Queue 和路由 | 将 AI、运维、通知等任务分开消费和限流 |
| RabbitMQ | 需要更复杂的消息路由和消息治理能力 |

注意：

- Celery Beat 通常只运行一个实例，避免周期任务重复发送。
- 长期任务审计应设计专门的业务任务表，而不是无限延长 Redis 结果保留时间。
- Redis 若需要对外开放，必须重新评估 ACL、密码、网络访问控制和加密连接。
- AOF 可以降低数据丢失风险，但不能替代幂等、重试和失败补偿设计。
