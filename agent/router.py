"""
Agent Router：负责判断用户任务应该交给哪个 Tool 执行，并驱动整个执行流程。

判断方式采用「大模型分类 + 关键词规则兜底」的双保险策略：
- 优先让大模型阅读用户任务，判断属于 document_search / study_plan / quiz_generator
  三者之一，这是真正意义上的、由 Agent 自主完成的任务理解；
- 如果没有配置大模型，或者调用失败/返回不合法，则使用关键词规则兜底，
  保证 Router 在任何情况下都不会崩溃、也不会"卡住"。

run_agent() 是整个 Agent 的执行入口，产出的 trace 是代码真实运行过程中
逐步追加的日志，不是预先写死的文案。
"""

from typing import List, Dict, Callable, Optional, Tuple

from utils import llm as llm_client
from agent import tools

VALID_TOOLS = ("document_search", "study_plan", "quiz_generator")

_KEYWORD_RULES: List[Tuple[str, List[str]]] = [
    ("study_plan", ["复习计划", "学习计划", "复习安排", "备考", "时间安排", "安排一下",
                     "规划", "计划", "schedule", "plan"]),
    ("quiz_generator", ["选择题", "练习题", "出题", "测验", "考题", "quiz", "出5道",
                         "出五道", "生成题目", "生成.*题", "几道题"]),
]


def _rule_based_route(user_task: str) -> Tuple[str, str]:
    for tool, keywords in _KEYWORD_RULES:
        for kw in keywords:
            if kw and kw in user_task:
                return tool, f"关键词规则命中「{kw}」"
    return "document_search", "未命中关键词规则，默认使用资料检索/问答"


def select_tool(user_task: str) -> Tuple[str, str]:
    """判断用户任务应该使用哪个 Tool，返回 (tool_name, 判断依据说明)。"""
    if llm_client.is_configured():
        prompt = (
            "你是一个任务路由器，需要判断用户任务属于以下哪一种类型，只输出对应的英文标识符，"
            "不要输出任何其他文字：\n"
            "document_search：用户想查询/理解/解释课程资料中的某个知识点\n"
            "study_plan：用户想制定学习计划、复习安排或时间规划\n"
            "quiz_generator：用户想生成练习题、选择题或测验\n\n"
            f"用户任务：{user_task}\n\n"
            "请直接输出 document_search 或 study_plan 或 quiz_generator："
        )
        res = llm_client.chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=20)
        if res.success:
            answer = res.content.strip().lower()
            for tool in VALID_TOOLS:
                if tool in answer:
                    return tool, f"大模型判断该任务属于「{tool}」"
    # 大模型未配置 / 调用失败 / 返回不合法内容时，使用关键词规则兜底
    return _rule_based_route(user_task)


def run_agent(user_task: str, sections: List[Dict[str, str]],
              on_step: Optional[Callable[[str], None]] = None) -> Dict:
    """
    Agent 执行主流程。

    on_step: 每完成一步就会被调用一次，可用于 UI 实时展示执行轨迹。
    """
    trace: List[str] = []

    def emit(message: str):
        trace.append(message)
        if on_step:
            on_step(message)

    emit("接收到用户任务")
    emit("分析任务类型")

    tool, reason = select_tool(user_task)
    emit(f"选择 Tool：{tool}（{reason}）")

    if tool == "study_plan":
        result = tools.study_plan(user_task, sections)
    elif tool == "quiz_generator":
        result = tools.quiz_generator(user_task, sections, num=5)
    else:
        tool = "document_search"
        result = tools.document_search(user_task, sections)

    for message in result.get("detail_log", []):
        emit(message)

    emit("完成任务")

    return {
        "trace": trace,
        "tool": tool,
        "tool_reason": reason,
        "result": result,
    }
