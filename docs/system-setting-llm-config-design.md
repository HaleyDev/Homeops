# system_setting 与大模型配置设计

> 日期：2026-11-14  
> 状态：规划稿（已按固定用途标签和每轮重新加载方案修订），未实施  
> 范围：新增独立 Django 应用 `system_setting`，首期只开放文本模型配置，预留 Embedding。  
> 本文仅做设计，不创建应用、不修改业务代码、不记录任何真实 API Key。

## 1. 最终建议：使用两张表，不建动态类别表或选择表

结合当前需求和 Insight 的实现，HomeOps 可以采用：

1. **LLMProvider：供应商表**，保存 base_url、加密 API Key、协议和启用状态。
2. **LLMModel：模型表**，保存供应商下的多个模型，并使用固定的模型类型和选择标签。

不再单独建立第三张“当前选择表”，也不建立可由用户随意新增类别的动态类别表。

模型用途在代码中使用固定枚举：

- `text`：文本对话模型，首期实际使用；
- `embedding`：向量模型，预留配置能力，后续接入知识库时使用。

选择状态也使用固定标签。当前只需要选择文本模型时，页面上只开放 text；以后增加 Embedding，不需要再增加一张选择表。

## 2. Insight 的实际设计与 HomeOps 的取舍

### 2.1 Insight 的结构

Insight 不是三张表，而是一张 `model_providers` 表：

- `models` 字段用 JSON 保存模型数组；
- 每个模型包含 `name`、`type` 和可选 `dimensions`；
- 类型只有代码常量 `text` 和 `embedding`；
- 供应商表通过 `selected_model` 保存当前文本模型名；
- 通过 `selected_embedding_model` 保存当前 Embedding 模型名。

对应源码：

