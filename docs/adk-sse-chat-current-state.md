# ADK 与前端 SSE 对话现状梳理

> 梳理日期：2026-11-14  
> 范围：AI 助手的前端页面、SSE 请求、Django 视图、ADK Runner、会话/消息持久化及部署配置。  
> 说明：本文基于静态代码阅读；本次未修改业务代码，未启动服务，也未调用真实模型。因此，下文将“代码已经实现的行为”和“需要运行验证或继续完善的事项”分开描述。

## 1. 总体结论

当前代码已经不是单纯的 UI Demo，基础链路已经具备：

- JWT 认证、会话归属校验；
- 会话创建、列表、删除和历史消息查询；
- 首次发送时自动创建会话并生成标题；
- ADK `Runner.run_async()` 调用；
- ADK 事件到 SSE 帧的转换；
- 前端逐帧更新回答、思考状态和工具调用状态；
- 用户消息落库，以及收到 `done` 后的助手消息落库；
- 浏览器主动取消、切换会话时保留后台流式输出。

但这条链路仍更接近“基本流程已接通，边界情况待补齐”。优先需要关注的是：

1. 容器部署配置中的后端端口不一致；
2. 前端把 `done`/`error` 当作结束信号，却没有处理“HTTP 流正常 EOF、但没有结束事件”的兜底；
3. 助手消息只在 `done` 时落库，取消、断流和异常会留下不完整的业务历史；
4. 页面注释强调多会话后台流，但实际只有一个全局 `streamingSessionId` 和一个全局状态文案，不能完整支持多会话并发；
5. ADK 会话历史与业务消息历史是两套数据，取消、删除、落库失败时可能不一致；
6. 长连接超时、同步 worker 占用、解析健壮性和专项测试仍需补齐。

## 2. 代码地图与职责

