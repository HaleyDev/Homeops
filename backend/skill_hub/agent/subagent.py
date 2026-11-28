from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm

from .tools import generate_skill_install_prompt, list_available_skills


def create_skill_hub_agent(model: BaseLlm) -> Agent:
    """创建只读的 Skill Hub 查询与安装提示语子 Agent。"""
    return Agent(
        name='skill_hub_assistant',
        model=model,
        description='查询 Skill Hub 可用 Agent Skills，并生成指定 Skill 的 HTTP 安装提示语。',
        instruction=(
            '你是 Skill Hub 子 Agent，负责查询可用 Agent Skills 和生成安装提示语，'
            '用中文简洁回答。\n'
            '用户询问有哪些 Skill，或询问 Skill 的描述、版本、标签和文件时，'
            '必须调用 list_available_skills，不得编造 Skill 或版本信息。\n'
            '用户要求安装、下载或生成提示语时，调用 generate_skill_install_prompt。'
            '用户未明确 Skill 名称时，先调用 list_available_skills 供其选择；'
            '不得替用户自行扩大安装范围。\n'
            '用户提供了 Skill 源地址时，将其作为 source_url 传入；未提供时留空，'
            '使用系统默认地址，不要编造源地址。\n'
            '生成成功后，在文本代码块中完整展示 prompt，不得省略安装命令、'
            'skills-lock.json 或 .gitignore 步骤。不要执行安装命令，也不要声称已经安装。\n'
            '如果工具返回 Skill 不存在，调用 list_available_skills 获取有效名称并告知用户。\n'
            '你只提供只读查询和提示语，不处理上传、编辑、发布或删除。'
        ),
        tools=[list_available_skills, generate_skill_install_prompt],
    )
