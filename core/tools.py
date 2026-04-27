def calculator(expression: str) -> str:
    """
    计算数学表达式的值。
    参数:
        expression: 字符串格式的数学表达式，例如 "123 * 456" 或 "(15 + 20) / 5"
    返回:
        计算结果的字符串。
    """
    try:
        # 使用 Python 内置的 eval 函数来执行字符串表达式
        # ⚠️ 注意：在真实的公开生产环境中，直接 eval 用户输入的字符串是不安全的，
        result = eval(expression)
        return str(result)
    except Exception as e:
        # 如果大模型给的数学公式格式不对，返回错误信息，让它知道自己算错了
        return f"计算错误，请检查表达式格式: {e}"

# 建立一个工具字典，方便后续代码通过字符串名字来调用对应的函数
AVAILABLE_TOOLS = {
    "calculator": calculator
}