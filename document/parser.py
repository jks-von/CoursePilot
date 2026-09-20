"""
课程资料解析模块。

负责把用户上传的 PDF / TXT / Markdown 文件转换成纯文本，
并把文本按章节（Markdown 标题）切分，供 Agent 的各个 Tool 使用。
"""

import os
import re
from typing import List, Dict, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_FILE_PATH = os.path.join(BASE_DIR, "data", "demo_course.md")


def _decode_bytes(data: bytes) -> str:
    """尝试用常见编码解码文本内容，优先 UTF-8，其次 GBK。"""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # 最后兜底，忽略无法解码的字节，保证不会崩溃
    return data.decode("utf-8", errors="ignore")


def _parse_pdf(data: bytes) -> Tuple[Optional[str], Optional[str]]:
    """解析 PDF 字节内容，返回 (文本, 错误信息)。"""
    try:
        from pypdf import PdfReader
        from io import BytesIO
    except ImportError:
        return None, "缺少 pypdf 依赖，请先运行 pip install -r requirements.txt。"

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as e:
        return None, f"PDF 文件无法打开，可能已损坏或被加密：{e}"

    texts = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        texts.append(page_text)

    full_text = "\n".join(texts).strip()
    if not full_text:
        return None, "未能从该 PDF 中提取到文本内容，可能是扫描版/图片版 PDF。请改用文字版 PDF 或上传 TXT/Markdown。"

    return full_text, None


def parse_uploaded_file(uploaded_file) -> Tuple[Optional[str], Optional[str]]:
    """
    解析 Streamlit 的 UploadedFile 对象。

    返回 (文本内容, 错误信息)。成功时错误信息为 None，失败时文本内容为 None。
    """
    if uploaded_file is None:
        return None, "未选择任何文件。"

    filename = getattr(uploaded_file, "name", "")
    ext = os.path.splitext(filename)[1].lower()

    try:
        data = uploaded_file.getvalue()
    except AttributeError:
        data = uploaded_file.read()

    if not data:
        return None, "文件内容为空，请检查后重新上传。"

    if ext == ".pdf":
        return _parse_pdf(data)
    elif ext in (".txt", ".md", ".markdown"):
        text = _decode_bytes(data).strip()
        if not text:
            return None, "文件内容为空或无法解码，请检查文件编码（推荐 UTF-8）。"
        return text, None
    else:
        return None, f"不支持的文件类型：{ext or '未知'}，请上传 PDF / TXT / Markdown 文件。"


def load_demo_course() -> str:
    """加载内置的演示课程资料。"""
    with open(DEMO_FILE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def split_into_sections(text: str) -> List[Dict[str, str]]:
    """
    将课程资料按 Markdown 标题（## / ### / ####）切分为若干章节。

    一级标题（#）视为文档总标题，不单独成章，避免"标题+简介"污染章节列表。
    若文本中没有任何标题（例如从 PDF/TXT 提取出的纯文本），
    则退化为按空行分段，每段生成一个编号标题，保证后续检索/出题逻辑仍然可用。
    """
    lines = text.splitlines()
    # 仅以 ## 及以下级别作为章节分界，一级标题（#）视为文档总标题，不单独成章
    heading_pattern = re.compile(r"^(#{2,4})\s+(.*)")
    doc_title_pattern = re.compile(r"^#\s+(.*)")

    sections: List[Dict[str, str]] = []
    current_title = None
    current_lines: List[str] = []
    has_heading = any(heading_pattern.match(line) for line in lines)

    if has_heading:
        for line in lines:
            if doc_title_pattern.match(line):
                continue
            match = heading_pattern.match(line)
            if match:
                if current_title is not None and current_lines:
                    sections.append({
                        "title": current_title,
                        "content": "\n".join(current_lines).strip(),
                    })
                elif current_title is None and current_lines:
                    # 标题之前的内容归入"概述"
                    sections.append({
                        "title": "概述",
                        "content": "\n".join(current_lines).strip(),
                    })
                current_title = match.group(2).strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_title is not None and current_lines:
            sections.append({
                "title": current_title,
                "content": "\n".join(current_lines).strip(),
            })
    else:
        # 没有标题：按连续空行分段
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            paragraphs = [text.strip()] if text.strip() else []
        for idx, para in enumerate(paragraphs, start=1):
            sections.append({"title": f"片段 {idx}", "content": para})

    # 过滤空章节
    sections = [s for s in sections if s["content"]]
    if not sections:
        sections = [{"title": "全文", "content": text.strip()}]
    return sections
