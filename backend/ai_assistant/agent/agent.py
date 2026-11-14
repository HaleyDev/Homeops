from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from system_setting.services import EffectiveModelConfig


def get_server_status(server_name: str) -> dict:
    """查询一台内网服务器的运行状态（演示用 mock 数据）。

    Args:
        server_name: 服务器名称，例如 backend、db、elasticsearch

    Returns:
        dict: 包含 status 与服务器运行详情
    """
    mock = {
        "backend": {"status": "success", "state": "running",
                    "cpu": "35%", "memory": "62%", "uptime": "12d"},
        "db": {"status": "success", "state": "running",
               "cpu": "18%", "memory": "81%", "uptime": "40d"},
        "elasticsearch": {"status": "success", "state": "running",
                          "cpu": "55%", "memory": "77%", "uptime": "12d"},
    }
    return mock.get(
        server_name.lower(),
        {"status": "error",
         "error_message": f"Unknown server: {server_name}. Available servers: backend / db / elasticsearch"},
    )


def create_agent(config: EffectiveModelConfig) -> Agent:
    """Create an agent bound to one request's model configuration snapshot."""

    model_options = {**config.extra_config, **config.parameters}
    model = LiteLlm(
        model=f"openai/{config.model_key}",
        api_key=config.api_key,
        base_url=config.base_url,
        **model_options,
    )
    return Agent(
        name="homeops_assistant",
        model=model,
        description="HomeOps 内网运维平台的演示助手",
        instruction=(
            "你是 HomeOps 内网运维平台的助手，用中文简洁回答。\n"
            "当用户询问服务器状态时，必须调用 get_server_status 工具查询，不要编造数据。\n"
            "用户问的服务器不在支持列表时，告知可选: backend / db / elasticsearch。"
        ),
        tools=[get_server_status],
    )
