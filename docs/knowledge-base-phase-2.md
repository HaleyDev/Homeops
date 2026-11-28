# HomeOps 知识库第二阶段：向量化、Celery 异步任务与前端轮询实施设计

- 文档状态：实施前设计稿，待评审后编码
- 更新日期：2026-11-15
- 前置文档：[第一阶段：知识库与文件上传管理](./knowledge-base-phase-1.md)
- 对应总体方案：[HomeOps 知识库与 RAG 实施方案](./knowledge-base-design.md)
- 本阶段目标：上传后自动完成文本分块、Embedding 和 pgvector 入库；前端可看到处理状态、失败原因并手动重试
- 本阶段不包含：Agent 检索工具、混合检索、rerank、PDF/OCR、独立 chunk 管理页面

## 1. 已确认需求与本阶段结论

本阶段按以下产品行为设计：

1. 文件上传成功后，自动进入 Celery 向量化任务；
2. 向量数据保存在 HomeOps 现有 PostgreSQL/pgvector，不引入独立向量数据库服务；
3. Embedding 必须使用“模型供应商”中当前选中的 Embedding 模型，与 Insight 的配置来源一致；
4. 向量维度固定为 **2048**，向量列为 `vector(2048)`，初期使用精确余弦计算，不创建普通 HNSW；
5. 文档状态至少包括 `uploaded / processing / ready / failed / deleting`；
6. 向量化失败时，将安全、可读的失败原因写入 `knowledge_documents.error_message`；
7. 文件列表展示失败原因，只有 `failed` 文件显示“重试”按钮；
8. 重试不是简单重放旧消息，而是递增 `ingestion_version` 后生成新任务；
9. 前端使用一个统一的 `watch` 管理轮询；
10. 当前知识库存在 `uploaded` 或 `processing` 文档时，每 **5 秒**重新请求一次该知识库的**完整文件列表**；
11. 不新增单文档状态查询接口，不为每个文件创建独立定时器；
12. 没有待处理文档、页签不可见、页面隐藏或组件卸载时停止轮询。

最终用户流程：

```text
上传文件
→ uploaded（等待处理）
→ processing（向量化中）
→ ready（已向量化）

任一处理环节失败
→ failed + error_message
→ 前端显示失败原因和“重试”
→ 重试后 version + 1、清空错误、重新进入 uploaded
```

## 2. 范围与不做事项

### 2.1 本阶段交付

- `knowledge_document_chunks` 表及 pgvector 向量字段和索引；
- Embedding 模型维度配置、配置快照和 OpenAI 兼容客户端；
- Unicode 文本分块、批量 Embedding、响应校验；
- Celery `knowledge` 独立队列和专用 Worker；
- 文档原子认领、版本幂等、最终向量事务和失败状态；
- 上传后自动投递、失败重试 API、超时任务对账；
- 文档完整列表轮询、错误展示和重试按钮；
- PostgreSQL、Celery、Embedding 契约和前端定时器测试。

### 2.2 本阶段不做

- `list_knowledge_bases` / `knowledge_search`；
- 对外直接搜索 chunk 的 HTTP API；
- 混合全文检索、相似度阈值、重排序；
- `ready` 文档的整库重建和 Embedding 模型迁移；
- PDF、Office、图片和 OCR；
- 独立任务历史表和 Celery 结果长期归档；
- 独立来源引用表和前端来源卡片。

> 本阶段实施期间应固定一个全局 Embedding 模型。切换模型后的 ready 文档批量重建，是后续检索上线前必须完成的独立工作，不在本次 retry 功能中隐式处理。

## 3. 总体架构

```text
管理员上传 Markdown/TXT
        │
        ▼
原文保存 + knowledge_documents(uploaded)
        │
        │ transaction.on_commit
        │ 仅传 document_id + ingestion_version
        ▼
Redis / Celery knowledge 队列
        │
        ▼
专用 Worker（初始 concurrency = 2）
        │
        ├─ 原子认领 uploaded → processing
        ├─ 加载一次 Embedding 配置快照
        ├─ 读取原文并分块
        ├─ 每 10 个 chunk 调用一次 Embedding API
        ├─ 校验数量、顺序、维度和数值
        └─ 事务替换 chunks 并标记 ready

处理失败
        └─ 同版本 processing → failed + error_message

前端
        │
        │ 有 uploaded/processing 时每 5 秒
        ▼
GET /api/knowledge-bases/{id}/documents/
返回当前知识库全部文档，一次请求刷新整个列表
```

持久化边界：

- 原文仍在第一阶段共享文件目录；
- 文件状态、错误和版本在 PostgreSQL 文档表；
- 分块原文、向量和模型身份在 PostgreSQL chunk 表；
- Redis 只负责 Celery 消息和短期执行结果，不是业务状态权威来源。

## 4. 向量数据库设计

### 4.1 模型来源与维度决策

本阶段明确固定以下决策：

```text
模型来源 = 系统设置“模型供应商”中当前选中的 Embedding 模型
KNOWLEDGE_EMBEDDING_DIMENSIONS = 2048
embedding = vector(2048)
distance = cosine
index = 初期不创建近似向量索引，使用精确余弦计算
```

具体要求：

