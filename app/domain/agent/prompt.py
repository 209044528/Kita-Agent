DEFAULT_PERSONA_PROMPT = "你叫 Kita，逻辑型AI助手。风格简明，除非用户要求详细。回答须基于知识库。"


def build_react_instruction_prompt(tool_descriptions: str) -> str:
    """
    构建 ReAct 指令提示词

    Args:
        tool_descriptions: 工具描述字符串（由 ToolRegistry 生成）

    Returns:
        完整的 ReAct 指令提示词
    """
    base_instruction = """
【回复格式】每轮必须包含：
Thought: 思考过程
Action: 执行动作

【Action 两种格式】
- 调用工具：工具名(参数="值")
- 给答案：Finish[最终回答]（回答须基于知识库结果，写在方括号内）

示例：
Thought: 用户问Agent定义，应先查知识库。
Action: knowledge_search(query="Agent定义")

Thought: 知识库已返回内容。
Action: Finish[Agent是能感知环境、决策并执行动作的智能体。]
"""

    if tool_descriptions:
        return f"{tool_descriptions}\n{base_instruction}"
    else:
        return base_instruction