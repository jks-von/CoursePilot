"""
CoursePilot 基础测试。

覆盖：
- 文档解析（TXT / Markdown 章节切分）
- Agent Router 的任务分类（关键词兜底逻辑，不依赖真实 LLM）
- 三个 Tool 的基本调用（通过 monkeypatch 模拟 LLM 返回，避免依赖真实网络/Key）
"""

import json

from agent import router, tools
from document import parser
from utils import llm as llm_client


SAMPLE_MD = """# 计算机网络资料片段

## TCP/IP 协议族

TCP 是面向连接的可靠传输协议。UDP 是无连接的传输协议。

## TCP 三次握手

第一次握手客户端发送 SYN。第二次握手服务器回复 SYN+ACK。第三次握手客户端发送 ACK，连接建立。

## HTTP 协议

HTTP 是应用层协议，常见方法有 GET 和 POST，常见状态码有 200 和 404。
"""


# ---------------------------------------------------------------------------
# 文档解析测试
# ---------------------------------------------------------------------------

def test_split_into_sections_with_headings():
    sections = parser.split_into_sections(SAMPLE_MD)
    titles = [s["title"] for s in sections]
    assert "TCP/IP 协议族" in titles
    assert "TCP 三次握手" in titles
    assert "HTTP 协议" in titles
    assert all(s["content"] for s in sections)


def test_split_into_sections_without_headings():
    text = "第一段内容，没有任何标题。\n\n第二段内容，介绍另一个知识点。"
    sections = parser.split_into_sections(text)
    assert len(sections) == 2
    assert sections[0]["title"] == "片段 1"


def test_demo_course_loads_and_has_sections():
    text = parser.load_demo_course()
    assert "TCP" in text
    sections = parser.split_into_sections(text)
    assert len(sections) >= 4


def test_parse_uploaded_file_unsupported_type():
    class FakeUpload:
        name = "notes.docx"

        def getvalue(self):
            return b"whatever"

    text, err = parser.parse_uploaded_file(FakeUpload())
    assert text is None
    assert "不支持" in err


def test_parse_uploaded_file_txt_ok():
    class FakeUpload:
        name = "notes.txt"

        def getvalue(self):
            return "你好，课程智航".encode("utf-8")

    text, err = parser.parse_uploaded_file(FakeUpload())
    assert err is None
    assert "课程智航" in text


# ---------------------------------------------------------------------------
# Router 测试（未配置 LLM 时应自动走关键词兜底逻辑）
# ---------------------------------------------------------------------------

def test_router_rule_based_study_plan(monkeypatch):
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    tool, reason = router.select_tool("帮我制定今晚的复习计划")
    assert tool == "study_plan"


def test_router_rule_based_quiz(monkeypatch):
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    tool, reason = router.select_tool("根据第三章生成5道选择题")
    assert tool == "quiz_generator"


def test_router_rule_based_default_document_search(monkeypatch):
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    tool, reason = router.select_tool("解释一下 TCP 三次握手")
    assert tool == "document_search"


def test_router_uses_llm_classification_when_configured(monkeypatch):
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm_client, "chat",
        lambda messages, **kwargs: llm_client.LLMResult(success=True, content="quiz_generator"),
    )
    tool, reason = router.select_tool("随便说点什么")
    assert tool == "quiz_generator"
    assert "大模型" in reason


# ---------------------------------------------------------------------------
# Tool 测试
# ---------------------------------------------------------------------------

def _sections():
    return parser.split_into_sections(SAMPLE_MD)


def test_document_search_without_llm():
    result = tools.document_search("TCP 三次握手 是什么", _sections())
    assert "三次握手" in result["answer"] or result["sources"]
    assert result["llm_used"] is False


def test_document_search_with_mocked_llm(monkeypatch):
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm_client, "chat",
        lambda messages, **kwargs: llm_client.LLMResult(success=True, content="这是模拟的大模型回答。"),
    )
    result = tools.document_search("TCP 三次握手", _sections())
    assert result["llm_used"] is True
    assert result["answer"] == "这是模拟的大模型回答。"


def test_study_plan_fallback_without_llm():
    result = tools.study_plan("今晚复习", _sections())
    assert result["llm_used"] is False
    assert "复习计划" in result["plan_text"] or "模板" in result["plan_text"]
    assert len(result["topics"]) >= 3


def test_quiz_generator_fallback_without_llm():
    result = tools.quiz_generator("TCP/IP", _sections(), num=3)
    assert result["llm_used"] is False
    # 资料内容有限时可能生成不足 num 道题，但不应报错
    assert isinstance(result["questions"], list)


def test_quiz_generator_with_mocked_llm_json(monkeypatch):
    fake_questions = [
        {
            "question": "TCP 三次握手中，第几次握手时连接建立完成？",
            "options": {"A": "第一次", "B": "第二次", "C": "第三次", "D": "第四次"},
            "answer": "C",
            "explanation": "客户端发送 ACK 后双方进入 ESTABLISHED 状态。",
        }
    ]
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm_client, "chat",
        lambda messages, **kwargs: llm_client.LLMResult(success=True, content=json.dumps(fake_questions, ensure_ascii=False)),
    )
    result = tools.quiz_generator("TCP", _sections(), num=1)
    assert result["llm_used"] is True
    assert result["questions"][0]["answer"] == "C"


def test_llm_chat_without_api_key_returns_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    result = llm_client.chat([{"role": "user", "content": "hi"}])
    assert result.success is False
    assert "API_KEY" in result.error or "Key" in result.error
