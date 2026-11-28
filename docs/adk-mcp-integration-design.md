# HomeOps ADK MCP 接入开发设计

> 文档状态：设计方案，尚未实施  
> 适用版本：`google-adk==2.11.0`  
> 范围：HomeOps 后端作为 MCP Client，通过 ADK `McpToolset` 使用外部 MCP Server 提供的工具。  
> 非目标：本文不要求把 HomeOps Agent 暴露为 MCP Server，也不在第一阶段实现 MCP 写操作、人工确认、进度通知和富 UI。

## 1. 背景与结论

HomeOps AI 助手当前通过 Google ADK Agent、LiteLLM 和自定义 Runner 提供服务，已有本地 Python 工具和知识库检索工具。接入 MCP 的目的，是以标准协议复用外部系统的查询和操作能力，避免为每个外部系统重复实现协议适配。

ADK 已提供 `McpToolset`，它承担 MCP 与 ADK Tool 之间的适配工作：

1. 连接 MCP Server；
2. 完成 MCP 初始化和 `tools/list`；
3. 将 MCP 工具描述与参数 schema 转换为 ADK 工具；
4. 模型选择工具后执行 MCP `call_tool`；
5. 将 MCP 返回值转换为 ADK `function_response`。

因此，第一阶段不需要自行开发 MCP 协议适配器。开发工作集中在依赖、连接配置、工具白名单、认证、错误处理和生命周期清理。

推荐第一阶段采用：

> 独立 MCP Server + Streamable HTTP + 系统级只读凭据 + 工具白名单 + 每轮创建并显式关闭 `McpToolset`。

## 2. 当前实现与接入差距

| 项目 | 当前状态 | 接入影响 |
| --- | --- | --- |
| Agent 定义 | `backend/ai_assistant/agent/agent.py` 中的 `create_agent()` 创建 Agent | `McpToolset` 可与本地函数工具一起加入 `Agent.tools` |
| 本地工具 | 已有 `get_server_status`、`list_knowledge_bases`、`knowledge_search` | 不需要为接入 MCP 而改写 |
| Runner | `backend/ai_assistant/services.py` 每轮重新创建模型、Agent 和 Runner | MCP 连接也需要按轮次管理，不能随意全局共享 |
| 异步桥接 | 每轮自建事件循环，结束前关闭 ADK 异步生成器和事件循环 | 必须在事件循环关闭前异步关闭 `McpToolset` |
| SSE | `TurnStreamCollector` 已处理通用 `function_call` 和 `function_response` | 普通 MCP Tools 可复用现有工具调用事件 |
| ADK 依赖 | 已安装 `google-adk==2.11.0` 和 `db`、`extensions` extras | 尚未安装 `mcp` extra |
| MCP SDK | 容器中未安装 `mcp`，导入 `MCPToolset` 会报 `ModuleNotFoundError` | 必须补依赖并重建镜像 |
| 容器运行时 | backend 基于 `python:3.13-slim`，未安装 Node.js/npx | 第一阶段不推荐使用 npx Stdio MCP Server |
| 模型 | 通过 LiteLLM 使用 OpenAI 兼容文本模型 | 实际模型必须支持 Function Calling 和工具调用后的继续生成 |

相关实现：

- [Agent 定义](../backend/ai_assistant/agent/agent.py)
- [Runner 与流式服务](../backend/ai_assistant/services.py)
- [ADK 事件收集](../backend/ai_assistant/streaming.py)
- [后端依赖](../backend/requirements.txt)
- [backend Dockerfile](../docker/backend/Dockerfile)

## 3. MCP 与本地 Tool 的边界

### 3.1 适合保留为本地 Tool 的能力

- 强依赖 Django ORM、HomeOps 权限和当前用户上下文的查询；
- 知识库列表与向量检索；
- 只需要被 HomeOps Agent 使用、逻辑简单且没有跨客户端复用需求的函数。

### 3.2 适合通过 MCP 接入的能力

- 已有标准 MCP Server 的外部系统；
- 多个 Agent、IDE 或其他 MCP Client 都需要复用的能力；
- 独立部署、独立鉴权和独立扩缩容的运维服务；
- 希望以统一工具协议管理的监控、资产管理、代码仓库等系统。

### 3.3 不应为了使用 MCP 而增加的包装