- 复用 `system_setting_llmprovider` / `system_setting_llmmodel` 中的供应商、Base URL、API Key、模型 key 和当前 Embedding 选择；
- 模型配置来源和 2048 维约定与 Insight 保持一致；
- 不在 `knowledge` app 中另建供应商或 Embedding 密钥配置；
- 与 Insight 一致只表示模型配置和向量维度一致，HomeOps 仍使用自己的文档与 chunk 表，不直接共用 Insight 数据；
- 普通 pgvector HNSW 的 vector 维度上限为 2000，因此本阶段明确不创建 HNSW；
- 初期通过知识库、ready、版本和模型身份等普通索引过滤后执行精确余弦距离计算，并用真实数据监控耗时；
- 后续如果数据量证明精确检索不足，再单独评审 `halfvec`、量化或其他索引方案，不在本阶段擅自改变存储精度。

**阻断性前置检查：**实施迁移前，必须使用“模型供应商”里实际选中的 Embedding 模型完成一次连通性测试，确认返回维度确实为 2048。若返回其他维度：

1. 不得启动正式迁移或将文档标记为 ready；
2. 不得截断或填充向量；
3. 应修正当前供应商/模型选择或配置，使其与已确定的 2048 维契约一致；
4. 运行时出现维度不符必须写入 failed 和可读错误，不能将错误向量写入 chunk 表。

数据库维度不能只由环境变量决定。Model 和迁移中明确写为 2048，环境配置只用于一致性校验，不能在迁移后通过改环境变量静默改变列类型。

### 4.2 新增 `knowledge_document_chunks`

| 字段 | 建议类型/约束 | 说明 |
| --- | --- | --- |
| `id` | `BigAutoField`，主键 | chunk ID |
| `document` | `ForeignKey(KnowledgeDocument, on_delete=CASCADE, related_name=chunks)` | 所属文档 |
| `chunk_index` | `PositiveIntegerField`，CHECK `>= 0` | 从 0 开始的分块顺序 |
| `content` | `TextField` | 分块原文，不允许空白 |
| `source_meta` | `JSONField(default=dict, blank=True)` | 可选标题路径、字符起止位置等 |
| `embedding` | `VectorField(dimensions=2048)` | pgvector 向量 |
| `embedding_model` | `ForeignKey(system_setting.LLMModel, on_delete=PROTECT)` | 生成向量的模型配置 |
| `embedding_provider_id` | `BigIntegerField` | 供应商 ID 快照，避免同名模型混用 |
| `embedding_model_key` | `CharField(max_length=160)` | 模型 key 快照 |
| `embedding_dimensions` | `PositiveIntegerField` | 本文档写入时的维度快照，必须等于 2048 |
| `embedding_profile_hash` | `CharField(max_length=64)` | 非敏感模型配置指纹 |
| `ingestion_version` | `PositiveIntegerField` | 与文档版本联合校验 |
| `created_at` | `DateTimeField(auto_now_add=True)` | 写入时间 |

Meta 建议：

```text
db_table = knowledge_document_chunks
UNIQUE(document_id, chunk_index)
INDEX(document_id, ingestion_version)
INDEX(embedding_model_id, embedding_profile_hash, document_id)
# 2048 维本阶段不创建 HNSW，使用精确余弦计算
CHECK(chunk_index >= 0)
CHECK(ingestion_version > 0)
CHECK(embedding_dimensions = 2048)
```

设计说明：

- 不重复保存 `knowledge_base_id`，检索时通过 document JOIN 限定知识库；
- `document → chunks` 使用 CASCADE，删除文档时删除全部向量；
- `embedding_model → LLMModel` 使用 PROTECT，防止仍被向量使用的模型配置被直接删除；
- provider/model key/profile hash 是向量空间身份快照，API Key 轮换不应改变 profile hash；
- `embedding_profile_hash` 由 provider ID、model ID/key、dimensions、Base URL 和非敏感参数计算，不包含 API Key、ciphertext 或密钥版本；
- 第一阶段没有 chunk 表，第二阶段迁移无需迁移任何历史向量。

### 4.3 文档表新增字段

第一阶段已有 `status`、`error_message`、`ingestion_version`，本阶段直接启用，不重复增加错误字段。

通过新迁移补充：

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `ingestion_task_id` | `CharField(max_length=100), blank=True, default=''` | 当前/最近 Celery 任务 ID，便于诊断 |
| `processing_started_at` | `DateTimeField(null=True, blank=True)` | Worker 认领时间 |
| `processed_at` | `DateTimeField(null=True, blank=True)` | 最近成功或失败完成时间 |
| `embedding_profile_hash` | `CharField(max_length=64), blank=True, default=''` | 当前 ready 向量使用的模型配置指纹；失败时保留诊断值 |

状态更新规则：

| 操作 | status | error_message | 其他字段 |
| --- | --- | --- | --- |
| 上传完成 | `uploaded` | 空 | version=1，清空任务时间 |
| Worker 认领 | `processing` | 空 | 写 task_id、processing_started_at |
| 向量化成功 | `ready` | 空 | 写 processed_at 和 profile hash |
| 向量化失败 | `failed` | 安全错误摘要 | 写 processed_at，保留 task_id 供诊断 |
| 点击重试 | `uploaded` | **立即清空** | version + 1，清空旧 task_id/时间/profile |
| 删除 | `deleting` | 按删除结果填写 | 后续版本检查防止旧任务回写 |

`error_message` 最长保存 1000 个 Unicode 字符，超出截断；不得包含 API Key、完整原文、物理路径、SQL、完整响应体或堆栈。