| 层次 | 位置 | 当前职责 |
| --- | --- | --- |
| Agent 定义 | [agent.py](../backend/ai_assistant/agent/agent.py#L8-L50) | 从环境变量读取模型、Base URL、API Key；通过 LiteLLM 创建 ADK Agent；注册服务器状态查询工具。 |
| 演示工具 | [agent.py](../backend/ai_assistant/agent/agent.py#L16-L37) | `get_server_status` 目前返回 backend、db、elasticsearch 的 mock 状态，不是真实运维查询。 |
| ADK/SSE 服务层 | [services.py](../backend/ai_assistant/services.py#L10-L91) | 懒加载并缓存 Runner 和 DatabaseSessionService；复用 Django 默认 PostgreSQL 配置；把 ADK 事件转换成 SSE；用同步生成器桥接 ADK 异步事件流。 |
| 对话视图与落库 | [views.py](../backend/ai_assistant/views.py#L21-L55) | 校验请求、校验会话归属、写用户消息、设置首条消息标题，返回 `StreamingHttpResponse`。 |
| 助手消息记录 | [views.py](../backend/ai_assistant/views.py#L83-L115) | 包装上游 SSE 帧并原样转发，同时聚合 text、thinking、tool_call，在 `done` 时写助手消息。 |
| 业务数据模型 | [models.py](../backend/ai_assistant/models.py#L8-L36) | ChatSession 保存用户会话；ChatMessage 保存用户/助手消息、思考文本和工具调用参数。 |
| 会话接口 | [views.py](../backend/ai_assistant/views.py#L58-L80) | 提供会话 CRUD 和指定会话的消息历史；查询集按当前用户隔离。 |
| 路由 | [urls.py](../backend/ai_assistant/urls.py#L6-L11)、[项目路由](../backend/backend/urls.py#L15-L18) | 对外提供 `/api/ai/chat/`、`/api/ai/sessions/` 及嵌套消息接口。 |
| 前端 AI API | [index.ts](../frontend/web/src/api/ai/index.ts#L47-L149) | 定义 SSE 事件类型；用 fetch 和 ReadableStream 读取 POST 响应并解析事件。 |
| 前端会话 API | [index.ts](../frontend/web/src/api/ai/index.ts#L151-L189) | 创建、列出、删除会话以及读取历史消息；使用独立的 RequestClient。 |
| 页面状态与交互 | [index.vue](../frontend/web/src/views/ai-assistant/index.vue#L38-L399) | 管理会话、消息缓存、后台流、取消、事件分发和页面 loading 状态。 |
| 页面展示 | [index.vue](../frontend/web/src/views/ai-assistant/index.vue#L402-L477)、[markdown.ts](../frontend/web/src/views/ai-assistant/markdown.ts#L1-L18) | 气泡列表、输入框和 Markdown 渲染；原始 HTML 不启用。 |
| 通用 SSE 模块 | [sse.ts](../frontend/packages/effects/request/src/request-client/modules/sse.ts#L9-L112) | 框架已有的原始 chunk 读取模块；AI 页面当前没有使用它，AI API 中另写了一套 SSE 帧解析。 |
| 部署 | [uwsgi.ini](../backend/uwsgi.ini#L1-L32)、[nginx.conf](../frontend/nginx.conf#L12-L26)、[docker-compose.yml](../docker-compose.yml#L12-L25) | uWSGI 提供后端，Nginx 代理 `/api/`，Compose 暴露端口并注入模型和数据库环境变量。 |

## 3. 当前完整调用链

### 3.1 页面初始化和历史回放

1. 页面挂载后请求会话列表，默认选择服务端返回的第一项。
2. 切换会话时，先把当前消息数组放入内存 Map，再展示目标会话。
3. 目标会话有内存缓存就直接使用；没有缓存则请求业务消息历史。
4. 历史接口读取 ChatMessage，而不是读取 ADK Session。
5. 空会话显示本地欢迎气泡；欢迎消息不写数据库。
6. 历史回放目前只恢复 role 和 content，thinking 与 tool_calls 虽能从接口返回，但页面映射时没有展示。

相关实现见[页面初始化与历史加载](../frontend/web/src/views/ai-assistant/index.vue#L137-L154)、[历史消息转换](../frontend/web/src/views/ai-assistant/index.vue#L183-L229)。

### 3.2 发送一条消息

1. 页面读取并 trim 输入；当前视图正在流式输出时禁止再次提交。
2. 如果没有 session_id，先创建业务会话；如果有，则直接使用当前会话。
3. 页面立即追加用户气泡和 loading 状态的 AI 气泡，并创建 AbortController。
4. 前端向 `/api/ai/chat/` 发起带 Bearer Token 的 JSON POST。
5. 后端校验 message 和 UUID 格式的 session_id，再按 session_id + 当前用户查询 ChatSession；无权限或不存在的会话都表现为 404。
6. 如果这是首条消息且标题为空或 `New Chat`，后端取问题前 50 个字符作为标题。
7. 用户消息先写 ChatMessage，然后才创建流式响应。
8. ADK 服务按当前用户 ID 和同一个 session_id 查询 ADK Session；不存在则创建。
9. `Runner.run_async()` 接收本轮用户 Content，持续产生 ADK Event。
10. 每个 Event 被翻译为零到多个 SSE 帧，经记录包装器原样发给浏览器。
11. 浏览器按空行拆帧、JSON.parse 数据，再更新对应气泡或状态。
12. 收到 `done` 后，后端写入一条助手 ChatMessage，前端结束 loading。

### 3.3 数据关系

```text
浏览器页面
  ├─ 会话 CRUD / 历史回放 ──> Django 业务表 ChatSession + ChatMessage
  └─ POST 对话 / SSE <──────> Django 流式视图
                                  ├─ 写业务用户消息
                                  ├─ ADK Runner + DatabaseSessionService
                                  │     └─ ADK 自己的 Session/Event 历史
                                  └─ done 时写业务助手消息
```

两套历史使用相同的 user_id 和 session_id 关联，并配置到同一个 PostgreSQL 数据库，但用途不同：

- **ADK 历史**：供 Agent 后续轮次理解上下文和执行工具。
- **业务历史**：供页面会话列表、历史回放和业务审计使用。
- 当前没有统一事务或补偿机制保证两套历史始终一致。

## 4. 当前 SSE 协议

帧格式为：

```text
event: <事件名>
data: <单行 JSON>

```

| 事件 | 数据字段 | 后端产生时机 | 前端当前处理 | 业务落库 |
| --- | --- | --- | --- | --- |
| `session` | `session_id` | 每次流开始时首先发送 | 回显并兜底同步当前 session_id | 否 |
| `text` | `detail` | ADK Part 含普通文本 | 追加到当前回答气泡 | 聚合到助手 content |
| `thinking` | `detail` | ADK Part 的 thought 为真 | 仅显示“思考中…” | 聚合到助手 thinking，但历史页不展示 |
| `tool_call` | `name`, `args` | ADK Part 含 function_call | 显示“调用工具：名称” | 保存名称和参数，但历史页不展示 |
| `tool_response` | `name` | ADK Part 含 function_response | 显示“整理结果…” | 不保存工具返回值 |
| `done` | `total_tokens` | ADK Event 判定为 final response | 结束 loading、清理状态 | 创建助手消息；token 数未保存、页面也未使用 |
| `error` | `message` | ADK 异步迭代中捕获异常，文本截断到 200 字符 | 弹错误提示并结束 loading | 不创建助手消息 |

协议细节见[后端帧转换](../backend/ai_assistant/services.py#L34-L58)和[前端事件类型](../frontend/web/src/api/ai/index.ts#L47-L82)。

需要区分两类错误：

- **HTTP 响应建立前**：参数、认证、会话归属等错误走 DRF 的非 2xx JSON 响应。
- **已经开始流式输出后**：大部分 ADK 迭代异常被转换成 HTTP 200 流内的 `error` 帧，不能再通过 HTTP 状态码表达。

当前协议没有 turn_id、SSE id、retry、heartbeat 或断点续传字段。

## 5. 已经做得比较好的部分

- **认证与越权隔离**：对话和会话接口使用全局 JWT 认证，会话查询按当前用户过滤。
- **禁用代理缓冲的响应头**：后端设置了 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。
- **跨块读取**：前端使用 TextDecoder 的 stream 模式和缓冲区，能够处理一个 SSE 帧被拆到多个网络 chunk 的常见情况。
- **后台输出引用**：发送时捕获对应消息数组和 replyKey，切换会话后，文本仍写入原会话数组，而不是直接写新视图。
- **取消入口**：每个会话保存 AbortController，页面卸载时统一 abort。
- **Markdown 基础安全**：MarkdownIt 未开启原始 HTML，模型输出中的 HTML 默认被转义。
- **数据库连接策略**：ADK DatabaseSessionService 使用 NullPool，避免长期复用跨事件循环的数据库连接。

## 6. 待完善点与风险

以下优先级是后续处理建议，不代表本次已经运行复现。

### P0：先保证部署链路和流结束状态可用

#### 6.1 容器后端端口存在确定性不一致

- uWSGI 当前监听 **8001**，见 [uwsgi.ini](../backend/uwsgi.ini#L3)。
- Compose 把宿主机 8000 映射到容器 **8000**，见 [docker-compose.yml](../docker-compose.yml#L17-L18)。
- Nginx 也代理到 backend:**8000**，见 [nginx.conf](../frontend/nginx.conf#L14-L17)。

按这组配置直接启动容器，Nginx/端口映射访问的是容器 8000，而应用监听 8001。开发环境若绕过该容器链路另起服务，表现可能不同；部署联调时应先确认实际启动参数和监听端口。

#### 6.2 前端缺少“无 done 的 EOF”收尾

前端 Promise 只在网络异常时进入 `.catch()`；页面只在 `done`、`error` 或异常回调中调用 `finishReply`，没有在 Promise resolve 后统一清理，见[流式请求调用](../frontend/web/src/views/ai-assistant/index.vue#L315-L375)和[读取循环](../frontend/web/src/api/ai/index.ts#L138-L149)。

因此，如果连接正常 EOF，但服务端没有发出 `done`/`error`，可能出现：

- AI 气泡一直保持 loading；
- 当前会话一直被判定为流式中；
- AbortController 没有按正常结束路径清理。

需要把“收到业务结束事件”和“传输层流关闭”区分处理，并保证结束清理只执行一次。

### P1：补齐取消、异常、多会话和长连接语义

#### 6.3 取消/异常时，两套历史可能不完整

用户消息在流开始前已经落库，而助手消息只有收到 `done` 才落库，见[用户消息写入](../backend/ai_assistant/views.py#L38-L49)和[助手消息写入](../backend/ai_assistant/views.py#L94-L115)。

取消、网络断开、服务端异常或落库失败时可能出现：

- 业务库只有用户消息，没有助手消息或部分回答；
- ADK 已保存的事件与业务 ChatMessage 不一致；
- 页面显示的部分回答在刷新后消失；
- 助手落库失败只记录 warning，客户端仍可能看到正常 `done`，无法感知历史未保存。

后续需要先明确产品语义：取消后是保存部分回答、保存取消标记，还是整轮回滚；然后让 ADK 历史、业务历史和页面行为遵守同一约定。

#### 6.4 多会话后台流的页面状态并不完全独立

代码已经为每个会话保存消息数组和 AbortController，但以下状态仍是全局单值：

- `streamingSessionId` 只能表示一个流式会话；
- `streamStatus` 被所有会话的事件共同修改；
- `finishReply` 会无条件清空全局状态文案。

实现见[页面流式状态](../frontend/web/src/views/ai-assistant/index.vue#L156-L181)和[事件处理](../frontend/web/src/views/ai-assistant/index.vue#L292-L375)。

当两个会话先后发起请求时，可能出现 loading 只跟踪最后一个请求、后台请求修改当前状态文案、结束清理互相影响等问题。当前设计可靠支持的是“后台继续写一个数组”，还不等于完整的“多会话独立并发状态机”。

另有相关边界：

- 删除非当前但仍在流式输出的会话，不会走当前会话的中止和缓存清理分支。
- 历史请求尚未返回时就发送消息，历史响应可能替换当前消息列表，需要额外验证加载与流式更新之间的竞态。

#### 6.5 浏览器 abort 不等于服务端已完成取消

前端取消会中断 fetch 并立即清理页面状态，但后端没有显式的轮次取消协议，也没有取消状态落库。需要实际验证：

- uWSGI 关闭响应迭代后，ADK 异步生成器和上游模型请求是否及时停止；
- 工具调用是否可能继续执行；
- ADK Session 最终保存到哪一步；
- 部分回答是否需要保存。

对运维工具而言，这一点尤其重要：未来工具若具有写操作，不能只依赖浏览器消失来推断操作已取消。

#### 6.6 长连接部署参数需要专项验证

- uWSGI `harakiri = 60`，见 [uwsgi.ini](../backend/uwsgi.ini#L16)，长时间生成可能触及 60 秒请求限制。
- Nginx 没有为 SSE 单独设置读取超时，见 [nginx.conf](../frontend/nginx.conf#L14-L26)；同时当前没有 heartbeat，模型长时间无输出时需要验证代理空闲超时。
- 当前采用同步 WSGI + 每个请求自建事件循环的方式桥接 ADK 异步流，见 [services.py](../backend/ai_assistant/services.py#L72-L91)。每个进行中的流会长期占用同步 worker，四进程配置下并发容量有限。

已有 `X-Accel-Buffering: no` 是正确基础，但它不解决超时、worker 容量和服务端取消问题。

### P2：统一协议细节、历史体验和可维护性

#### 6.7 SSE 解析和类型契约仍可加强

- 后端强制要求 session_id，前端 `SendChatStreamOptions.sessionId` 却是可选字段；虽然页面会自动补建会话，但 API 类型允许构造出必然被后端拒绝的请求。
- 读取循环结束后没有再次 flush decoder、也没有 dispatch 缓冲区中的最后一帧；当前后端总是以双换行结尾，所以正常路径不受影响，但异常截断/其他服务端实现下缺少兜底。
- 分隔逻辑只识别 `\n\n`，没有兼容标准 SSE 中可能出现的 CRLF 分隔。
- 多行 `data:` 直接拼接而未补换行；当前后端单行 JSON 不受影响。
- `JSON.parse` 和 `onEvent` 在同一个 try/catch 中，页面回调自身抛错也会被记录成“帧解析失败”并跳过。
- 通用 SSE 模块只回调原始 chunk，并不负责协议拆帧；它与 AI API 的读取逻辑并存，后续需要明确复用边界，避免两套实现各自修补。

#### 6.8 认证和错误处理没有完全复用主请求链路

AI 会话接口使用独立 RequestClient，流式接口直接 fetch；二者都没有主请求客户端中的自动刷新 token 逻辑。当前 401 会作为普通 HTTP 错误抛出，并没有专门的重新登录引导。

此外，Runner 初始化位于异步迭代异常捕获范围之外；初始化失败是否转成 `error` 帧需要单独处理。直接把异常字符串前 200 字发给浏览器也应在后续统一错误码、日志与用户可见文案时重新评估。

#### 6.9 历史展示和会话列表还有一致性问题

- thinking 和 tool_calls 已保存，却在历史回放时丢弃；tool_response 的返回内容和 token 用量则没有保存。
- 前端新标题截断 20 字，后端截断 50 字，刷新前后可能不同。
- 后续消息只创建 ChatMessage，没有更新 ChatSession.updated_at；会话按 updated_at 排序，但不一定按最近对话时间移动。
- 删除业务会话会级联删除业务消息，但当前没有看到同步删除 ADK Session 的逻辑，可能遗留孤立的 ADK 历史。

#### 6.10 缺少这条业务链路的专项测试

后端测试文件仍是默认占位，见 [tests.py](../backend/ai_assistant/tests.py#L1-L3)。AI API 和页面目录下没有专项测试。框架通用 SSE 模块已有测试，见 [sse.test.ts](../frontend/packages/effects/request/src/request-client/modules/sse.test.ts#L42-L142)，但它验证的是原始 chunk 回调，不覆盖 AI 页面实际使用的 SSE 拆帧和页面状态。

## 7. 建议的后续完善顺序

1. **先建立可运行的联调基线**：统一容器端口，确认 ADK API Key/模型配置和 ADK Session 表初始化，再跑通普通文本与工具调用。
2. **定义单轮对话状态机**：明确 started、text/tool、done、error、cancelled、EOF 的关系；前后端都保证终态只处理一次，前端无论 resolve/reject 都能释放 loading。
3. **确定持久化与取消策略**：明确部分回答是否保存、业务库与 ADK 历史如何补偿、落库失败如何反馈；必要时为每轮增加 turn_id 和状态。
4. **把页面并发状态改为按会话/轮次隔离**：避免单一 streamingSessionId 和 streamStatus 互相覆盖，并处理删除、历史加载、快速切换等竞态。
5. **验证长连接基础设施**：覆盖超过 60 秒无输出、超过 60 秒总生成时间、代理解除缓冲、客户端断开后的服务端资源回收，再决定是否迁移到 ASGI。
6. **最后补解析、认证和测试**：统一 API 类型与后端契约，补 token 刷新/重登引导、严格拆帧、结构化错误以及自动化测试。

## 8. 后续联调最少覆盖的场景

| 场景 | 重点观察 |
| --- | --- |
| 普通文本，一次完整 done | 文本不丢、不重复；loading 和 controller 均清理；刷新后历史一致。 |
| 工具调用后回答 | 事件顺序、状态文案、工具记录和最终回答一致。 |
| 模型/ADK 抛错 | 客户端有明确终态；不永久 loading；日志和业务历史符合约定。 |
| 用户主动取消 | 浏览器与后端都停止；明确部分回答和工具操作的最终状态。 |
| 网络 EOF 但没有 done | 页面能恢复，不永久占用流式状态。 |
| 两个会话先后并发输出 | 文本、loading、状态文案、取消和删除互不影响。 |
| 快速切换会话及历史加载中发送 | 不串台，不被迟到的历史响应覆盖。 |
| 超过 60 秒无输出或总耗时超过 60 秒 | uWSGI、Nginx 和浏览器均不意外中断。 |
| token 过期 | 能刷新或明确引导重登，不出现难以定位的普通失败。 |
| 中文、Emoji、Markdown、跨 chunk/CRLF 帧 | 解码和解析正确，异常帧不影响后续状态清理。 |
| 删除有 ADK 历史的会话 | 业务数据和 ADK 数据的保留/清理策略一致。 |

## 9. 本次未做的验证

- 未安装或检查运行环境中的实际 ADK 依赖版本行为；
- 未验证真实模型是否支持 thinking、流式增量和工具事件的预期组合；
- 未验证 PostgreSQL 中 ADK Session 表的初始化情况；
- 未启动 uWSGI、Nginx 或前端，也未进行浏览器端 SSE 联调；
- 未修改上述业务、测试和部署代码。