如果某个能力只是普通 HTTP API，并且只供当前 Agent 使用，可以直接封装为 ADK Function Tool。只有存在标准化、跨客户端复用或独立服务边界需求时，才有必要再为该 API 开发 MCP Server。

## 4. 目标架构

```text
浏览器
  └─ POST /api/ai/chat/ + SSE
       └─ Django 流式视图
            └─ ADK Runner
                 └─ LiteLLM / OpenAI 兼容模型
                      ├─ 本地 Function Tools
                      │    ├─ get_server_status
                      │    ├─ list_knowledge_bases
                      │    └─ knowledge_search
                      └─ McpToolset
                           └─ Streamable HTTP
                                └─ 外部 MCP Server
                                     ├─ 资产查询
                                     ├─ 监控查询
                                     └─ 其他白名单工具
```

一次典型 MCP 工具调用流程：

```text
用户提问
  → Agent 获取本地工具和 MCP 工具声明
  → 模型生成 function_call
  → ADK 路由到 McpToolset
  → McpToolset 执行 MCP call_tool
  → MCP Server 返回结果
  → ADK 生成 function_response
  → 现有 SSE 发送 tool_call/tool_response
  → 模型根据工具结果生成最终回答
  → 关闭 ADK 异步生成器、McpToolset 和本轮事件循环
```

MCP 接入发生在 ADK 工具层，不直接接入前端，也不要求模型供应商原生理解 MCP 协议。

## 5. 传输方式选择

| 传输方式 | 适用场景 | 当前决策 |
| --- | --- | --- |
| Streamable HTTP | 独立容器、远程服务、内网 MCP 服务 | 第一阶段默认方式 |
| SSE | 仅支持旧版 MCP SSE 传输的服务 | 仅在目标 Server 要求时兼容 |
| Stdio | backend 启动本地子进程，通过标准输入输出通信 | 用于本地开发或有明确子进程需求时 |

### 5.1 Streamable HTTP 注意事项

- URL 必须从 backend 容器可达；容器内的 `localhost` 指向 backend 容器自身。
- MCP Server 作为独立 Compose 服务时，应使用 Compose 服务名和容器端口。
- 应配置连接超时和读取超时，避免工具调用无限等待。
- 认证信息通过安全配置注入，不写入代码、Agent instruction 或前端。

### 5.2 Stdio 注意事项

Stdio 不是连接另一个已经运行的容器，而是 backend 自己启动 MCP Server 子进程。因此：

- npx 形式要求 backend 镜像安装 Node.js 和 npx；
- Python 包形式要求将对应包安装进 backend 镜像；
- 文件路径按 backend 容器文件系统解释；
- 每个 uWSGI worker 可能产生不同子进程；
- 必须验证异常、取消和 worker 退出时的子进程回收。

## 6. 依赖与配置设计

### 6.1 Python 依赖

现有 ADK extras 需要保留，并增加 `mcp`：

```text
google-adk[db,extensions,mcp]==2.11.0
```

ADK 2.11.0 的 MCP extra 声明了 `mcp>=1.24,<3`。依赖变更后需要重新构建 backend 镜像，仅重启容器不会安装新依赖。

### 6.2 第一阶段配置项

以下是建议新增的配置，不表示当前代码已经支持：

| 配置 | 必填 | 说明 |
| --- | --- | --- |
| `MCP_ENABLED` | 否 | 总开关，默认关闭，保证未配置时现有对话行为不变 |
| `MCP_SERVER_URL` | 启用时必填 | Streamable HTTP MCP 地址 |
| `MCP_AUTH_TOKEN` | 按 Server 要求 | 系统级 Bearer Token，只注入 backend |
| `MCP_TIMEOUT_SECONDS` | 否 | 建立连接和请求超时，建议从较小值开始 |
| `MCP_SSE_READ_TIMEOUT_SECONDS` | 否 | 流式读取超时 |
| `MCP_TOOL_FILTER` | 启用时必填 | 允许暴露给模型的工具白名单 |
| `MCP_TOOL_NAME_PREFIX` | 否 | 工具名前缀，用于避免与本地工具或其他 Server 重名 |

第一阶段只支持一个静态 MCP Server。多 Server、数据库化配置和动态用户授权均不在最小接入范围内。

## 7. McpToolset 使用示例

以下示例用于说明接入方式，不代表已经完成项目接入。工具名称必须替换为目标 MCP Server 实际通过 `tools/list` 返回的名称。

