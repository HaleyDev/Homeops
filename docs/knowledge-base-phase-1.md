# HomeOps 知识库第一阶段：知识库与文件上传管理实施设计

- 文档状态：实施前设计稿，待评审后编码
- 更新日期：2026-11-15
- 对应总体方案：[HomeOps 知识库与 RAG 实施方案](./knowledge-base-design.md)
- 后续阶段：[第二阶段：向量化、Celery 异步任务与前端轮询](./knowledge-base-phase-2.md)
- 本阶段后端：新增独立 `knowledge` Django app，完成知识库 CRUD、原始文件上传、文件列表和删除
- 本阶段前端：在现有“系统设置”页面内增加“知识库管理”页签，不新增顶级菜单
- 本阶段不包含：文本分块、Embedding、向量表、Celery 业务任务、Agent 检索、文件下载和重新向量化

## 1. 目标与边界

### 1.1 本阶段完成定义

管理员可以：

1. 在“系统设置 → 知识库管理”中查看、搜索、新建、编辑和删除知识库；
2. 选择知识库并上传单个 Markdown 或 TXT 文件；
3. 查看该知识库的历史文件、文件大小、上传时间和真实状态；
4. 删除文件，并同时清理原文与数据库记录；
5. 删除空知识库；非空知识库由前后端共同阻止删除；
6. 普通用户和未登录用户不能调用任何知识库管理接口。

上传成功只表示：

```text
原始文件已安全保存 + knowledge_documents 记录已创建 + status = uploaded
```

上传成功**不表示**已经解析、切片、向量化或可检索。本阶段不创建空 Celery 任务，也不把文件状态伪装为 `ready`。

### 1.2 明确不做

| 功能 | 所属阶段 |
| --- | --- |
| `knowledge_document_chunks` / `VectorField` | 后续真实向量化阶段 |
| Celery 投递、处理状态轮询、失败重试 | 后续真实向量化阶段 |
| Embedding 模型选择与调用 | 后续真实向量化阶段 |
| `list_knowledge_bases` / `knowledge_search` | 后续 RAG 阶段 |
| 文件下载、chunk 预览、检索测试 | 后续增强阶段 |
| PDF、DOCX、图片、OCR | 后续解析扩展阶段 |
| 普通用户知识库管理、细粒度共享 ACL | 当前不在范围内 |

## 2. 总体结构

```text
系统设置
├── 大模型配置（现有页面）
└── 知识库管理（本阶段新增页签）
        │
        │ /api/knowledge-bases/**
        ▼
DRF KnowledgeBase / KnowledgeDocument API
        │
        ├── KnowledgeBaseService
        │       └── knowledge_bases
        │
        └── KnowledgeDocumentService
                ├── KnowledgeFileStorage
                │       └── 原始文件：受控本地目录
                └── knowledge_documents

本阶段到此为止，不继续进入分块、Embedding 或向量检索。
```

设计约束：

- `knowledge` 自己拥有知识库和文档模型，不把表塞进 `system_setting` 或 `ai_assistant`；
- `system_setting` 继续负责模型配置，本阶段不修改其模型表；
- `ai_assistant` 本阶段完全不改；
- View 不直接拼接文件路径，不直接读取整个上传文件到内存；
- 文件存储与数据库失败必须有清理或可重试路径；
- 所有成功响应继续符合前端主 `requestClient` 的 `{code: 0, data, message}` 约定。

## 3. 后端 app 与文件结构

### 3.1 新增文件

```text
backend/knowledge/
├── __init__.py
├── apps.py
├── admin.py
├── models.py
├── serializers.py
├── pagination.py
├── storage.py
├── views.py
├── urls.py
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py
├── services/
│   ├── __init__.py
│   ├── knowledge_bases.py
│   └── knowledge_documents.py
└── tests/
    ├── __init__.py
    ├── test_knowledge_base_api.py
    ├── test_knowledge_document_api.py
    ├── test_models.py
    └── test_storage.py
```