### 4.4 迁移顺序

```text
system_setting：增加 Embedding dimensions 配置
→ knowledge：CREATE EXTENSION IF NOT EXISTS vector
→ knowledge：文档表新增任务字段
→ knowledge：创建 knowledge_document_chunks
→ knowledge：创建唯一约束和普通 B-tree 索引，不创建 HNSW
```

要求：

- 扩展创建必须进入 Django 迁移，不能只依赖 PostgreSQL 数据目录首次初始化脚本；
- 数据库账号必须具有创建扩展权限，失败时给出明确部署错误；
- chunk 外键依赖第一阶段文档表；
- 模型外键依赖 `system_setting` 初始迁移；
- 删除被 chunk 使用的模型/供应商时，将 `ProtectedError` 映射为 409，而不是 500；
- 迁移和索引测试必须使用真实 PostgreSQL/pgvector，不使用 SQLite。

## 5. Embedding 模型配置

### 5.1 复用现有配置

继续使用：

```text
get_effective_model_config(ModelType.EMBEDDING)
```

不新建供应商、API Key 或 Base URL 表。现有实现见 [system_setting/services.py](../backend/system_setting/services.py#L42-L97)。

任务只能使用 `selected_for = embedding` 且 `model_type = embedding` 的当前配置：

- 从当前选择关联到 `LLMModel`，再读取其所属 `LLMProvider`；
- Base URL 和解密后的 API Key 均来自该供应商；
- 不允许任务消息临时指定其他 provider/model；
- 未选择 Embedding、配置被停用或配置不完整时，文档进入 failed，不能回退使用文本模型；
- 这与 Insight 从 ModelProvider 加载全局 Embedding 配置的方式一致。

### 5.2 补充显式维度与身份

建议给 `LLMModel` 增加：

```text
dimensions = PositiveIntegerField(null=True, blank=True)
```

规则：

- `model_type = embedding` 时必须填写且固定为 2048；
- `model_type = text` 时保持为空；
- 创建、更新、选择和运行时加载都进行校验；
- `EffectiveModelConfig` 增加 `model_id`、`provider_id`、`dimensions`；
- 供应商或模型被 chunk 使用时禁止删除。

前端现有大模型配置页签需要：

- 开放 Embedding 模型创建和当前选择；
- Embedding 模型显示固定 2048 维，创建/编辑校验必须为 2048，不提供任意维度切换；
- 显示“修改模型不会自动重建已有向量”的警告；
- API Key 继续 write-only，不在页面回显。

### 5.3 配置快照

一篇文档开始处理时只加载一次配置，并创建固定 Embedder：

```text
provider_id + model_id + model_key + base_url + api_key
+ dimensions + parameters + profile_hash
```

整篇文档的所有批次使用同一快照，避免处理途中切换全局模型导致一篇文档混入两个向量空间。API Key 只存在于 Worker 内存，不写入任务消息、chunk、日志或错误字段。

## 6. 文本分块与 Embedding 客户端

### 6.1 分块参数

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `KNOWLEDGE_CHUNK_SIZE` | 800 | Python Unicode 字符数，不是 token |
| `KNOWLEDGE_CHUNK_OVERLAP` | 100 | 相邻 chunk 重叠字符数 |
| `KNOWLEDGE_EMBEDDING_BATCH_SIZE` | 10 | 每次 Embedding 请求的 chunk 数 |
| `KNOWLEDGE_MAX_CHUNKS_PER_DOCUMENT` | 5000 | 防止超大文档造成内存和费用失控 |

分块算法：

1. 将 CRLF/CR 统一为 LF并 Trim；
2. 空白文本返回 0 chunks，并使文档失败；
3. 以 800 字符为目标窗口；
4. 在窗口后半段优先寻找段落/换行，其次寻找 `。！？；.!?;`；
5. 找不到自然边界才硬切；
6. 下一段从实际结束位置减去 100 开始，并保证始终向前移动；
7. 保存 `chunk_index`，可选保存字符起止位置和 Markdown 标题路径到 `source_meta`。

第一期不是 Markdown AST 解析器，不宣称能完美保留表格、代码块或标题结构。

### 6.2 原始文件读取

- 只通过文档 `storage_key` 和受控存储根目录读取；
- 做根目录 containment 校验，禁止路径逃逸；
- 文件不存在、不可读或 UTF-8 校验失败时进入 `failed`；
- 20 MiB 文件可以在 Worker 中读取为文本，但必须限制 chunk 数并监控 Worker 内存；
- 不在上传请求进程中执行分块或 Embedding。

### 6.3 OpenAI 兼容客户端

建议新增独立 `knowledge/embeddings.py`，基于显式 `httpx` 依赖实现同步客户端：

```text
POST {base_url 去除末尾 /}/embeddings
Authorization: Bearer <api_key>
Content-Type: application/json
{
  "model": "...",
  "input": ["chunk 1", "chunk 2", ...]
}
```

仅当供应商明确支持 dimensions 参数时，才通过非敏感 parameters 添加该字段；不能盲目发送不兼容参数。无论请求是否带 dimensions，都必须校验实际返回维度。

客户端约束：

- 连接超时 10 秒，请求总超时 60 秒；
- 响应体设置上限，成功响应建议最大 32 MiB；
- 网络错误、429、5xx 最多尝试 3 次，指数退避 1s、2s、4s并加入 jitter；
- 400、401、403、404、配置错误和维度错误不自动重试；
- 自动重试只位于 Embedding 客户端这一层，Celery 不再叠加另一层业务自动重试；
- 空输入直接返回空数组，不发 HTTP 请求。

响应必须校验：

1. `data` 数量等于输入 chunk 数；
2. 每个 `index` 唯一且处于合法范围；
3. 按 index 还原顺序，不能假设供应商按顺序返回；
4. 每个向量恰好 2048 维；
5. 所有数值必须有限，拒绝 NaN/Inf；
6. 拒绝全零向量；
7. 任一批次失败，整篇文档不能进入 ready。

## 7. Celery 队列与 Worker 设计

### 7.1 队列隔离

新增独立队列：

```text
knowledge.document.vectorize
→ CELERY_TASK_ROUTES → knowledge queue
→ 专用 celery-knowledge-worker
```

建议专用 Worker 初始配置：

```text
celery -A backend worker
  --queues=knowledge
  --concurrency=2
  --prefetch-multiplier=1
```

现有默认 `celery-worker` 保持处理普通队列，不让长时间 Embedding 任务占满其默认 5 个并发。

并发口径：

- 一个专用 Worker 容器、concurrency=2：最多同时处理 2 篇文档；
- 每个任务内部顺序请求，每批 10 个 chunk；
- 因而单容器最多通常有 2 个并发 Embedding HTTP 请求，而不是 20 个；
- 多容器总文档并发 = 容器数 × 每容器 concurrency；
- 调整时必须同时考虑供应商限流、Worker 内存和数据库写入量。

### 7.2 任务消息

任务只接收：

```json
{
  "document_id": 10,
  "ingestion_version": 1
}
```

建议任务名：

```text
knowledge.document.vectorize
```

建议确定性 task ID：

```text
knowledge.document.vectorize:{document_id}:{ingestion_version}
```

确定性 ID 用于诊断和减少误重复投递，但 **Celery/Redis 不保证全局去重**，最终仍由数据库状态与版本保证幂等。

禁止传入：

- 文件句柄和文件正文；
- Django Model 实例；
- API Key 或完整模型配置；
- chunks 或向量数组；
- 用户提供的物理路径。

### 7.3 Celery 执行参数

建议：

```text
acks_late = True
reject_on_worker_lost = True
prefetch_multiplier = 1
soft_time_limit = 1800 秒
time_limit = 1860 秒
Redis visibility_timeout = 3600 秒
```

要求 visibility timeout 大于任务硬超时。硬 kill 后可能来不及更新 failed，因此必须有第 10 章的超时对账。

Celery result 继续存 Redis DB 1 并保留一天，但前端只读取 PostgreSQL 文档状态，不查询 Celery AsyncResult。

## 8. 向量化任务状态机

### 8.1 原子认领

Worker 首先执行条件更新：

```text
WHERE document_id = ?
  AND ingestion_version = ?
  AND status = uploaded

SET status = processing,
    ingestion_task_id = ?,
    processing_started_at = now(),
    processed_at = NULL,
    error_message = ''
```

只有影响一行才继续处理。以下消息直接安全结束：

- 文档已删除；
- version 已过期；
- 另一个 Worker 已认领；
- 文档已 ready/failed/deleting；
- 当前消息是重复投递。

### 8.2 主流程

```text
原子认领
→ 加载一次 Embedding 配置快照
→ 读取并校验原始文件
→ SplitText
→ 检查 1 <= chunk_count <= 5000
→ 每 10 个 chunk 批量 Embedding
→ 校验所有向量并生成 chunk Model 列表
→ 开启最终数据库事务
→ SELECT FOR UPDATE 锁定文档
→ 再次检查 version = 当前版本且 status = processing
→ 删除该文档旧 chunks
→ bulk_create 新 chunks
→ 更新 ready、processed_at、profile hash
→ 提交事务
```

任一步骤失败都不得进入 ready。

### 8.3 最终事务

最终事务是防止旧任务破坏新数据的最后一道防线：

- 如果版本或状态不匹配，抛出状态变化异常并回滚；
- 删除旧 chunks、插入新 chunks 和更新 ready 必须原子完成；
- 不在事务中调用 Embedding HTTP API；
- 每批数据库插入可使用 100 条一批，但不能把“部分批次成功”视为文档成功；
- 当前设计在内存中积累整篇文档向量，因此必须执行 5000 chunk 上限和 Worker 内存监控。

### 8.4 失败处理

捕获异常后，只允许将同一版本、仍为 processing 的文档更新为 failed：

```text
status = failed
error_message = 安全摘要，最多 1000 字符
processed_at = now()
```

旧任务遇到以下情况不得覆盖新状态：

- 管理员已重试并递增版本；
- 文档正在删除或已删除；
- 新任务已经认领；
- 文档已被其他任务更新。

失败时可能仍存在旧 chunks，但文档不是 ready，后续检索必须过滤，因此不会把旧数据当作本次成功结果。

### 8.5 推荐错误文案

| 场景 | `error_message` 示例 |
| --- | --- |
| 未配置模型 | `向量模型未配置或不可用，请联系管理员检查系统设置。` |
| 文件不可读 | `原始文件不存在或无法读取，请重新上传或联系管理员。` |
| 空白文档 | `文档没有可向量化的文本内容。` |
| chunk 超限 | `文档分块数量超过当前上限，请拆分文件后重试。` |
| 供应商暂时不可用 | `Embedding 服务暂时不可用，已自动重试，请稍后手动重试。` |
| 维度不符 | `Embedding 返回维度与系统配置不一致，请检查向量模型配置。` |
| 向量写库失败 | `向量数据保存失败，请重试；详细原因已记录到服务端日志。` |
| 任务中断 | `向量化任务执行中断，请手动重试。` |
| 投递失败 | `向量化任务投递失败，请重试。` |

前端只展示安全摘要，详细异常由服务端按 document_id/version/task_id 记录，不记录正文和密钥。

### 8.6 与文件删除协作

第二阶段删除接口的路由和权限不变，但删除服务必须使正在执行的任务失效：

```text
事务锁定文档
→ ingestion_version += 1
→ status = deleting
→ 提交状态
→ 删除原文
→ 删除文档数据库记录并级联删除 chunks
```

要求：

- uploaded、processing、ready、failed 都通过同一删除入口处理；
- processing 文档不等待 Worker 返回，先递增 version 并标记 deleting；
- Worker 最终事务同时检查 version 和 processing 状态，因此不能覆盖删除；
- Worker 因原文已删除而失败时，失败回写同样受 version/status 条件限制；
- 删除失败后保留 deleting 和新 version，沿用第一阶段的删除重试与补偿；
- 不能仅凭取消 Celery task ID 判断删除成功，任务可能已经在执行。

## 9. 上传投递与失败重试

### 9.1 上传后自动投递

第一阶段上传服务在数据库事务成功提交后投递：

```text
创建 uploaded 文档
→ transaction.on_commit
→ 投递 document_id + ingestion_version
→ 返回文档真实状态
```

如果 Broker 投递失败：

- 原文和文档记录已经存在，不能假装整个上传失败；
- 将同版本文档标记为 `failed`；
- `error_message = 向量化任务投递失败，请重试。`；
- 上传 API 仍返回 **201**，响应中携带 `failed` 和错误信息；
- 投递辅助函数必须捕获 Broker 异常、按同版本条件更新 failed 并返回结果，不能让 on_commit 异常把已成功的原文上传变成 500；
- 前端显示上传原文成功，但向量化未启动，并直接提供 retry；
- 不应返回一个诱导用户重新上传原文的错误，否则会遇到同库 Hash 409。

### 9.2 重试 API

新增：

```http
POST /api/knowledge-bases/{base_id}/documents/{document_id}/retry/
```

权限：仅超级管理员。

只允许：

```text
当前文档.status = failed
```

其他状态返回 409，包括 uploaded、processing、ready 和 deleting。

成功流程：

```text
事务 SELECT FOR UPDATE 锁定文档
→ 再次确认 failed 及知识库归属
→ ingestion_version += 1
→ status = uploaded
→ error_message = ''
→ 清空旧 task_id、处理时间和 embedding_profile_hash
→ 提交事务
→ transaction.on_commit 投递新 version 任务
→ 返回 202 和更新后的完整文档
```

重试成功后：

- 前端立即将该行更新为 `uploaded`、清空错误；
- 不显示旧错误；
- watch 检测到待处理状态后启动 5 秒完整列表轮询；
- 旧 version 任务即使迟到，也无法认领或写回。

如果 retry 投递失败：

- 文档重新标记为 failed，并保留“任务投递失败，请重试”；
- API 返回 503；
- 前端刷新完整列表后继续显示失败原因和 retry；
- 不递增第二次版本，除非用户再次明确点击 retry。

本阶段没有 ready 文档重新向量化按钮，retry 不能用于 ready。

## 10. 超时任务与恢复对账

Redis AOF 和 Celery ACK 不能替代数据库恢复。新增周期任务：

```text
knowledge.document.recover_stale
每 60 秒执行一次
```

可通过独立 `celery-beat` 服务调度，或将管理命令接入现有调度系统。

处理规则：

| 场景 | 判定 | 恢复动作 |
| --- | --- | --- |
| uploaded 长期未认领 | `updated_at` 距今超过 5 分钟 | 按相同 version 重新投递；数据库认领防止重复执行 |
| processing 疑似僵死 | `processing_started_at` 超过任务硬超时 + 5 分钟 | 标记 failed，写入“任务执行中断，请手动重试” |
| version/status 已变化 | 与扫描时不一致 | 条件更新影响 0 行，跳过 |
| 正常长任务 | 未超过硬超时 + 宽限期 | 不处理 |

选择“僵死 processing → failed 并人工重试”，而不是无限自动重跑，可以避免配置错误或持续供应商故障造成无限费用。后续如需自动恢复次数，可增加独立恢复计数字段并设上限。

对账任务本身必须幂等，启动多个 Beat/调度实例时也只能依靠条件更新和版本认领保证安全。

## 11. 文档列表 API 调整

### 11.1 使用完整集合，不使用单文件状态接口

本阶段明确文档列表为当前知识库的全量集合：

```http
GET /api/knowledge-bases/{base_id}/documents/
```

响应：

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": 10,
        "knowledge_base_id": 1,
        "original_name": "值班规范.md",
        "mime_type": "text/markdown",
        "extension": ".md",
        "size_bytes": 10240,
        "status": "failed",
        "error_message": "Embedding 服务暂时不可用，已自动重试，请稍后手动重试。",
        "processed_at": "2026-11-15T05:00:00Z",
        "created_at": "2026-11-15T04:55:00Z"
      }
    ]
  },
  "message": "OK"
}
```

约束：

- 返回该知识库全部文档，按 `created_at DESC, id DESC` 排序；
- 一次请求更新整个 `documents` 数组；
- 不提供 `GET /documents/{id}/status/`；
- 不为每个文档单独调用 API；
- 知识库列表仍保留服务端分页；
- 文件表格如需分页，本阶段使用前端本地分页，轮询仍更新完整数组；
- 这是当前小数据量阶段的明确取舍。未来文档数很大时，应重新评审游标分页、列表快照或增量同步，不能悄悄改成只刷新当前页。

响应新增 `processed_at`，继续保留 `error_message`。不返回完整向量、物理路径、content hash、API Key 或内部堆栈。

### 11.2 本阶段全部新增/调整接口

| Method | 路径 | 变化 |
| --- | --- | --- |
| GET | `/api/knowledge-bases/{id}/documents/` | 返回全量文件及真实向量化状态 |
| POST | `/api/knowledge-bases/{id}/documents/` | 创建记录后自动投递向量化任务 |
| POST | `/api/knowledge-bases/{id}/documents/{document_id}/retry/` | 新增，failed 文档重试 |

其他第一阶段 CRUD 和删除接口的路由、权限保持不变；删除服务内部必须按第 8.6 节递增版本并使旧 Worker 失效。

## 12. 前端轮询设计

### 12.1 状态与定时器

在 `knowledge-document-panel.vue` 内只维护一个轮询定时器：

```text
pollTimer: number | null
pollInFlight: boolean
pageVisible: boolean
```

待处理状态只包括：

```text
uploaded、processing
```

failed 不轮询，因为需要用户点击 retry；ready 不轮询；deleting 不由本向量化 watch 处理。

### 12.2 一个 watch 统一管理

实现形态应为一个 `watch`，同时观察：

- 当前知识库 ID；
- 是否存在 uploaded/processing 文档；
- 系统设置知识库页签是否激活；
- 浏览器页面是否可见。

伪代码如下，表达设计而不是要求逐字照抄：

```ts
watch(
  () => [
    props.knowledgeBaseId,
    documents.value.some((item) =>
      ['uploaded', 'processing'].includes(item.status),
    ),
    props.active,
    pageVisible.value,
  ] as const,
  ([baseId, hasPending, active, visible], _previous, onCleanup) => {
    if (!baseId || !hasPending || !active || !visible) return;

    const timer = window.setInterval(() => {
      void refreshAllDocuments({ silent: true });
    }, 5000);

    onCleanup(() => window.clearInterval(timer));
  },
  { immediate: true },
);
```

实现时可以封装 `stopPolling()`，但必须避免在 watch 外再次创建第二套 interval。

### 12.3 启动、重启与停止

| 场景 | 行为 |
| --- | --- |
| 初次完整列表含 uploaded/processing | watch 启动 5 秒 interval |
| 新上传文档加入列表 | pending 从 false → true，启动 |
| retry 后 failed → uploaded | 清空错误并启动 |
| 轮询中仍有 pending | watch 依赖布尔值不变，不重复创建 interval |
| 全部 ready/failed | pending → false，清理 interval |
| 切换知识库 | 清理旧 interval，按新列表决定是否启动 |
| 离开知识库页签 | 停止 |
| 浏览器页面隐藏 | 停止；重新可见且仍有 pending 时恢复 |
| 组件卸载 | 通过 watch cleanup 和卸载钩子确保停止 |

页面隐藏事件只负责更新 `pageVisible`，不另建第二个轮询 watch。

### 12.4 防止重叠请求和旧响应覆盖

`refreshAllDocuments()` 必须满足：

1. `pollInFlight = true` 时跳过本次静默轮询，等待下一个 5 秒周期；
2. 静默轮询不显示整表 loading，不清空当前列表；
3. 请求返回后一次性替换完整 documents 数组；
4. 切换知识库时使旧请求失效，可使用 AbortController 或递增 request sequence；
5. 旧知识库的响应不能覆盖新选中的知识库；
6. 手动上传、删除、retry 后与静默轮询并发时，以最新完整列表刷新为准，不能用旧响应把 uploaded 恢复成 failed；
7. 静默轮询失败保留现有列表，下一次周期继续；错误提示需去重或节流，不能每 5 秒弹一次全局消息；
8. 手动刷新、上传和 retry 的失败仍立即提示。

### 12.5 为什么不使用单文件轮询

统一集合轮询符合当前需求：

- 只调用一个既有列表接口；
- 同一请求可同时推进多篇上传文档状态；
- 不需要为每个文档维护 task ID、timer 或 AbortController；
- 新上传和 retry 都只改变列表状态，由同一个 watch 决定是否继续；
- 前端逻辑简单，且不会遗漏其他管理员同时上传的文档。

## 13. 前端错误展示与重试

### 13.1 文件状态

| 状态 | 展示 | 是否显示 retry |
| --- | --- | --- |
| `uploaded` | 等待向量化 | 否 |
| `processing` | 向量化中 | 否 |
| `ready` | 已向量化 | 否 |
| `failed` | 向量化失败 | **是** |
| `deleting` | 删除中；删除失败时显示对应错误 | 否，使用删除重试 |

### 13.2 错误信息

- failed 行在状态旁显示错误图标或“查看原因”；
- 使用 NTooltip、NPopover 或可展开行展示 `error_message`；
- 长错误允许换行，表格列可显示截断摘要；
- 始终按纯文本渲染，不使用 `v-html`；
- 空错误显示“向量化失败，请重试或联系管理员”，不伪造具体原因；
- retry 成功后立即清空该行错误；
- 不在前端展示 task ID、物理路径或供应商完整响应。

### 13.3 retry 交互

- 仅 `status === 'failed'` 时显示；
- 按钮文案“重试”，带 `lucide:rotate-cw` 图标；
- 可用 NPopconfirm 提示“将重新分块并调用 Embedding 服务”；
- 每个文档独立 `retryingId`，请求期间只禁用当前按钮；
- 202 成功后更新该行并刷新完整列表；
- 409 通常表示状态已变化，刷新完整列表并提示；
- 503 表示投递失败，保留错误和 retry；
- retry 请求期间不能重复点击同一文件，但其他文件仍可操作。

## 14. 后端与前端文件变更建议

### 14.1 后端

| 文件 | 新建/修改 | 内容 |
| --- | --- | --- |
| `knowledge/models.py` | 修改 | 文档任务字段、KnowledgeDocumentChunk |
| `knowledge/migrations/0002_*.py` | 新建 | vector 扩展、文档任务字段、chunk 表和索引 |
| `knowledge/chunking.py` | 新建 | Unicode 分块和来源定位 |
| `knowledge/embeddings.py` | 新建 | OpenAI 兼容客户端、重试和响应校验 |
| `knowledge/services/vectorization.py` | 新建 | 认领、主流程、最终事务和失败处理 |
| `knowledge/services/knowledge_documents.py` | 修改 | 上传提交后投递、retry、完整列表 |
| `knowledge/tasks.py` | 新建 | 向量化任务和对账任务 |
| `knowledge/management/commands/recover_knowledge_documents.py` | 新建 | 可手动执行的对账入口 |
| `knowledge/views.py` / `urls.py` | 修改 | retry 路由和文档响应 |
| `knowledge/serializers.py` | 修改 | processed_at 等公开字段 |
| `system_setting/models.py` / `services.py` / `serializers.py` | 修改 | dimensions 和模型身份信息 |
| `system_setting/views.py` | 修改 | 被向量使用模型的删除保护 |
| `backend/settings.py` | 修改 | 队列路由、任务限制、分块和 Embedding 配置 |
| `docker-compose.yml` | 修改 | 专用 Worker、Beat、队列并发和共享原文卷 |
| `requirements.txt` | 修改 | 固定 pgvector Python 包和 httpx 版本 |

### 14.2 前端

| 文件 | 新建/修改 | 内容 |
| --- | --- | --- |
| `api/knowledge/index.ts` | 修改 | processed_at、retry API、全量列表类型 |
| `views/system-setting/knowledge-base.vue` | 修改 | 向文件面板传递页签 active 状态 |
| `views/system-setting/components/knowledge-document-panel.vue` | 修改 | 一个 watch、5 秒全量轮询、错误和 retry |
| `views/system-setting/llm-config.vue` | 修改 | Embedding 模型和维度选择 |
| `views/system-setting/__tests__/knowledge-base.spec.ts` | 修改 | fake timers、完整列表轮询和 retry 测试 |
| `views/system-setting/__tests__/knowledge-documents.spec.ts` | 新建 | 状态、错误、重叠请求和停止条件测试 |

本阶段不重写 AI 对话页、不修改 SSE、不新增知识库顶级菜单。

## 15. 测试设计

### 15.1 分块单元测试

- 中文、英文、emoji 和混合 Unicode；
- CRLF/CR 标准化；
- 空文本和纯空白；
- 自然边界、硬切和重叠；
- 极短边界不会死循环；
- chunk_index 和 source offset 正确；
- 5000 chunk 上限。

### 15.2 Embedding 契约测试

使用本地 fake HTTP 服务，不调用真实供应商：

- 多批次拆分和顺序；
- 空输入不发请求；
- 429、5xx、网络错误重试及 jitter；
- 400/401/403 不重试；
- 超时；
- data 数量错误、重复/越界 index；
- 维度不符、NaN/Inf、全零向量；
- 响应过大；
- 日志和 error_message 不包含 Key、正文和完整响应。

### 15.3 向量表与事务测试

使用真实 PostgreSQL/pgvector：

- vector 扩展和 2048 维列创建成功；
- 普通 B-tree 索引存在，embedding 列上不创建 HNSW；
- 精确余弦距离查询可执行且排序正确；
- 非 2048 维写入失败；
- `(document_id, chunk_index)` 唯一；
- 文档删除级联 chunks；
- 被使用模型删除返回 409；
- 最终事务失败时旧 chunks 不被部分替换；
- 版本或状态变化时 ready 更新失败并回滚。

### 15.4 Celery 任务测试

- uploaded → processing → ready；
- 每个异常阶段 → failed + 安全 error_message；
- 重复消息不重复调用 Embedding；
- 旧 version 消息不能认领；
- 旧任务不能覆盖 retry 后的新任务；
- 删除中的文档不能被认领；
- 最终提交后才显示 ready；
- 上传投递失败返回 201 + failed + retry 可用；
- processing 超时对账为 failed；
- uploaded 超时重新投递且不会并发重复处理；
- Redis 结果过期不影响文档状态和错误显示。

### 15.5 retry API 测试

- 仅超级管理员；
- 仅 failed 返回 202；
- uploaded/processing/ready/deleting 返回 409；
- 跨知识库文档返回 404；
- version 精确加 1；
- error_message、旧 task_id 和时间被清空；
- on_commit 后才投递新 version；
- 重复点击不会生成两个有效 version；
- 投递失败返回 503 并保留可读错误。

### 15.6 前端轮询测试

使用 `vi.useFakeTimers()` 和 mocked API：

1. 有 uploaded/processing 时启动一个 interval；
2. 前进 5000ms，完整列表接口调用一次；
3. 前进 10000ms，调用两次，不调用任何单文档状态接口；
4. 多篇 pending 文档仍只有一个列表请求；
5. 全部 ready/failed 后停止；
6. 新上传和 retry 后重新启动；
7. 切换知识库时清理旧 timer，旧响应不覆盖新列表；
8. 慢请求期间跳过重叠轮询；
9. 页签隐藏、浏览器隐藏和组件卸载后停止；
10. 静默失败不每 5 秒重复弹错；
11. 本地表格分页/滚动和当前选择不被静默刷新重置。

### 15.7 前端错误与 retry 测试

- failed 显示错误纯文本和 retry；
- uploaded/processing/ready 不显示 retry；
- 长错误可查看且不执行 HTML；
- retry 中只禁用当前文件；
- 202 后错误清空、状态变为 uploaded 并刷新全列表；
- 409 后刷新状态；
- 503 后保留错误和 retry；
- 用户重复点击不会发送并发 retry。

## 16. 部署与运行参数

建议集中配置：

```text
KNOWLEDGE_EMBEDDING_DIMENSIONS=2048
KNOWLEDGE_CHUNK_SIZE=800
KNOWLEDGE_CHUNK_OVERLAP=100
KNOWLEDGE_EMBEDDING_BATCH_SIZE=10
KNOWLEDGE_MAX_CHUNKS_PER_DOCUMENT=5000
KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS=60
KNOWLEDGE_EMBEDDING_MAX_ATTEMPTS=3
KNOWLEDGE_TASK_SOFT_TIME_LIMIT=1800
KNOWLEDGE_TASK_TIME_LIMIT=1860
KNOWLEDGE_PROCESSING_STALE_SECONDS=2160
CELERY_KNOWLEDGE_WORKER_CONCURRENCY=2
```

注意：

- 维度在 Model/迁移中固定，以上环境值只用于一致性检查；
- 前端 5 秒是产品交互常量，不需要做成后端环境变量；
- Redis broker 的 visibility timeout 必须大于任务硬超时；
- 专用 Worker 与 backend 使用相同代码镜像、数据库、Redis 和原文卷；
- 模型配置未完成时任务应失败并给出可读原因，而不是无限等待；
- 真实供应商连通性和 2048 维验证是上线前置条件；
- 监控文档状态数量、任务耗时、失败原因、Embedding 请求次数、Worker 内存和队列长度。

## 17. 推荐实施顺序

1. 确认真实 Embedding 模型、Base URL 和 2048 维能力，完成维度预检；
2. 增加 Embedding dimensions 配置和模型身份快照；
3. 创建文档任务字段、chunk 表、pgvector 扩展和索引迁移；
4. 实现并测试分块器与 Embedding 客户端；
5. 实现向量化 Service、最终事务和失败状态；
6. 配置 knowledge 队列、专用 Worker、上传后投递和超时对账；
7. 实现 failed retry API 及版本递增测试；
8. 复用第一阶段全量文档集合响应，补充向量化状态和完成时间字段；
9. 实现前端一个 watch、5 秒全量轮询、错误展示和 retry；
10. 执行后端、前端、迁移、Worker 故障和端到端验收。

每一步先评审代码与测试，不提前接入 Agent 检索。

## 18. 最终验收清单

- [ ] 上传后自动创建向量化任务，上传请求本身不执行 Embedding；
- [ ] 文档按 uploaded → processing → ready/failed 真实流转；
- [ ] 向量保存到 `knowledge_document_chunks`，维度、模型和版本可追溯；
- [ ] chunks 替换和 ready 更新在同一事务；
- [ ] 重复消息、旧版本任务和删除竞态不会产生错误向量；
- [ ] 失败原因写入文档 `error_message`，且不泄漏密钥和内部路径；
- [ ] 前端能查看失败原因，只有 failed 文件显示 retry；
- [ ] retry 递增版本、清空错误并重新进入 uploaded；
- [ ] 当前知识库有 uploaded/processing 时，一个 watch 每 5 秒请求一次完整文件列表；
- [ ] 不存在单文件状态接口或每文件独立 timer；
- [ ] 无 pending、切换知识库、页签隐藏、页面隐藏和卸载时停止轮询；
- [ ] 慢请求不会重叠，旧响应不会覆盖新知识库或新任务状态；
- [ ] 专用 Worker 并发、Embedding 批次和超时限制生效；
- [ ] 僵死 processing 能转为可重试 failed；
- [ ] PostgreSQL/pgvector、Celery、retry 和前端 fake timer 测试通过；
- [ ] 本阶段没有伪造检索、混合检索或 ready 文档全量重建能力。
