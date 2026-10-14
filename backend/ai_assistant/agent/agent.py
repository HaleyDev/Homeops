import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

# ============================ CONFIG ============================
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
MODEL_NAME = os.getenv("ADK_MODEL_NAME", "openai/glm-5.3-flash")
BASE_URL = os.getenv("ADK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
API_KEY = os.getenv("ADK_API_KEY", "")
# ================================================================


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
         "error_message": f"未知服务器: {server_name}，可选: backend / db / elasticsearch"},
    )


root_agent = Agent(
    name="homeops_assistant",
    model=LiteLlm(model=MODEL_NAME, api_key=API_KEY, base_url=BASE_URL),
    description="HomeOps 内网运维平台的演示助手",
    instruction=(
        "你是 HomeOps 内网运维平台的助手，用中文简洁回答。\n"
        "当用户询问服务器状态时，必须调用 get_server_status 工具查询，不要编造数据。\n"
        "用户问的服务器不在支持列表时，告知可选: backend / db / elasticsearch。"
    ),
    tools=[get_server_status],
)