说明：

- `services/knowledge_bases.py`：名称校验后的业务操作、非空删除保护和文档计数；
- `services/knowledge_documents.py`：上传、列表、删除、事务与异常映射；
- `storage.py`：临时文件、流式 Hash/校验、UUID 路径、原子 rename、删除和根目录约束；
- `admin.py`：只提供 Django Admin 诊断入口，不代替前端管理页面；
- `migrations/0001_initial.py`：只创建本阶段两张表，不需要创建 vector 扩展。

### 3.2 修改的现有后端文件

| 文件 | 修改内容 |
| --- | --- |
| [settings.py](../backend/backend/settings.py) | 注册 `knowledge`；增加上传目录和 20 MiB 大小配置 |
| [urls.py](../backend/backend/urls.py) | 在 `/api/` 下挂载知识库路由 |
| `backend/backend/api.py`（新增） | 放置共享 `ok` / `ApiResponseMixin`，统一成功响应 |
| [system_setting/views.py](../backend/system_setting/views.py) | 改为复用共享响应工具，行为保持不变 |
| [docker-compose.yml](../docker-compose.yml) | 为后端及后续 Worker 配置同一原文目录和环境变量 |

本阶段只使用 Django、DRF 和 Python 标准库，不需要修改 [requirements.txt](../backend/requirements.txt)。

响应工具说明：

