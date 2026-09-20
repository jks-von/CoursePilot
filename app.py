"""
课程智航 CoursePilot —— Streamlit 主入口。

页面结构：
1. 【课程资料】上传 / 使用内置 Demo 资料
2. 【学习目标】输入自然语言任务
3. 【开始执行】触发 Agent，实时展示执行轨迹
4. 【任务结果】展示对应 Tool 的输出
"""

import time

import streamlit as st

from agent import router
from document import parser
from utils import llm as llm_client

st.set_page_config(page_title="课程智航 CoursePilot", page_icon="🧭", layout="wide")

# ---------------------------------------------------------------------------
# Session State 初始化
# ---------------------------------------------------------------------------
for key, default in [
    ("doc_text", None),
    ("doc_sections", None),
    ("doc_name", None),
    ("task_input", ""),
    ("last_output", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def _load_text_as_doc(text: str, name: str):
    st.session_state["doc_text"] = text
    st.session_state["doc_name"] = name
    st.session_state["doc_sections"] = parser.split_into_sections(text)


def _fill_example(text: str):
    st.session_state["task_input"] = text


# ---------------------------------------------------------------------------
# 侧边栏：系统状态
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ 系统状态")
    if llm_client.is_configured():
        cfg = llm_client.get_config()
        st.success(f"大模型已配置\n\n模型：`{cfg['model']}`")
    else:
        st.warning("未配置大模型 API Key\n\n将自动降级为简化模式（关键词匹配 + 模板生成），"
                    "不影响 Demo 正常运行。")
    st.markdown("---")
    st.markdown("### 📖 使用说明")
    st.markdown(
        "1. 上传课程资料，或点击「使用内置演示资料」\n"
        "2. 用自然语言描述你的学习目标\n"
        "3. 点击「开始执行」，观察 Agent 的执行轨迹\n"
        "4. 查看 Agent 自主生成的结果"
    )

# ---------------------------------------------------------------------------
# 头部
# ---------------------------------------------------------------------------
st.title("🧭 课程智航 CoursePilot")
st.caption("基于智能体的自主学习规划与执行系统")
st.divider()

# ---------------------------------------------------------------------------
# 1. 课程资料
# ---------------------------------------------------------------------------
st.subheader("【课程资料】")
upload_col, demo_col = st.columns([3, 1])

with upload_col:
    uploaded = st.file_uploader(
        "上传 PDF / TXT / Markdown 课程资料",
        type=["pdf", "txt", "md", "markdown"],
        key="uploader",
    )
with demo_col:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    use_demo = st.button("📎 使用内置演示资料", use_container_width=True)

if uploaded is not None:
    text, err = parser.parse_uploaded_file(uploaded)
    if err:
        st.error(err)
    else:
        _load_text_as_doc(text, uploaded.name)

if use_demo:
    _load_text_as_doc(parser.load_demo_course(), "demo_course.md（内置演示：计算机网络课程资料）")

if st.session_state["doc_text"]:
    sections = st.session_state["doc_sections"]
    st.success(
        f"已加载课程资料：**{st.session_state['doc_name']}** "
        f"（共 {len(st.session_state['doc_text'])} 字，识别到 {len(sections)} 个章节）"
    )
    with st.expander("查看已识别的章节目录"):
        st.write(" ／ ".join(s["title"] for s in sections))
else:
    st.info("请上传课程资料，或点击「使用内置演示资料」体验 Demo。")

st.divider()

# ---------------------------------------------------------------------------
# 2. 学习目标
# ---------------------------------------------------------------------------
st.subheader("【学习目标】")
st.text_area(
    "请输入你的任务……",
    key="task_input",
    height=90,
    placeholder="例如：根据这份计算机网络课程资料，帮我制定今晚的考试复习计划，并告诉我最应该优先复习哪些内容。",
)

st.caption("快速体验（点击自动填充示例任务）：")
ex_col1, ex_col2, ex_col3 = st.columns(3)
with ex_col1:
    st.button(
        "📅 生成复习计划",
        use_container_width=True,
        on_click=_fill_example,
        args=("根据这份计算机网络课程资料，帮我制定今晚的考试复习计划，并告诉我最应该优先复习哪些内容。",),
    )
with ex_col2:
    st.button(
        "📝 生成练习题",
        use_container_width=True,
        on_click=_fill_example,
        args=("根据 TCP/IP 这一章生成5道选择题，并给出答案和解析。",),
    )
with ex_col3:
    st.button(
        "🔎 知识点问答",
        use_container_width=True,
        on_click=_fill_example,
        args=("解释 TCP 三次握手，并指出课程资料中最重要的考试知识点。",),
    )

st.divider()

# ---------------------------------------------------------------------------
# 3. 开始执行
# ---------------------------------------------------------------------------
start = st.button("🚀 开始执行", type="primary", use_container_width=True)

if start:
    doc_text = st.session_state["doc_text"]
    task = (st.session_state.get("task_input") or "").strip()

    if not doc_text:
        st.warning("请先上传课程资料，或点击「使用内置演示资料」。")
    elif not task:
        st.warning("请输入你的学习目标/任务。")
    else:
        sections = st.session_state["doc_sections"]

        st.subheader("Agent 执行过程")
        trace_placeholder = st.empty()
        trace_lines = []

        def on_step(message: str):
            trace_lines.append(message)
            trace_placeholder.markdown("\n\n".join(f"✅ {m}" for m in trace_lines))
            time.sleep(0.2)  # 仅用于现场演示的节奏感，不影响真实执行逻辑

        output = router.run_agent(task, sections, on_step=on_step)
        st.session_state["last_output"] = output

# ---------------------------------------------------------------------------
# 4. 任务结果
# ---------------------------------------------------------------------------
output = st.session_state.get("last_output")
if output:
    st.divider()
    tool = output["tool"]
    reason = output["tool_reason"]
    result = output["result"]

    st.markdown(
        f"**Agent 状态**：任务已完成 &nbsp;|&nbsp; **选择的 Tool**：`{tool}` &nbsp;|&nbsp; **选择依据**：{reason}"
    )

    st.subheader("【任务结果】")

    if tool == "document_search":
        st.markdown(result.get("answer", ""))
        with st.expander(f"参考章节：{', '.join(result.get('sources', [])) or '无'}"):
            st.text(result.get("context_used", ""))

    elif tool == "study_plan":
        st.markdown(result.get("plan_text", ""))
        st.caption(f"涉及主题：{', '.join(result.get('topics', [])) or '无'}")

    elif tool == "quiz_generator":
        if result.get("parse_failed"):
            st.warning("大模型返回内容未能解析为结构化题目，已展示原始文本：")
            st.markdown(result.get("raw_text", ""))
        else:
            questions = result.get("questions", [])
            if not questions:
                st.warning("未能生成题目，可能是课程资料内容过少，请尝试更换/补充资料。")
            for idx, q in enumerate(questions, start=1):
                st.markdown(f"**第 {idx} 题：** {q.get('question', '')}")
                options = q.get("options", {})
                for k in sorted(options.keys()):
                    st.markdown(f"- {k}. {options[k]}")
                with st.expander("查看答案与解析"):
                    st.markdown(f"**正确答案：{q.get('answer', '')}**")
                    st.markdown(q.get("explanation", ""))
                st.markdown("---")
        st.caption(f"出题范围：{', '.join(result.get('sources', [])) or '无'}")

    if result.get("llm_used"):
        st.caption("✨ 本次结果由大模型基于课程资料生成")
    else:
        st.caption("⚙️ 当前为简化模式结果（未配置大模型 Key 或调用失败），已基于原文自动降级生成，不影响流程演示")