```python
import os

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)


mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=os.environ["MCP_SERVER_URL"],
        headers={
            "Authorization": f"Bearer {os.environ['MCP_AUTH_TOKEN']}",
        },
        timeout=5,
        sse_read_timeout=300,
    ),
    tool_filter=["list_servers", "query_metrics"],
    tool_name_prefix="ops_",
)
```

将其与现有本地工具一起注册：

```python
agent = Agent(
    name="homeops_assistant",
    model=model,
    instruction=instruction,
    tools=[
        get_server_status,
        list_knowledge_bases,
        knowledge_search,
        mcp_toolset,
    ],
)
```

假设 Server 提供 `list_servers`、`query_metrics` 和 `restart_server`，上述配置只会把前两个工具暴露给模型，并以 `ops_list_servers`、`ops_query_metrics` 命名。`restart_server` 不会进入模型工具列表。

`McpToolset` 构造时通常不会立即连接 Server；第一次获取工具列表或执行工具时才建立 MCP Session。因此配置错误可能在运行时才暴露，联调必须覆盖首次工具发现和首次调用。

## 8. 生命周期设计

### 8.1 当前项目的关键约束

当前服务每轮创建新的 Agent 和 Runner，并为同步 WSGI 请求创建独立事件循环。如果只在 `create_agent()` 中创建 `McpToolset`，却不把清理句柄交给服务层，就容易出现连接或子进程无法显式回收的问题。

### 8.2 第一阶段生命周期策略

采用每轮独立 Toolset：

1. 本轮 Runner 初始化时同步创建 `McpToolset`；
2. 服务层保存本轮 Toolset 引用；
3. 在同一事件循环中执行 ADK 事件流；
4. 正常完成、模型异常、MCP 异常或客户端取消时进入统一清理路径；
5. 先关闭 ADK 异步生成器，确保没有仍在执行的工具调用；
6. 执行 `await mcp_toolset.close()`；
7. 最后关闭本轮事件循环。

清理代码应使用嵌套 `finally` 或等价机制，保证前一步清理失败不会跳过后续资源释放。清理异常应记录日志，但不能向客户端泄露地址、Token 或内部堆栈。

### 8.3 禁止的第一阶段做法

- 只创建 Toolset，不提供关闭路径；
- 在事件循环已经关闭后再调用 `close()`；
- 默认把同一个 Toolset 全局共享给不同请求的独立事件循环；
- 假设浏览器 abort 会自动完成后端 MCP 清理；
- 为减少连接次数而在没有并发验证前直接引入跨请求连接池。

后续若需要复用连接，应单独设计事件循环亲和性、并发隔离、用户身份隔离、缓存失效和进程退出清理。

## 9. SSE 与前端影响

### 9.1 第一阶段无需新增协议

MCP 工具经 ADK 转换后仍表现为标准 `function_call` 和 `function_response`。当前链路已经能够处理：

- 工具名称；
- 调用参数；
- 调用状态；
- 工具结果；
- 工具调用后的最终文本。

因此，普通只读 MCP Tools 第一阶段不需要新增 SSE 事件类型，也不需要修改前端消息结构。

### 9.2 后续高级能力需要单独设计

以下能力不能直接视为已有支持：

- `require_confirmation` 对应的人工确认与继续执行；
- `progress_callback` 对应的实时进度事件；
- elicitation 对应的用户交互；
- MCP UI Resource 对应的前端富组件；
- OAuth 授权跳转与回调。

实现这些能力前，应先扩展单轮对话状态机、SSE 协议、持久化语义和前端交互，而不是只增加 ADK 参数。

## 10. 认证、权限与安全

### 10.1 工具暴露

- 生产环境必须配置明确的 `tool_filter`；
- 第一阶段只开放只读、低风险和结果可审计的工具；
- 多 Server 或可能重名时使用 `tool_name_prefix`；
- 不因为 Server 提供某个工具，就默认允许模型使用它。

### 10.2 用户身份

- 用户身份必须来自后端认证上下文；
- 不允许模型通过参数自行声明 `user_id` 或提升权限；
- 第一阶段只使用系统级只读凭据；
- 后续用户级动态 Token 可使用 `header_provider`，但需要验证用户状态注入和跨请求隔离；
- MCP Server 必须再次执行服务端权限校验，不能只依赖 Agent instruction。