- 当前 `ApiResponseMixin` 位于 [system_setting/views.py:20-27](../backend/system_setting/views.py#L20-L27)；
- 新 app 不应反向 import 另一个 app 的 views；
- 将该通用工具移动到项目级 `backend/api.py`，`system_setting` 和 `knowledge` 共同使用；
- `accounts` 现有响应逻辑不在本阶段重构。

## 4. 数据表设计

本阶段只创建两张表，显式配置 `db_table`，不创建 chunk/vector 表。

### 4.1 `knowledge_bases`

| 字段 | Django/数据库约束 | 说明 |
| --- | --- | --- |
| `id` | `BigAutoField`，主键 | 知识库 ID |
| `name` | `CharField(max_length=50, unique=True)` | 名称，序列化时 trim，不能为空 |
| `description` | `CharField(max_length=300)` | 内容说明，序列化时 trim，不能为空 |
| `created_by` | 用户外键，`null=True`，`on_delete=SET_NULL` | 创建人 |
| `created_at` | `DateTimeField(auto_now_add=True)` | 创建时间 |
| `updated_at` | `DateTimeField(auto_now=True)` | 更新时间 |

Meta 建议：

```text
db_table = knowledge_bases
ordering = (-updated_at, -id)
```

说明：

- 本阶段不增加 `enabled`、所有者 ACL 或 Embedding 模型字段；
- `created_by` 不出现在管理响应中；
- 名称重复返回 409，而不是数据库 500。

### 4.2 `knowledge_documents`

| 字段 | Django/数据库约束 | 说明 |
| --- | --- | --- |
| `id` | `BigAutoField`，主键 | 文档 ID |
| `knowledge_base` | `ForeignKey(KnowledgeBase, on_delete=RESTRICT, related_name=documents)` | 所属知识库 |
| `original_name` | `CharField(max_length=255)` | 清理后的原始文件名，仅用于展示 |
| `storage_key` | `CharField(max_length=512, unique=True)` | 相对存储键，不使用用户文件名拼路径 |
| `mime_type` | `CharField(max_length=64)` | `text/markdown` 或 `text/plain` |
| `extension` | `CharField(max_length=8)` | `.md` 或 `.txt` |
| `size_bytes` | `PositiveBigIntegerField` | 原始文件大小，数据库 CHECK `> 0` |
| `content_hash` | `CharField(max_length=64)` | SHA-256，不在 API 返回 |
| `status` | `CharField(max_length=16)` | 文档状态，默认 `uploaded` |
| `error_message` | `TextField(blank=True, default='')` | 安全的错误摘要 |
| `ingestion_version` | `PositiveIntegerField(default=1)` | 为后续幂等摄取预留，CHECK `> 0` |
| `created_by` | 用户外键，`null=True`，`on_delete=SET_NULL` | 上传人 |
| `created_at` | `DateTimeField(auto_now_add=True)` | 上传时间 |
| `updated_at` | `DateTimeField(auto_now=True)` | 状态更新时间 |

状态定义：

| 状态 | 本阶段是否产生 | 含义 |
| --- | --- | --- |
| `uploaded` | 是，上传后的唯一正常状态 | 原文和元数据已保存，尚未向量化 |
| `processing` | 否，后续 Worker 产生 | 正在向量化 |
| `ready` | 否，后续向量事务产生 | 可以参与向量检索 |
| `failed` | 否，后续 Worker 产生 | 向量化失败 |
| `deleting` | 是，删除第一步产生 | 原文/记录正在删除，允许重试删除 |

Meta 约束与索引：

```text
db_table = knowledge_documents
ordering = (-created_at, -id)
UNIQUE(knowledge_base_id, content_hash)
INDEX(knowledge_base_id, created_at DESC, id DESC)
INDEX(status, updated_at)
CHECK(size_bytes > 0)
CHECK(ingestion_version > 0)
CHECK(status IN uploaded/processing/ready/failed/deleting)
```

本阶段不添加 `ingestion_task_id`、`processing_started_at` 等暂不使用字段，后续接入 Celery 时通过新迁移增加。

### 4.3 删除关系

```text
knowledge_bases
    1
    │ knowledge_documents.knowledge_base_id
    │ ON DELETE RESTRICT
    N
knowledge_documents
```

- 非空知识库不能直接删除；
- 删除知识库前必须先删除其中全部文件；
- 文档表尚无 chunks 外键，后续新增 chunk 表时使用 `document → chunks CASCADE`。

## 5. 管理 API

### 5.1 路由

| Method | 路径 | 功能 | 成功状态码 |
| --- | --- | --- | --- |
| GET | `/api/knowledge-bases/` | 知识库分页、关键字搜索 | 200 |
| POST | `/api/knowledge-bases/` | 创建知识库 | 201 |
| GET | `/api/knowledge-bases/{id}/` | 知识库详情 | 200 |
| PATCH | `/api/knowledge-bases/{id}/` | 部分更新名称/描述 | 200 |
| DELETE | `/api/knowledge-bases/{id}/` | 删除空知识库 | 200 |
| GET | `/api/knowledge-bases/{id}/documents/` | 当前知识库完整文件列表 | 200 |
| POST | `/api/knowledge-bases/{id}/documents/` | 上传单个文件 | 201 |
| DELETE | `/api/knowledge-bases/{id}/documents/{document_id}/` | 删除文件和记录 | 200 |

实现建议：

- `KnowledgeBaseViewSet` 提供前五项，禁用 PUT；
- 两个嵌套 `APIView` 分别提供文件列表/上传和文件删除；
- 所有视图使用 `permission_classes = [IsSuperuser]`；
- 所有知识库 ID、文档 ID 都使用正整数校验；
- 文档查询始终同时限定 `knowledge_base_id` 和 `document_id`，跨库访问返回 404。

### 5.2 知识库分页与文档全量列表

知识库列表请求参数：

```text
page=1
page_size=20
keyword=可选，仅知识库列表使用
```

规则：

- `page` 从 1 开始；
- `page_size` 默认 20，最大 100；
- 非法分页参数返回 400；
- 知识库关键字同时匹配名称和描述，使用 `icontains`；
- 文档列表不使用单文档状态接口，返回当前知识库全部文档，按 `created_at DESC, id DESC` 排序；
- 全量文档集合供第二阶段一次请求刷新所有状态；文件表格如需分页，使用前端本地分页。

知识库列表响应中的 `data`：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

文档列表响应中的 `data`：

```json
{
  "items": []
}
```

### 5.3 知识库响应字段

```json
{
  "id": 1,
  "name": "运维制度",
  "description": "内部运维规范和值班制度",
  "document_count": 2,
  "created_at": "2026-11-15T04:00:00Z",
  "updated_at": "2026-11-15T04:00:00Z"
}
```

`document_count` 统计数据库中仍存在的全部文档，包括 `deleting` 文档，避免前端在删除完成前误删知识库。

### 5.4 文件响应字段

```json
{
  "id": 10,
  "knowledge_base_id": 1,
  "original_name": "值班规范.md",
  "mime_type": "text/markdown",
  "extension": ".md",
  "size_bytes": 10240,
  "status": "uploaded",
  "error_message": "",
  "created_at": "2026-11-15T04:05:00Z"
}
```

明确不返回：

- `storage_key` 或绝对路径；
- `content_hash`；
- `created_by`；
- 后续向量、Embedding 密钥或内部异常堆栈。

### 5.5 错误语义

| 场景 | HTTP | 要求 |
| --- | --- | --- |
| 未登录 | 401 | 使用现有 JWT 认证 |
| 非超级管理员 | 403 | 前端菜单隐藏不能替代后端校验 |
| 名称/描述为空或超长 | 400 | 返回字段级错误 |
| 文件缺失、空文件、非法 UTF-8、含 NUL、扩展名不支持 | 400 | 不保存记录，不遗留文件 |
| 文件超过 20 MiB | 413 | 后端仍检查实际字节数 |
| 知识库名称重复 | 409 | 转换唯一约束冲突 |
| 同库文件 Hash 重复 | 409 | 不保留第二次上传的原文 |
| 删除非空知识库 | 409 | 后端复核，不只依赖前端禁用 |
| 知识库或文档不存在、跨库文档 ID | 404 | 不泄漏其他库信息 |

成功响应使用项目统一 envelope；错误响应继续使用 DRF 的 `detail` 或字段错误结构，由前端现有错误拦截器处理。

## 6. 文件上传实现约束

### 6.1 上传配置

新增 settings：

```text
KNOWLEDGE_UPLOAD_ROOT
    环境变量优先；本地开发默认 backend/data/knowledge
KNOWLEDGE_MAX_FILE_SIZE
    默认 20 * 1024 * 1024，即 20,971,520 字节
FILE_UPLOAD_MAX_MEMORY_SIZE
    4 MiB；较大上传由 Django 使用临时文件
```

Compose：

```text
KNOWLEDGE_UPLOAD_ROOT=/data/knowledge
backend 与 celery-worker 均挂载 ./docker/knowledge:/data/knowledge
```

虽然本阶段没有知识库 Celery 任务，后续 Worker 也必须看到同一原文目录，因此部署结构一次配置到位。需要保证运行用户对目录具有读写权限，启动或首次上传时给出明确错误。

将 `docker/knowledge/*` 和本地开发运行数据加入 `.gitignore`，不上传真实知识文件。

### 6.2 文件名与路径

1. 对原始文件名取 basename，去除路径部分和控制字符；
2. 清理后不能为空，最长 255 个 Unicode 字符；
3. 扩展名转小写，只允许 `.md`、`.txt`；
4. 实际存储名由服务端生成 UUID；
5. 存储键格式：`<knowledge_base_id>/<uuid><extension>`；
6. 最终路径必须位于配置的根目录内，拒绝绝对路径和 `..` 逃逸；
7. `original_name` 仅用于展示，不能用于磁盘路径拼接。

### 6.3 流式保存与校验

上传处理顺序：

```text
校验知识库和 multipart file 字段
→ 检查声明大小和扩展名
→ 在目标知识库目录创建临时文件
→ 按 UploadedFile.chunks() 读取
→ 同步计算 SHA-256、累计实际字节数、检查 NUL
→ 使用增量 UTF-8 decoder 校验，不把 20 MiB 全文一次性读入内存
→ 空文件/超限/非法内容：删除临时文件并返回错误
→ 计算最终 UUID 路径并原子 rename
→ 创建 knowledge_documents 记录
→ 数据库失败：删除已落盘文件并返回错误
```

其他要求：

- 只接受一个名为 `file` 的文件字段；
- MIME 只作为元数据，不能代替扩展名和内容校验；
- 同库 Hash 在上传服务中先查一次，数据库唯一约束负责并发最终保护；
- 相同文件可以存在于不同知识库；
- 临时文件与最终文件位于同一文件系统，保证 rename 语义；
- 日志只记录知识库 ID、文档 ID、文件大小和错误类型，不记录正文、完整路径或密钥。

### 6.4 上传响应

本阶段创建原文记录成功，使用 **201 Created**。响应中的 `status` 必须为 `uploaded`。

后续接入 Celery 后仍可保留 201，因为 HTTP 资源已经创建；异步进度由 `status` 和后续任务接口表达，不需要通过改变状态码制造兼容性变化。

## 7. 删除与一致性

### 7.1 删除知识库

1. 在事务中锁定知识库；
2. 检查是否仍有文档；
3. 有文档返回 409；
4. 无文档才删除；
5. 数据库 `RESTRICT` 是并发情况下的最终保护，唯一/外键异常映射为可读错误。

上传创建文档时也应在事务中读取或锁定所属知识库，避免知识库删除与文件登记发生无约束竞态。

### 7.2 删除文件

不能简单依赖“先删文件再删数据库”，否则数据库失败会留下指向缺失文件的记录。采用可重试的两步状态：

```text
事务锁定文档并设置 status = deleting
→ 提交状态
→ 删除原文；文件不存在视为已删除
→ 删除 knowledge_documents 记录
→ 返回成功
```

异常处理：

- 原文删除失败：保留 `deleting` 记录并保存安全的错误摘要，返回错误，允许管理员重试；
- 原文已删除但数据库删除失败：记录仍保留 storage_key、`deleting` 和安全的错误摘要，重试时把“文件不存在”视为成功并继续删除记录；
- 本阶段没有 Worker；后续接入 Worker 后，必须同时通过版本和状态阻止旧任务在删除后重新写回向量；
- 删除请求进行中禁止重复点击；若失败留下 `deleting`，前端显示“删除失败”并允许重试删除，服务端仍需保证操作幂等。

## 8. 前端设计：放在系统设置内部

### 8.1 页面结构

保留现有路由 `/system-setting` 和 `authority: ['super']`，不新增顶级菜单。

新增系统设置容器页：

```text
系统设置
├── 大模型配置（现有 llm-config.vue）
└── 知识库管理（新增 knowledge-base.vue）
        │
        ├── 左：知识库搜索、新建、分页、列表、编辑、删除
        │
        └── 右：当前知识库描述、文件上传、文件列表和删除
```

建议使用 Naive UI `NTabs`：

- 页签值：`llm` 和 `knowledge`；
- 默认显示 `llm`；
- 使用 URL query（如 `?tab=knowledge`）保存当前页签，刷新后可恢复；
- 非法 query 回退到 `llm`；
- 页签内容 lazy 渲染，避免普通查看模型配置时自动请求知识库接口；
- 不改变现有路由 name、菜单标题和权限码。

### 8.2 前端文件变更

| 文件 | 新建/修改 | 内容 |
| --- | --- | --- |
| `frontend/web/src/views/system-setting/index.vue` | 新建 | 系统设置标题和两个页签 |
| [llm-config.vue](../frontend/web/src/views/system-setting/llm-config.vue) | 修改 | 作为“大模型配置”页签内容，移除重复页面级标题，保留现有业务逻辑 |
| `frontend/web/src/views/system-setting/knowledge-base.vue` | 新建 | 知识库管理主页面，组合列表和文件面板 |
| `frontend/web/src/views/system-setting/components/knowledge-base-form-modal.vue` | 新建 | 新建/编辑知识库弹窗和表单校验 |
| `frontend/web/src/views/system-setting/components/knowledge-document-panel.vue` | 新建 | 文件上传、列表、状态和删除 |
| `frontend/web/src/api/knowledge/index.ts` | 新建 | API 类型和全部请求函数 |
| [system-setting.ts](../frontend/web/src/router/routes/modules/system-setting.ts) | 修改 | 页面组件改为 `system-setting/index.vue`，路径和权限不变 |
| `frontend/web/src/views/system-setting/__tests__/knowledge-base.spec.ts` | 新建 | 页签、CRUD、上传和异常交互测试 |

### 8.3 API 封装

使用主 `requestClient`，复用：

- Bearer Token 和刷新逻辑；
- `{code: 0, data}` 解包；
- 统一错误提示；
- `requestClient.upload` 的 FormData 处理。

依据：[request.ts:73-102](../frontend/web/src/api/request.ts#L73-L102)、[uploader.ts:13-39](../frontend/packages/effects/request/src/request-client/modules/uploader.ts#L13-L39)。

建议类型：

```text
KnowledgeBase
KnowledgeBaseListParams
KnowledgeBaseListResult
CreateKnowledgeBaseParams
UpdateKnowledgeBaseParams
KnowledgeDocument
KnowledgeDocumentListResult
KnowledgeDocumentStatus
```

上传函数直接传 `{ file }`，不要传数组，避免触发通用上传器的 `file[0]` 数组序列化。

### 8.4 知识库管理交互

- 名称和描述必填，前端限制 50/300 字符；
- 搜索输入 350ms 防抖，回车立即搜索；
- 切换知识库时加载第一页文件；
- 新建、编辑成功后刷新列表并保持合理选中项；
- 删除末页最后一项后，如当前页为空且页码大于 1，回退一页；
- `document_count > 0` 时删除按钮禁用并提示先删除文件，后端仍必须复核；
- 长名称、长描述、空状态、加载状态和移动端布局需要可用。

### 8.5 文件上传与列表交互

使用 `NUpload + NUploadDragger`：

- 单文件，`max = 1`；
- `accept = .md,.txt,text/markdown,text/plain`；
- 自定义请求调用 `requestClient.upload`；
- 上传前检查扩展名、非空和 20 MiB；
- 未选择知识库时禁止上传；
- 上传中禁止重复提交和切换当前上传请求；
- 成功后清空上传组件临时文件并刷新文件列表和知识库 `document_count`；
- 409、413 等错误保留在页面提示中，不伪造成功记录；
- 本阶段上传后不轮询，因为没有后台任务。

状态显示：

| 后端状态 | 前端文案 |
| --- | --- |
| `uploaded` | 已上传（未向量化） |
| `processing` | 向量化中（为后续兼容） |
| `ready` | 已向量化（本阶段不会产生） |
| `failed` | 处理失败（本阶段不会产生） |
| `deleting` | 删除中；若 `error_message` 非空则显示“删除失败，可重试” |

页面顶部显示明确说明：“当前仅管理知识库原文，切片和向量化将在后续阶段接入。”本阶段不显示重试、重建、下载或检索按钮。

## 9. 部署与代理配置

修改 [frontend/nginx.conf](../frontend/nginx.conf) 的 API location：

- `client_max_body_size` 设置为略大于 20 MiB，例如 `21m`，容纳 multipart 边界开销；
- 后端仍执行真实文件 20 MiB 限制，Nginx 不代替业务校验；
- 上传请求超时应与前端上传超时、后端 uWSGI 60 秒限制一起验证；
- 不为本阶段修改 SSE 专用代理逻辑。

修改 Compose：

- backend 和 celery-worker 使用相同 `KNOWLEDGE_UPLOAD_ROOT=/data/knowledge`；
- 两个服务挂载相同 `./docker/knowledge:/data/knowledge`；
- 原文目录与 PostgreSQL/Redis 数据一样不进入 Git；
- 部署前检查目录权限和磁盘剩余空间。

## 10. 测试设计

### 10.1 模型与迁移

- 全新 PostgreSQL 数据库可执行本阶段迁移；
- 两张表使用指定 `db_table`；
- 知识库名称唯一；
- 同库 Hash 唯一，不同库相同 Hash 可共存；
- 文档大小和版本 CHECK 生效；
- 文档外键为 `RESTRICT`；
- 不需要 vector 扩展，不出现 chunk/vector 表。

### 10.2 知识库 API

- 未登录 401、普通用户 403、超级管理员成功；
- 创建、详情、部分更新、分页和搜索；
- 空名称、空描述、空白字符和超长字段；
- 重名返回 409；
- 非空知识库删除返回 409；
- 空知识库删除成功；
- 删除末页数据的分页边界；
- `document_count` 正确。

### 10.3 文件 API 与存储

使用 Django 临时目录作为测试存储根目录，不污染真实 `docker/knowledge`：

- 中文 Markdown 和 TXT 上传成功；
- 文件存储路径使用 UUID 文件名，原始文件名不参与路径拼接；
- 响应不包含 storage_key/hash；
- 空文件、超限、错误扩展名、无文件、多文件、非法 UTF-8、NUL；
- 文件名带路径、控制字符或只有扩展名；
- 同库重复上传 409，不同库允许；
- 当前知识库完整列表、跨库隔离和排序；
- 跨库文档 ID 返回 404；
- 模拟数据库失败时清理已保存文件；
- 模拟 rename/写盘失败时清理临时文件；
- 文件删除成功、文件已不存在、文件删除失败后的重试；
- 数据库删除失败后记录仍可诊断和再次删除。

### 10.4 前端

- 系统设置默认显示大模型配置，知识库页签 query 可恢复；
- 无权限路由行为不变；
- 知识库搜索、创建、编辑、删除和分页；
- 非空知识库删除禁用；
- 文件类型、空文件和大小预校验；
- 上传 FormData 字段为单个 `file`；
- 上传成功刷新文件和文档数；
- 409/413 错误提示，不插入虚假记录；
- 文件删除、空状态、长文件名和加载状态；
- 本阶段不启动状态轮询。

## 11. 推荐实施顺序

1. 创建 `knowledge` app、两个 Model 和迁移，先完成模型测试；
2. 抽取共享响应工具并接入知识库 CRUD，保持现有系统设置 API 回归通过；
3. 实现文件存储和上传/列表/删除服务，再完成异常与清理测试；
4. 配置共享原文目录、Git 忽略和 Nginx 上传限制；
5. 新建前端 API 封装和系统设置页签容器；
6. 实现知识库列表、表单和文件面板；
7. 执行后端测试、前端测试、类型检查和生产构建；
8. 最后进行端到端验收，不提前接入空 Celery 任务或向量代码。

每一步完成后先评审对应代码和测试，再进入下一步。

## 12. 最终验收清单

- [ ] `knowledge` 作为独立 app 注册，只有两张本阶段业务表；
- [ ] 知识库 CRUD、搜索和分页使用真实 PostgreSQL；
- [ ] 所有管理 API 均要求超级管理员；
- [ ] Markdown/TXT 单文件上传、20 MiB、UTF-8/NUL 和 SHA-256 去重生效；
- [ ] 原始文件以 UUID 名称写入受控目录；
- [ ] 文件列表刷新后仍可见，不依赖当前页面临时状态；
- [ ] 文件删除和失败重试不会留下不可诊断状态；
- [ ] 非空知识库删除返回 409；
- [ ] 系统设置内出现“知识库管理”页签，原大模型配置功能不回归；
- [ ] 上传后显示“已上传（未向量化）”，没有伪造 `ready`；
- [ ] 本阶段没有 Embedding、Celery 业务投递、chunk 表或 Agent 工具；
- [ ] 后端测试、前端测试、类型检查和构建通过；
- [ ] 运行目录、API Key 和真实上传文件不进入 Git。
