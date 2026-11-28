# HomeOps 知识库与 RAG 实施方案（对照 Insight）

- 文档状态：代码对照与实施设计，HomeOps 知识库业务尚未实施
- 更新日期：2026-11-15
- 分析范围：HomeOps 与同级目录 Insight 仓库的实际源码
- 第一阶段实施设计：[知识库与文件上传管理](./knowledge-base-phase-1.md)
- 第二阶段实施设计：[向量化、Celery 异步任务与前端轮询](./knowledge-base-phase-2.md)
- 本文目标：说明 Insight 的当前实现、列清知识库相关表结构，并给出 HomeOps 的分阶段落地方案
- 重要边界：第 2～3 章是 Insight 代码事实；第 4 章是 HomeOps 当前代码事实；第 5 章以后均为待评审、待实施的设计，不表示相关表或功能已经存在

## 1. 结论

Insight 在代码层面已经形成以下 RAG 闭环：

```text
Markdown/TXT 上传
→ 原始文件落盘、文档记录入库
→ 内存队列异步处理
→ 文本分块、批量 Embedding
→ PostgreSQL/pgvector 保存分块和向量
→ ADK 列出知识库并执行向量检索
→ 返回答案、来源和工具调用记录
```

HomeOps 当前没有知识库、文档、分块、向量检索等业务模型，但已经具备：

- PostgreSQL 17 + pgvector；
- Celery + Redis Worker；
- 全局文本/Embedding 模型配置与 API Key 加密；
- Google ADK Agent、SSE 工具事件和聊天消息持久化；
- JWT 认证、超级管理员权限和 Vue 管理前端。

因此推荐新增独立的 `knowledge` Django app，复用上述基础设施，不照搬 Insight 的 Go 分层和内存队列。

## 2. Insight 当前实现概览

### 2.1 核心调用链

```text
Gin /v1/knowledge-bases
→ Handler / Service / Repository
→ LocalStorage + knowledge_documents
→ memory.Broker + WorkerPool
→ vectorize.DocumentService
→ SplitText + OpenAI-compatible Embeddings API
→ knowledge_document_chunks
→ retrieval.Service
→ ADK list_knowledge_bases / knowledge_search
→ SSE tool_call / tool_response
```