### 10.3 不可信内容

MCP 返回内容属于不可信外部数据。返回文本中的指令不得覆盖系统指令、Agent instruction 或安全策略。Agent 应把工具结果当作事实材料，而不是新的高优先级命令。

### 10.4 写操作

重启、删除、修改配置、执行 Shell 和数据库变更等写操作不进入第一阶段。后续开放前必须同时具备：

- 明确的服务端权限校验；
- 参数校验与目标资源限制；
- 用户确认交互；
- 审计日志；
- 幂等、超时与取消语义；
- 失败补偿或明确的部分完成状态。

## 11. 错误处理与可观测性

至少需要区分：

- MCP Server 不可达；
- 连接或读取超时；
- 认证失败；
- `tools/list` 失败；
- 工具不存在或 schema 不兼容；
- `call_tool` 返回错误；
- 模型不支持或没有正确生成工具调用；
- 客户端取消后的清理失败。

后端日志应记录 Server 标识、工具名、耗时、结果状态和异常类型，不记录 Token、完整认证头或不必要的敏感参数。客户端继续使用安全的通用错误信息，不直接透传内部堆栈。

普通工具失败应尽量让模型收到可理解的失败结果并说明无法完成，而不是生成虚构成功结果。连接初始化失败则需要确保本轮流能够终止并释放资源。

## 12. 建议实施步骤

1. 确定一个只读 MCP Server、传输方式、实际工具列表和认证方式。
2. 为 ADK 增加 `mcp` extra，重建 backend 镜像并验证导入。
3. 增加 MCP 总开关和最小连接配置，默认保持关闭。
4. 创建单个 `McpToolset`，配置白名单、名称前缀和超时。
5. 将 Toolset 注册到现有 `Agent.tools`，保留所有本地工具。
6. 调整本轮运行时对象的持有方式，使服务层能够关闭 Toolset。
7. 在正常、异常和取消路径中完成生成器、Toolset、事件循环的顺序清理。
8. 根据实际 MCP 工具补充最小 Agent instruction，不堆叠重复规则。
9. 完成后端测试和真实 MCP/模型联调后，再默认启用。
10. 单独评估多 Server、Resources、用户级认证和写操作。

## 13. 测试与验收

### 13.1 自动化测试

- MCP 关闭或未配置时，现有 Agent 工具和对话测试不变；
- 配置完整时，Toolset 使用正确 URL、超时、白名单和前缀；
- 配置缺失时不会静默暴露全部工具；
- 工具发现失败、调用失败和超时能够进入明确终态；
- 正常完成、异常和取消都调用一次异步清理；
- Toolset 在事件循环关闭前清理；
- 日志不包含 Token 和敏感请求头；
- 现有 SSE 收集器能够处理 MCP 产生的通用工具事件。

### 13.2 真实联调

- backend 容器可以连接 MCP Server；
- `tools/list` 返回结果与白名单一致；
- 普通聊天不会误调用 MCP；
- 匹配的问题能够选择正确工具并传递正确参数；
- 工具结果能够触发后续最终回答；
- 当前 LiteLLM 模型支持完整 Function Calling 流程；
- Server 不可用或超时时，客户端不会永久等待；
- 多轮对话后没有持续增长的连接或子进程；
- 浏览器取消后，后端能够完成取消与资源清理；
- 两个并发会话不会混用 MCP 身份、连接或结果。

## 14. 后续扩展

以下能力应在最小只读链路稳定后分别设计：

- 多 MCP Server 与工具命名空间；
- `tool_list_cache_ttl_seconds` 和跨轮工具发现优化；
- `use_mcp_resources=True`、`list_resources()` 和 `read_resource()`；
- 用户级 `header_provider` 和 OAuth；
- `require_confirmation` 人工确认；
- `progress_callback` 长任务进度；
- sampling、elicitation 和富 UI；
- 跨请求连接复用及统一异步运行时。

## 15. 参考资料

- [ADK Model Context Protocol tools](https://adk.dev/tools-custom/mcp-tools/)
- [ADK Advanced MCP configuration](https://adk.dev/tools-custom/mcp-tools/advanced/)
- [HomeOps ADK Skill 接入开发设计](./adk-skills-integration-design.md)
- [HomeOps ADK 与 SSE 对话现状](./adk-sse-chat-current-state.md)