- [模型与固定类型](/home/haley/project/gitlab/insight/backend/internal/model/model_provider.go#L12-L55)；
- [类型、模型名和选中项校验](/home/haley/project/gitlab/insight/backend/internal/service/model_provider_service.go#L140-L194)；
- [切换时清理其它供应商的选中状态](/home/haley/project/gitlab/insight/backend/internal/repository/model_provider_repo.go#L45-L99)。

Insight 的“固定类型 + 固定选中字段”很适合类别数量明确的场景，但它的全局唯一选择主要依赖事务和清理逻辑。HomeOps 已经希望把模型拆成独立表，因此不必再退回 JSON 模型列表。

### 2.2 HomeOps 的关系型等价方案

保留独立模型表，并增加一个可空、唯一的 `selected_for` 字段：

- 未被选中：`selected_for=NULL`；
- 当前文本模型：`selected_for="text"`；
- 当前 Embedding 模型：`selected_for="embedding"`。

`selected_for` 做唯一约束。PostgreSQL 的唯一索引默认允许多个 NULL，因此可以有很多未选模型，但每种固定标签最多只有一条模型记录。

这比在模型表增加普通 `is_selected` 布尔值更直接：可空唯一标签无需额外的部分唯一索引，就能限制“每种类型全局只能有一条选中记录”。

## 3. 应用边界

### 3.1 system_setting 负责

- 供应商和模型目录；
- 固定模型类型及选择标签；
- API Key 加密、解密和脱敏；
- 配置校验与管理员 API；
- 按固定用途解析运行时模型配置。

### 3.2 ai_assistant 负责

- 每次收到一条新的用户消息时，重新读取 text 当前配置；
- 根据本次读取的配置创建本轮 LLM、Agent 和 Runner；
- 不直接操作 system_setting 表，通过服务接口获取配置；
- 配置缺失或不可用时，返回安全、可理解的错误。

建议接口：

```text
get_effective_model_config(ModelType.TEXT)
    → EffectiveModelConfig
```

后续知识库向量化使用同一个接口和 `ModelType.EMBEDDING`。system_setting 不反向导入 ai_assistant，避免循环依赖。

### 3.3 不做通用配置中心

虽然应用名为 system_setting，本期只开放模型配置。其它系统配置后续可以在该应用中增加独立模块，但不引入通用 key-value 表来承载模型关系。

## 4. 数据表设计

### 4.1 LLMProvider：供应商表

| 字段 | 建议类型 | 说明 |
| --- | --- | --- |
| `id` | BigAutoField | 主键 |
| `name` | CharField(80) | 展示名称 |
| `slug` | SlugField(50), unique | 稳定内部标识 |
| `protocol` | CharField(32) | 首期固定为 `openai_compatible` |
| `base_url` | CharField/URLField(500) | API 根地址 |
| `api_key_ciphertext` | TextField, blank | 应用层加密后的 API Key |
| `api_key_version` | CharField(16), blank | 加密密钥版本，便于轮换 |
| `is_active` | BooleanField | 是否允许选择和运行 |
| `extra_config` | JSONField, default=dict | 非敏感协议扩展参数 |
| `created_by` / `updated_by` | FK User, null, SET_NULL | 操作人 |
| `created_at` / `updated_at` | DateTimeField | 时间信息 |

规则：

- `slug` 唯一；
- base_url 只允许 http/https，不能把用户名、密码或 Key 放在 URL 中；
- `extra_config` 不得保存 API Key、Token 或密码；
- 是否允许空 API Key 由协议决定；OpenAI 兼容远程服务首期默认要求配置；
- 供应商显示名与协议分开，运行时不能根据显示名硬编码调用方式。

### 4.2 LLMModel：模型表

| 字段 | 建议类型 | 说明 |
| --- | --- | --- |
| `id` | BigAutoField | 主键 |
| `provider` | FK LLMProvider, CASCADE | 所属供应商 |
| `model_key` | CharField(160) | 调用 API 的真实模型标识 |
| `display_name` | CharField(100) | 页面展示名称 |
| `model_type` | CharField(20), choices | 固定为 text 或 embedding |
| `selected_for` | CharField(20), null, blank, unique | 当前选择标签；未选必须为 NULL |
| `parameters` | JSONField, default=dict | 非敏感参数，如温度、Embedding 维度 |
| `is_active` | BooleanField | 是否允许选择和运行 |
| `created_at` / `updated_at` | DateTimeField | 时间信息 |

建议约束：

```text
UNIQUE(provider, model_key, model_type)
UNIQUE(selected_for)
```

第二个唯一约束允许多个 `selected_for=NULL`，但最多一个 text 和一个 embedding。

模型类型与选择标签的校验：

- `model_type` 只能使用代码中定义的固定枚举；
- `selected_for` 非空时必须等于 `model_type`；
- 未选模型必须保存为 `NULL`，不能保存为空字符串，否则空字符串也会占用唯一值；
- 保存选择时，模型和供应商必须启用；
- 可以通过 Service 校验和数据库 CheckConstraint 双重保证标签与类型一致；
- 已被选中的模型和对应供应商不允许直接删除或停用，应先切换选择。

同一个供应商的同一个 model_key 如果确实同时支持文本和 Embedding，可以分别建立 text、embedding 两条记录，其参数和用途不同；通过三元唯一约束避免同类型重复。

### 4.3 为什么不需要第三张选择表

当前类型固定且很少，选择状态可以直接成为模型记录上的固定标签：

- 不需要动态类别 CRUD；
- 不需要再关联一次 provider/model；
- `selected_for` 本身即可查询当前选择；
- 唯一标签可直接保证每个固定用途最多一个选择；
- 增加 embedding 只需使用已有枚举值，不增加表。

如果未来出现大量动态用途、按用户选择、选择历史或复杂路由，才需要重新评估独立选择表；这些都不是本期需求。

## 5. 选择、切换和删除规则

### 5.1 选择模型

在事务中执行：

1. 校验管理员权限；
2. 查询并锁定新模型及供应商；
3. 校验 `model_type`、启用状态和固定选择标签；
4. 将该类型旧模型的 `selected_for` 清为 NULL；
5. 将新模型的 `selected_for` 设置为其固定类型；
6. 提交事务。

唯一约束是最后防线。并发选择同一类型时，数据库应拒绝产生第二条同标签记录，不能只在 Python 中先查询再更新。

### 5.2 清除选择

将当前模型的 `selected_for` 更新为 NULL 即可。没有标签表示该用途未配置，不需要创建空选择行。

### 5.3 删除与停用

- 已选模型：禁止删除或停用，并提示先切换；
- 含已选模型的供应商：禁止删除或停用；
- 其它模型和供应商：正常管理；
- 不静默切换到另一家供应商；当前模型不可用时明确报错。

选择标签不是历史记录。如果以后需要审计“谁在何时从哪个模型切换到哪里”，应增加独立审计日志，不在模型表保存多份选择历史。

## 6. API Key 与敏感信息

- API Key 必须应用层加密后存库，不明文保存；
- 主密钥来自独立环境变量，例如 `SYSTEM_SETTING_ENCRYPTION_KEY`；
- 主密钥不写入 Git、数据库、迁移、前端或文档；
- 主密钥需独立备份，丢失后已有密文无法使用；
- API 的 `api_key` 只能 write-only；
- GET 只返回 `api_key_configured: true/false`，不返回明文或密文；
- 更新时未传或留空表示保持原 Key；`clear_api_key=true` 才明确清除；
- Django Admin、DRF、结构化日志、异常、测试连接和 SSE 不得输出 Key；
- 运行时配置对象的 repr/日志格式必须隐藏 Key；
- base_url 和测试连接必须校验协议并设置超时，避免通过重定向泄露请求头；
- 管理接口首期仅允许超级管理员，隐藏前端菜单不能代替后端权限。

## 7. 每轮问答重新加载配置

### 7.1 不是进程启动时，也不是会话创建时

当前 ai_assistant 使用静态 root_agent 和全局 Runner 缓存，见[现有加载方式](../backend/ai_assistant/services.py#L10-L39)。如果继续复用，修改数据库配置后仍可能使用旧模型。

目标行为必须明确为：

> **每次发送一条新消息、开始一轮问答时，都重新加载当前选择，并创建本轮 LLM/Agent/Runner。**

不是只在 Django 启动时加载，也不是一个聊天会话第一次创建后一直复用。

### 7.2 同一会话中途修改配置

假设：

1. 用户在同一会话中发送消息 A，使用模型甲；
2. 管理员随后把文本模型切换为模型乙；
3. 用户在该会话中继续发送消息 B。

消息 B 必须重新查询 `selected_for="text"`，并创建使用模型乙的新 LLM/Agent/Runner。不能因为会话 ID 没变而继续使用模型甲。

正在流式生成的消息 A 不在中途更换模型，以免同一轮出现混用；它使用本轮开始时的配置快照。配置切换从下一轮消息开始生效。

### 7.3 每轮处理流程

```text
收到一条用户消息
    ↓
读取 selected_for = text 的模型及 provider
    ↓
重新校验启用状态、类型、base_url 和 Key
    ↓
解密 API Key（仅内存）
    ↓
创建本轮 LiteLlm → Agent → Runner
    ↓
复用 ADK DatabaseSessionService，执行本轮对话
    ↓
本轮结束，丢弃本轮 LLM/Runner 引用
```

可以复用 ADK 的 DatabaseSessionService 和既有 ADK Session 历史，但不能全局缓存与供应商配置绑定的 LLM/Agent/Runner。

不应通过修改全局 root_agent 的 model/api_key 来实现切换，否则并发请求可能互相覆盖配置。

### 7.4 配置解析与错误

运行时查询类似：

```text
LLMModel.objects.select_related("provider").get(selected_for=ModelType.TEXT)
```

- DoesNotExist：文本模型尚未配置；
- 多条同标签：数据库唯一约束应阻止，运行时仍将数据异常视为配置错误；
- 模型或供应商停用：配置不可用；
- model_type 与 selected_for 不一致：配置无效；
- Key 缺失或无法解密：配置不可用，不泄露内部细节。

text 未配置只影响文本对话，不应导致 Django 启动失败或管理页面无法打开。Embedding 未配置不应影响文本对话。

## 8. 管理 API 与页面建议

### 8.1 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/POST | `/api/system-setting/llm/providers/` | 供应商列表、创建 |
| GET/PATCH/DELETE | `/api/system-setting/llm/providers/{id}/` | 供应商详情、修改、删除 |
| GET/POST | `/api/system-setting/llm/models/` | 模型列表、创建 |
| GET/PATCH/DELETE | `/api/system-setting/llm/models/{id}/` | 模型详情、修改、删除 |
| GET | `/api/system-setting/llm/selections/` | 返回 text/embedding 固定用途及当前模型 |
| PUT | `/api/system-setting/llm/selections/{category}/` | 为固定用途选择 model_id |
| DELETE | `/api/system-setting/llm/selections/{category}/` | 清除固定用途选择 |
| POST（后续） | `/api/system-setting/llm/providers/{id}/test/` | 测试连接 |

`{category}` 只是固定用途的路由参数，后端必须拒绝 text/embedding 之外的值，不代表支持动态类别。

### 8.2 页面

模型配置页面分为：

1. 供应商管理；
2. 供应商下的模型管理；
3. 当前选择区域，首期只显示“文本模型”，Embedding 后续开放。

模型行可显示固定标签：

- `文本模型` / `Embedding 模型`：model_type；
- `当前文本模型`：selected_for=text；
- `当前 Embedding 模型`：selected_for=embedding。

操作按钮根据状态显示“设为当前文本模型”或“取消当前选择”。后端仍需验证类型和状态，不能依赖前端过滤。

API Key 编辑框默认留空，提示“已配置，留空保持不变”，不提供查看原 Key 的入口。选择保存成功后提示“从下一轮对话开始生效”。

## 9. 现有配置迁移

- 不把现有真实 API Key 写入迁移、测试夹具或文档；
- 管理员通过页面录入供应商、模型和文本选择；
- 短期可保留受控的旧配置回退方案，但不能在新代码中复制旧密钥；
- 数据库配置验证可用后，移除静态密钥依赖；
- 没有可用 text 配置时，对话返回“文本模型尚未配置，请联系管理员”，系统设置页面仍可正常修复配置。

## 10. 测试与验收

### 数据和选择

- 一个供应商可拥有多个模型；
- 同供应商、同类型不能重复 model_key；
- 同 model_key 可按 text/embedding 分别建记录；
- 未选模型可以有多条 NULL，空字符串不能作为未选值；
- 全系统最多一个 selected_for=text 和一个 selected_for=embedding；
- 跨供应商切换会清除旧标签；
- 并发选择不会产生两个同类型当前模型；
- 类型不匹配、停用模型和停用供应商不能选择；
- 已选模型及其供应商不能删除或停用。

### 安全

- 未认证和普通用户不能访问管理 API；
- 所有响应不包含明文或密文 Key；
- 留空更新保留 Key，明确清除才删除；
- 日志、异常和 SSE 不包含 Key；
- 非法 base_url、类型和协议被拒绝。

### 每轮重新加载

- 同一会话消息 A 使用模型甲；
- 切换选择后，同一会话消息 B 创建新的 LLM/Runner 并使用模型乙；
- 修改同一供应商的 base_url、Key 或模型参数后，下一轮同样读取新值；
- 正在执行的一轮仍使用自己的配置快照；
- ADK Session 历史继续保留，不因切换模型而删除；
- 测试使用 fake runner/mock 服务，不调用真实供应商。

## 11. 推荐实施顺序

1. 创建 system_setting 应用、供应商表、模型表和固定枚举；
2. 实现 selected_for 唯一标签、事务切换和加密服务；
3. 实现管理员 API、脱敏和权限测试；
4. 实现按 ModelType 的 EffectiveModelConfig 查询；
5. 改造 ai_assistant 为每条消息重新加载配置并创建 LLM/Agent/Runner；
6. 实现系统设置页面，首期只开放文本模型选择；
7. 完成同一会话中途切换模型的回归验证和迁移文档；
8. 后续再开放 Embedding 消费者、测试连接和选择审计。

## 12. 首期默认决策

| 决策点 | 建议 |
| --- | --- |
| 表数量 | 两张：供应商、模型 |
| 模型用途 | 代码固定 text/embedding，不做动态类别表 |
| 当前选择 | 模型上的可空唯一 selected_for 标签 |
| 配置作用域 | 全局系统配置 |
| 管理权限 | 首期仅超级管理员 |
| 首个协议 | OpenAI 兼容接口 |
| API Key | 数据库存密文，主密钥来自独立环境变量 |
| 加载时机 | 每条新消息、每一轮问答重新加载并创建 LLM |
| 同会话切换 | 下一条消息使用新配置，当前流式轮次不中途换模型 |
| 故障转移 | 不做隐式自动切换 |

这个方案保留 Insight“固定类型、固定选择”的简单性，同时利用独立模型表和可空唯一标签，让 HomeOps 在当前只有文本模型、后续增加 Embedding 的情况下保持结构简单，并确保同一会话中的下一轮消息能够使用最新配置。