启动装配见 [Insight backend/main.go](../../insight/backend/main.go#L75-L120)。知识库管理路由见 [Insight router.go](../../insight/backend/internal/routers/router.go#L97-L109)。

### 2.2 当前算法与参数

| 项目 | 当前实现 |
| --- | --- |
| 文件类型 | 仅 `.md`、`.txt` |
| 文件大小 | 单文件最大 20 MiB |
| 原文校验 | 非空、UTF-8、拒绝 NUL 字节 |
| 文件存储 | 本地 `./data/knowledge`，服务端生成 UUID 文件名 |
| 去重 | 同一知识库内按原始字节 SHA-256 唯一 |
| 分块 | 800 个 Unicode rune，重叠 100 rune |
| 分块边界 | 优先换行，其次句末标点，否则硬切 |
| Embedding | OpenAI 兼容 `POST {baseURL}/embeddings` |
| Embedding 批次 | 每批 10 个 chunk |
| 向量维度 | 固定 2048 维 |
| 检索 | pgvector `<=>` 余弦距离升序 |
| topK | 默认 5，范围 1～10 |
| 查询长度 | 最长 1000 个字符 |
| score | `1 - cosine_distance` |
| 队列 | 内存 Channel，容量 64，Worker 2 |

主要依据：

- [Insight knowledge_document_service.go](../../insight/backend/internal/service/knowledge_document_service.go#L92-L180)
- [Insight chunk.go](../../insight/backend/internal/knowledge/vectorize/chunk.go#L11-L76)
- [Insight vectorize/service.go](../../insight/backend/internal/knowledge/vectorize/service.go#L15-L145)
- [Insight embedder_http.go](../../insight/backend/internal/knowledge/vectorize/embedder_http.go#L18-L171)
- [Insight retrieval/service.go](../../insight/backend/internal/knowledge/retrieval/service.go#L115-L203)
- [Insight knowledge_retrieval_repo.go](../../insight/backend/internal/repository/knowledge_retrieval_repo.go#L30-L104)

### 2.3 值得保留的设计

1. 任务只传知识库 ID、文档 ID 和 `ingestion_version`，不传原文和向量。
2. 只有匹配版本的 `uploaded` 文档才能被原子认领为 `processing`。
3. 删除旧 chunks、插入新 chunks、更新 `ready` 位于同一事务。
4. 旧任务不能覆盖新版本或已删除文档的状态。
5. 检索同时限定知识库、`ready`、当前摄取版本和 Embedding 模型。
6. Retrieval Service 与 ADK Tool 分离，Tool 只做参数和结果适配。
7. Agent 将知识库内容视为不可信资料，无结果时不得编造。

事务和状态认领依据：[Insight knowledge_vector_repo.go](../../insight/backend/internal/repository/knowledge_vector_repo.go#L15-L118)。

## 3. Insight 知识库相关表清单

### 3.1 总览

从当前代码模型看，知识库核心表有三张，另有三类辅助表：

| 表名 | 分类 | 作用 | 是否直接保存向量 |
| --- | --- | --- | --- |
| `knowledge_bases` | 核心 | 知识库元数据 | 否 |
| `knowledge_documents` | 核心 | 上传文件的元数据、处理状态和版本 | 否 |
| `knowledge_document_chunks` | 核心 | 文件分块原文、向量和模型/版本信息 | **是** |
| `model_providers` | 辅助 | 文本模型、Embedding 模型及全局选择配置 | 否 |
| `ai_sessions` | 辅助 | 用户 AI 会话 | 否 |
| `ai_messages` | 辅助 | 对话正文及知识库工具调用 JSON | 否 |

关系如下：

```text
knowledge_bases
    1
    │  knowledge_documents.knowledge_base_id
    │  ON DELETE RESTRICT
    N
knowledge_documents
    1
    │  knowledge_document_chunks.document_id
    │  ON DELETE CASCADE
    N
knowledge_document_chunks

model_providers
    └── 独立提供当前 Embedding 模型配置，不与三张核心表建立外键

ai_sessions
    1
    │  ai_messages.session_id
    N
ai_messages
    └── tool_calls JSON 中保存知识库工具参数和结果；不是到 chunk 的数据库外键
```

> 此处“存在”指当前源码已经定义并纳入迁移模型清单，不等同于本文已连接任一运行数据库核实其实际数据。运行库核验方法见第 3.7 节。

### 3.2 `knowledge_bases`：知识库表

模型定义：[Insight knowledge_base.go](../../insight/backend/internal/model/knowledge_base.go#L5-L35)。

| 字段 | 类型/约束 | 说明 | 管理 API 是否返回 |
| --- | --- | --- | --- |
| `id` | `uint64`，自增主键 | 知识库 ID，Agent 检索时使用 | 是 |
| `name` | `varchar(50)`，非空，唯一 | 知识库名称 | 是 |
| `description` | `varchar(300)`，非空 | 内容范围描述，是 Agent 选库的重要依据 | 是 |
| `created_by` | `uint64`，非空 | 创建人 ID | 否 |
| `created_at` | 时间戳，非空 | 创建时间 | 是 |
| `updated_at` | 时间戳，非空 | 更新时间 | 是 |

关键约束：

- 唯一索引：`uk_knowledge_bases_name`。
- 当前没有 `enabled`、所有者 ACL、Embedding 模型绑定等字段。
- 非空知识库不能被直接删除，由文档表外键 `ON DELETE RESTRICT` 保证。

### 3.3 `knowledge_documents`：知识库文件表

模型定义：[Insight knowledge_document.go](../../insight/backend/internal/model/knowledge_document.go#L11-L82)。

| 字段 | 类型/约束 | 说明 | 管理 API 是否返回 |
| --- | --- | --- | --- |
| `id` | `uint64`，自增主键 | 文档 ID，异步任务只传该 ID 和版本 | 是 |
| `knowledge_base_id` | `uint64`，非空，外键 | 所属知识库 | 是 |
| `original_name` | `varchar(255)`，非空 | 用户上传时的原始文件名 | 是 |
| `storage_path` | `text`，非空 | 服务器上的实际存储路径 | **否** |
| `mime_type` | `varchar(64)`，非空 | `text/markdown` 或 `text/plain` | 是 |
| `extension` | `varchar(8)`，非空 | `.md` 或 `.txt` | 是 |
| `size_bytes` | 整数，`> 0` | 原始文件字节数 | 是 |
| `content_hash` | `char(64)`，非空 | 原始内容的 SHA-256 | **否** |
| `status` | `varchar(16)`，默认 `uploaded` | 文档处理状态 | 是 |
| `error_message` | `text`，默认空字符串 | 最近一次处理失败信息 | 是 |
| `ingestion_version` | 正整数，默认 1 | 防止旧任务覆盖新结果 | 否 |
| `created_by` | `uint64`，非空 | 上传人 ID | 否 |
| `created_at` | 时间戳，非空 | 上传时间 | 是 |
| `updated_at` | 时间戳，非空 | 最近状态更新时间 | 否 |

状态取值：

| 状态 | 含义 |
| --- | --- |
| `uploaded` | 原文和记录已保存，等待 Worker 认领 |
| `processing` | 正在读取、分块、Embedding 或写入向量 |
| `ready` | 全部分块和向量已事务提交，可以参与检索 |
| `failed` | 处理失败，保存错误信息；当前没有重试 API |

关键约束：

- 唯一索引：`uk_knowledge_documents_base_hash(knowledge_base_id, content_hash)`，实现同库内容去重。
- 列表索引：`idx_knowledge_documents_base_created(knowledge_base_id, created_at DESC)`。
- `knowledge_base_id → knowledge_bases.id ON DELETE RESTRICT`。
- 状态 CHECK 仅允许 `uploaded/processing/ready/failed`。
- 当前没有 `deleting`、Celery/队列任务 ID、处理开始时间或重试次数字段。

### 3.4 `knowledge_document_chunks`：文件分块与向量表

模型定义：[Insight knowledge_document_chunk.go](../../insight/backend/internal/model/knowledge_document_chunk.go#L13-L58)。

| 字段 | 类型/约束 | 说明 | 管理 API 是否返回 |
| --- | --- | --- | --- |
| `id` | `uint64`，自增主键 | chunk ID，检索结果用于定位 | 检索工具返回 |
| `document_id` | `uint64`，非空，外键 | 所属文件 | 检索工具返回 |
| `chunk_index` | 整数，`>= 0` | 分块在文件中的顺序 | 检索工具返回 |
| `content` | `text`，非空 | 分块原文 | 检索工具返回 |
| `embedding` | `vector(2048)`，非空 | pgvector 向量 | **否** |
| `embedding_model` | `varchar(128)`，非空 | 生成该向量的模型名 | 不作为独立字段返回 |
| `ingestion_version` | 正整数 | 与文档当前版本匹配才可检索 | 否 |
| `created_at` | 时间戳，非空 | 分块写入时间 | 否 |

关键约束：

- 唯一索引：`uk_knowledge_chunks_document_index(document_id, chunk_index)`。
- `document_id → knowledge_documents.id ON DELETE CASCADE`。
- 删除文档时，分块和向量由数据库级联删除。
- 当前没有 `knowledge_base_id`，检索时通过 JOIN 文档表限定知识库。
- 当前没有标题、页码、字符偏移、token 数等来源元数据。
- 当前只保存模型名，没有 provider ID、模型配置版本或配置指纹。

向量索引现状：

- 代码采用的 HNSW 维度上限为 2000。
- 当前固定 `vector(2048)`，所以跳过 HNSW，保留精确余弦检索能力。
- 数据量增大后可能出现顺序扫描性能问题。

依据：[Insight knowledge_document_chunk.go](../../insight/backend/internal/model/knowledge_document_chunk.go#L61-L126)。

### 3.5 `model_providers`：模型配置辅助表

模型定义：[Insight model_provider.go](../../insight/backend/internal/model/model_provider.go#L19-L83)。

| 字段 | 作用 |
| --- | --- |
| `id` | 供应商配置 ID |
| `base_url` | OpenAI 兼容 API 地址 |
| `api_key` | API Key，属于敏感配置 |
| `models` | JSONB 模型数组，每项可包含 `name/type/dimensions` |
| `selected_model` | 当前全局文本模型 |
| `selected_embedding_model` | 当前全局 Embedding 模型 |
| `created_at` / `updated_at` | 配置时间戳 |

该表不与知识库三张核心表建立外键。向量化和查询时都会加载当前选中的 Embedding 配置。

### 3.6 `ai_sessions` / `ai_messages`：工具调用辅助表

模型定义：[Insight assistant.go](../../insight/backend/internal/model/assistant.go#L13-L49)。

`ai_sessions` 主要字段：

- `id`：UUID 主键；
- `user_id`：会话所属用户；
- `title`；
- `created_at` / `updated_at`。

`ai_messages` 主要字段：

| 字段 | 作用 |
| --- | --- |
| `id` | 消息 ID |
| `session_id` | 所属 AI 会话 |
| `role` | `user` 或 `assistant` |
| `content` | 消息正文 |
| `thinking` | 思考内容 |
| `tool_calls` | JSONB，保存工具名称、参数、结果和状态 |
| `created_at` | 消息时间 |

知识库检索结果可随 `tool_calls` 持久化，但当前没有独立的 `citations` 表或字段，也没有从聊天消息到 chunk 的数据库外键。

### 3.7 如何核验运行数据库中的表

如果需要确认某个 Insight 运行环境是否已经实际建表，可执行只读 SQL：

```sql
SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'knowledge_bases',
    'knowledge_documents',
    'knowledge_document_chunks',
    'model_providers',
    'ai_sessions',
    'ai_messages'
  )
ORDER BY tablename;
```

查看三张核心表的字段、空值约束和默认值：

```sql
SELECT
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'knowledge_bases',
    'knowledge_documents',
    'knowledge_document_chunks'
  )
ORDER BY table_name, ordinal_position;
```

## 4. HomeOps 当前已有相关表与缺口

### 4.1 当前已有辅助表

HomeOps 当前没有 `knowledge_bases`、`knowledge_documents`、`knowledge_document_chunks`，但有以下可复用表：

| 当前表名 | 对应模型 | 可复用能力 |
| --- | --- | --- |
| `system_setting_llmprovider` | `LLMProvider` | 供应商、Base URL、加密 API Key、启用状态 |
| `system_setting_llmmodel` | `LLMModel` | 文本/Embedding 模型目录和全局选择 |
| `ai_assistant_chatsession` | `ChatSession` | 用户会话归属 |
| `ai_assistant_chatmessage` | `ChatMessage` | 正文、thinking、工具调用 JSON 持久化 |

依据：

- [HomeOps system_setting/0001_initial.py](../backend/system_setting/migrations/0001_initial.py#L17-L61)
- [HomeOps ai_assistant/0001_initial.py](../backend/ai_assistant/migrations/0001_initial.py#L17-L45)
- [HomeOps system_setting/models.py](../backend/system_setting/models.py#L8-L117)
- [HomeOps ai_assistant/models.py](../backend/ai_assistant/models.py#L8-L36)

其中 `system_setting_llmmodel` 已支持 `model_type = embedding` 和 `selected_for = embedding`，但当前没有专门的向量维度字段；Embedding 管理页面也尚未开放。

### 4.2 当前缺失

- 三张知识库核心业务表及迁移；
- pgvector Python 依赖、`VectorField`、向量索引和相似度查询；
- 原文存储、上传校验、SHA-256 去重和文本分块；
- OpenAI 兼容 Embedding 客户端；
- Celery 知识库业务任务、状态认领、失败重试和恢复；
- ADK 知识库列表与检索工具；
- 知识库管理前端、状态轮询和重建入口；
- pgvector、任务幂等、权限和端到端 RAG 测试。

## 5. HomeOps 拟建表设计

> 本章全部为建议，尚未在 HomeOps 创建。建议通过 Django `db_table` 显式使用以下表名，避免依赖默认命名。

### 5.1 总览

| 拟建表 | Django Model | 作用 |
| --- | --- | --- |
| `knowledge_bases` | `KnowledgeBase` | 知识库元数据 |
| `knowledge_documents` | `KnowledgeDocument` | 文件、状态、任务和摄取版本 |
| `knowledge_document_chunks` | `KnowledgeDocumentChunk` | 分块原文、来源元数据和向量 |

第一期不建议额外建立任务历史表：当前处理状态持久化在文档表，Celery/Redis 结果仅用于执行观测，不能作为长期业务状态。若未来需要完整任务审计，再增加 `knowledge_ingestion_jobs`。

### 5.2 `knowledge_bases` 拟建字段

| 字段 | 建议类型/约束 | 说明 |
| --- | --- | --- |
| `id` | `BigAutoField` | 主键 |
| `name` | `CharField(50)`，唯一 | 知识库名称 |
| `description` | `CharField(300)`，必填 | Agent 选库依据 |
| `created_by` | 用户外键，`SET_NULL`，可空 | 创建人 |
| `created_at` | `DateTimeField(auto_now_add=True)` | 创建时间 |
| `updated_at` | `DateTimeField(auto_now=True)` | 更新时间 |

第一期不虚构 `enabled` 字段；如后续需要停用知识库，再单独增加状态及检索过滤。

### 5.3 `knowledge_documents` 拟建字段

| 字段 | 建议类型/约束 | 说明 |
| --- | --- | --- |
| `id` | `BigAutoField` | 主键 |
| `knowledge_base` | 外键，`RESTRICT` | 所属知识库 |
| `original_name` | `CharField(255)` | 原始文件名 |
| `storage_key` | `TextField` | 相对存储键，不直接暴露绝对路径 |
| `mime_type` | `CharField(64)` | 文件类型 |
| `extension` | `CharField(8)` | `.md` / `.txt` |
| `size_bytes` | `BigIntegerField`，`> 0` | 文件大小 |
| `content_hash` | `CharField(64)` | SHA-256 |
| `status` | `CharField(16)` | `uploaded/processing/ready/failed/deleting` |
| `error_message` | `TextField`，默认空 | 经过清理和截断的错误摘要 |
| `ingestion_version` | 正整数，默认 1 | 摄取幂等版本 |
| `ingestion_task_id` | 字符串，可空 | 当前 Celery 任务 ID，便于诊断 |
| `processing_started_at` | 时间戳，可空 | 超时任务回收依据 |
| `processed_at` | 时间戳，可空 | 最近完成时间 |
| `created_by` | 用户外键，`SET_NULL`，可空 | 上传人 |
| `created_at` / `updated_at` | 时间戳 | 上传和状态更新时间 |

建议约束和索引：

- `UNIQUE(knowledge_base_id, content_hash)`；
- `INDEX(knowledge_base_id, created_at DESC)`；
- `INDEX(status, updated_at)`，供对账恢复扫描；
- `ingestion_version > 0`；
- `size_bytes > 0`。

### 5.4 `knowledge_document_chunks` 拟建字段

| 字段 | 建议类型/约束 | 说明 |
| --- | --- | --- |
| `id` | `BigAutoField` | chunk ID |
| `document` | 文档外键，`CASCADE` | 所属文件 |
| `chunk_index` | 非负整数 | 分块顺序 |
| `content` | `TextField` | 分块原文 |
| `source_meta` | `JSONField`，默认对象 | 标题路径、字符偏移等可选来源信息 |
| `embedding` | `VectorField(dimensions=2048)` | pgvector 向量，与 Insight 及当前供应商模型一致 |
| `embedding_provider_id` | 整数 | 供应商身份，避免同名模型混用 |
| `embedding_model_key` | `CharField(160)` | 模型标识 |
| `embedding_dimensions` | 正整数 | 写入时维度快照 |
| `embedding_profile_hash` | 字符串，可选 | 非敏感模型配置指纹 |
| `ingestion_version` | 正整数 | 与文档版本联合过滤 |
| `created_at` | 时间戳 | 写入时间 |

建议约束和索引：

- `UNIQUE(document_id, chunk_index)`；
- `INDEX(document_id, ingestion_version)`；
- `INDEX(embedding_model_id, embedding_profile_hash, document_id)`；
- 已确定使用 2048 维，本阶段不创建普通 HNSW，保留精确余弦检索并监控；后续如确有需要再单独评估 `halfvec`，不能直接截断向量。

### 5.5 与现有辅助表的关系

- Embedding 只使用 `selected_for = embedding` 的当前 `system_setting_llmmodel`，并读取其所属 `system_setting_llmprovider` 的 Base URL 和解密 API Key，与 Insight 的配置来源一致；不复制 API Key 到知识库表或 Celery 消息。
- 知识库工具调用继续写入 `ai_assistant_chatmessage.tool_calls`。
- 若后续需要正式来源卡片和历史引用审计，再给聊天消息增加独立 `citations` JSON 或关系表。
- 文档重新向量化或删除后，历史引用保留策略必须单独定义，不能依赖 ADK Session 代替业务审计。

## 6. HomeOps 业务设计

### 6.1 模块边界

建议新增：

```text
backend/knowledge/
├── models.py
├── storage.py
├── chunking.py
├── embeddings.py
├── services/
│   ├── ingestion.py
│   └── retrieval.py
├── tasks.py
├── serializers.py
├── views.py
├── urls.py
├── migrations/
└── tests/
```

职责划分：

- `knowledge`：知识库、文件、向量、任务和检索；
- `system_setting`：供应商、模型和密钥；
- `ai_assistant`：Agent 编排、SSE 和聊天消息；
- 前端：知识库管理、Embedding 选择和工具过程展示。

### 6.2 上传与向量化

```text
DRF 上传 API
→ 流式校验和保存原文
→ 创建 uploaded 文档
→ transaction.on_commit 投递 Celery
→ 原子认领 uploaded → processing
→ 读取原文、分块、分批 Embedding
→ 锁定文档并复核版本
→ 事务替换 chunks、更新 ready
```

关键规则：

1. 上传接口只确认原文和记录创建，返回文档 ID 及 `uploaded` 状态，不代表向量化完成。
2. Celery 消息只包含 `document_id + ingestion_version`。
3. 使用独立 `knowledge` 队列，建议专用 Worker 初始并发为 2。
4. 网络错误、429、5xx 使用有限指数退避；配置和维度错误不自动重试。
5. 自动重试只保留一层，避免 Embedding 客户端和 Celery 双重放大请求。
6. 重试/重建递增 `ingestion_version`，旧任务不能覆盖新结果。
7. 增加超时 `processing` 和未投递 `uploaded` 的对账恢复。
8. 删除通过 `deleting` 和补偿清理处理文件系统与数据库的非事务边界。

### 6.3 检索与 Agent

建议沿用两个只读工具：

```text
list_knowledge_bases()
knowledge_search(knowledge_base_id, query, top_k=5)
```

检索必须同时过滤：

- 指定知识库；
- 当前用户可访问范围；
- 文档 `status = ready`；
- chunk 版本等于文档当前 `ingestion_version`；
- provider、model、dimensions 与查询模型兼容；
- 余弦距离升序并限制 topK。

Agent 根据知识库名称和描述自主选库，第一期不增加前端知识库选择器。检索无结果返回空数组；知识库原文属于不可信资料，不能覆盖 Agent 指令。

权限建议：

- 管理 API：复用 `IsSuperuser`；
- Agent 检索：若一期沿用 Insight，可定义为所有登录用户可读全部 ready 知识库；
- 即使一期全员可读，也要把真实 `request.user` 绑定到 Retrieval Service；
- 若文档存在密级差异，对象级 ACL 是上线阻断项，不能只做菜单隐藏。

### 6.4 管理 API 建议

```text
GET/POST            /api/knowledge-bases/
GET/PATCH/DELETE    /api/knowledge-bases/{id}/
GET/POST            /api/knowledge-bases/{id}/documents/
DELETE              /api/knowledge-bases/{id}/documents/{document_id}/
POST                /api/knowledge-bases/{id}/documents/{document_id}/retry/
POST                /api/knowledge-bases/{id}/reindex/
```

当前阶段按知识库返回全量文档列表，供前端一次请求刷新所有文件状态；文件表格可使用前端本地分页。知识库列表仍使用服务端分页，chunk 不提供无限制通用列表 API。物理路径、内容 Hash、完整向量和 Embedding 密钥不能出现在管理响应中。

### 6.5 前端建议

- 在现有 `/system-setting` 页面内增加“知识库管理”页签，新增 `frontend/web/src/api/knowledge/` 和系统设置子组件，不新增顶级菜单；
- 复用 Naive UI、`requestClient.upload`、`NDataTable/NModal/NForm`；
- 管理路由使用 `authority: ['super']`；
- 使用一个 `watch` 管理轮询：存在 `uploaded/processing` 时每 5 秒请求当前知识库完整文件列表，完成、切换知识库或页面隐藏后停止；
- 展示 `error_message` 中的安全失败原因，仅为 failed 文件提供重试；整库重建入口留到后续生产加固阶段；
- 扩展现有模型配置页，开放 Embedding 创建和选择，固定展示并校验 2048 维；
- 为 `list_knowledge_bases` / `knowledge_search` 增加中文工具名称和图标；
- Nginx 上传限制应略大于 20 MiB，后端仍执行真实文件大小校验；
- 正式来源卡片可后续通过独立 `citations` 实现，不需要重写现有 SSE 工具事件协议。

## 7. 分阶段实施与验收

| 阶段 | 交付内容 | 验收标准 |
| --- | --- | --- |
| 阶段 1：管理基础 | 新 app、知识库/文档两张表、迁移、知识库 CRUD、上传/列表/删除、系统设置管理页签 | 非管理员不能管理；非法文件和重复文件被拒绝；上传后仅为 `uploaded` |
| 阶段 2：真实向量化 | chunk/vector 表、Embedding 维度配置、Celery 队列、分块、版本幂等、失败重试、5 秒全量状态轮询、僵死任务对账、共享文件卷 | 只有 chunks 事务提交后才 `ready`；重复任务和旧版本任务不会破坏结果；failed 可查看原因并重试 |
| 阶段 3：RAG 闭环 | pgvector 检索、两个 ADK 工具、权限过滤、Agent 提示词、来源返回 | 不串库、不查旧版本；无结果不编造；SSE 与历史工具记录完整 |
| 阶段 4：生产加固 | 对账恢复、批量重建、指标告警、索引与性能验证、结构化来源卡片 | Worker/Redis 重启可恢复；模型切换有明确重建流程；耗时和失败率可观测 |

第一期仅实施 Markdown/TXT + 向量检索。PDF/OCR、混合检索、rerank、复杂 ACL 和对象存储后续迭代。

## 8. 测试清单

1. **表和迁移**：全新数据库可启用 vector 并建表；已有数据库不能只依赖首次初始化 SQL。
2. **pgvector 集成**：余弦排序、topK、跨库隔离、非 ready、旧版本、不同模型和维度过滤。
3. **任务幂等**：重复投递、旧版本任务、处理中删除、重试、Worker 崩溃恢复、事务回滚。
4. **Embedding 契约**：429/5xx、超时、返回数量错误、维度错误、NaN/Inf、Key 不进入日志。
5. **权限**：匿名、普通用户、超级管理员，以及 Agent 直接传其他知识库 ID 的情况。
6. **端到端**：上传 → ready → Agent 检索 → SSE 工具事件 → 历史消息来源回放。
7. **前端**：上传、轮询停止、失败重试、工具名称映射和流中断。

## 9. 开始实施前必须确认的决策

1. **Embedding 来源与维度（已确认）**：使用“模型供应商”中当前选中的 Embedding 模型，与 Insight 一致固定为 2048 维；本阶段采用精确余弦检索，不创建普通 HNSW，后续单独评估 halfvec。
2. **读取权限**：确认一期是否允许所有登录用户读取全部 ready 知识库；存在密级差异时先补 ACL。
3. **原文存储**：开发环境可使用后端与 Worker 共享目录；多副本生产环境需要共享卷或对象存储。
4. **模型切换**：明确切换后旧向量不可混查，并提供单文档和整库重建入口。
5. **文件范围**：第一期只支持 Markdown/TXT，不在上传接口中伪装支持未实现的 PDF/Office 解析。

## 10. 额外安全事项

只读检查在 Insight 独立示例 `test/embedding-demo/main.go` 中发现非空硬编码 Embedding API Key。本文不记录密钥内容。应按已经暴露处理，立即撤销并轮换，后续统一从环境变量或密钥配置注入。

HomeOps 应继续复用现有 API Key 加密和 write-only 机制，不把密钥写入知识库表、Celery 消息、异常文本或日志。
