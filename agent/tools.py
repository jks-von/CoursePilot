"""
Agent 可调用的三个 Tool：

- document_search  在课程资料中检索并回答问题
- study_plan       基于课程资料生成复习计划
- quiz_generator   基于课程资料生成选择题

每个 Tool 都遵循同一套设计：
1. 先用简单的关键词匹配从课程资料中找到相关章节（不依赖向量数据库）；
2. 如果配置了大模型，则把检索到的原文片段作为上下文交给大模型生成结果；
3. 如果没有配置大模型，或大模型调用失败，都会自动降级为基于原文的
   简化处理方式，保证现场演示不会因为网络/Key 问题而中断；
4. 返回结果中附带 detail_log，记录该 Tool 内部真实执行的步骤，
   用于在 UI 上展示 Agent 的执行轨迹。
"""

import json
import random
import re
from typing import List, Dict, Optional, Tuple

from utils import llm as llm_client

MAX_CONTEXT_CHARS = 3000

_STOPWORDS = {
    "的", "了", "吗", "呢", "是", "在", "和", "与", "请", "帮", "我", "这份",
    "根据", "并", "给出", "生成", "关于", "对于", "有关", "一下", "帮我",
    "今晚", "今天", "这个", "那个", "内容", "资料", "课程",
}


def _extract_keywords(text: str) -> List[str]:
    """从用户输入中提取用于匹配的关键词（中文按词/2-gram，英文按单词）。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    tokens: List[str] = []
    for word in cleaned.split():
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            tokens.append(word)
            for i in range(len(word) - 1):
                bigram = word[i:i + 2]
                if bigram not in _STOPWORDS:
                    tokens.append(bigram)
        else:
            tokens.append(word.lower())
    return [t for t in tokens if t and t not in _STOPWORDS]


def _score_section(section: Dict[str, str], keywords: List[str]) -> int:
    # 统一转小写，避免英文关键词（如 tcp）因大小写不一致（TCP）而匹配不到
    haystack = (section["title"] * 2 + " " + section["content"]).lower()
    score = 0
    for kw in keywords:
        weight = 2 if len(kw) >= 2 else 1
        score += haystack.count(kw) * weight
    return score


def _title_matches_hint(title: str, hint: str) -> bool:
    """判断章节标题是否与用户提到的主题/章节名相关（大小写不敏感，支持标题内的子词匹配）。"""
    title_l, hint_l = title.lower(), hint.lower()
    if title_l in hint_l or hint_l in title_l:
        return True
    for chunk in re.split(r"[\s/、，,]+", title):
        chunk = chunk.strip()
        if len(chunk) >= 2 and chunk.lower() in hint_l:
            return True
    return False


def search_relevant_sections(query: str, sections: List[Dict[str, str]], top_k: int = 3) -> List[Dict[str, str]]:
    """根据关键词匹配，从章节列表中找出最相关的若干章节。"""
    keywords = _extract_keywords(query)
    scored = [(_score_section(s, keywords), s) for s in sections]
    scored.sort(key=lambda x: x[0], reverse=True)
    matched = [s for score, s in scored if score > 0][:top_k]
    if not matched:
        matched = sections[:top_k] if sections else []
    return matched


def _build_context(sections: List[Dict[str, str]]) -> str:
    context = "\n\n".join(f"【{s['title']}】\n{s['content']}" for s in sections)
    return context[:MAX_CONTEXT_CHARS]


# ---------------------------------------------------------------------------
# Tool 1: document_search
# ---------------------------------------------------------------------------

def document_search(query: str, sections: List[Dict[str, str]]) -> Dict:
    log = []
    matched = search_relevant_sections(query, sections, top_k=3)
    log.append(f"检索课程资料，匹配到 {len(matched)} 个相关章节：{', '.join(s['title'] for s in matched)}")

    context = _build_context(matched)
    log.append(f"获取相关课程内容，提取上下文约 {len(context)} 字")

    result = {
        "sources": [s["title"] for s in matched],
        "context_used": context,
        "llm_used": False,
    }

    if llm_client.is_configured():
        prompt = (
            "你是一名课程助教。请仅根据下面提供的【课程资料片段】回答学生的问题，"
            "不要编造资料中不存在的信息。回答时请说明依据的章节名称，并在末尾单独用一行"
            "指出\u201c课程资料中最重要的相关考点\u201d。\n\n"
            f"【课程资料片段】\n{context}\n\n【学生问题】\n{query}"
        )
        res = llm_client.chat([{"role": "user", "content": prompt}])
        if res.success:
            result["answer"] = res.content
            result["llm_used"] = True
            log.append("调用大模型生成结果：已基于检索到的资料生成回答")
        else:
            result["answer"] = f"（大模型调用失败：{res.error}，已降级为直接展示匹配到的原文片段）\n\n{context}"
            log.append(f"大模型调用失败，已降级为原文展示：{res.error}")
    else:
        result["answer"] = f"（未配置大模型 API Key，已使用简化模式直接展示匹配到的原文片段）\n\n{context}"
        log.append("未配置大模型 API Key，使用简化模式直接展示原文片段")

    result["detail_log"] = log
    return result


# ---------------------------------------------------------------------------
# Tool 2: study_plan
# ---------------------------------------------------------------------------

def _fallback_plan(sections: List[Dict[str, str]], start_hour: int = 19, start_minute: int = 0,
                    total_minutes: int = 150) -> str:
    n = max(len(sections), 1)
    per = max(total_minutes // n, 15)
    minutes = start_hour * 60 + start_minute
    lines = ["**（未配置/调用大模型失败，以下为按章节均分时间的模板计划）**\n"]
    for s in sections:
        end = minutes + per
        lines.append(f"- {minutes // 60:02d}:{minutes % 60:02d}-{end // 60:02d}:{end % 60:02d}  {s['title']}")
        minutes = end
    lines.append(
        f"- {minutes // 60:02d}:{minutes % 60:02d}-{(minutes + 30) // 60:02d}:{(minutes + 30) % 60:02d}  综合练习与查漏补缺"
    )
    priority = "、".join(s["title"] for s in sections[:2]) if sections else "（无可用章节）"
    lines.append(f"\n**优先建议**：建议优先复习「{priority}」等章节（默认按资料章节顺序给出，仅供参考）。")
    return "\n".join(lines)


def study_plan(goal: str, sections: List[Dict[str, str]]) -> Dict:
    log = []
    topics = [s["title"] for s in sections]
    log.append(f"检索课程资料，提取到 {len(topics)} 个课程主题：{', '.join(topics)}")

    brief = "\n".join(f"- {s['title']}：{s['content'][:120].strip()}" for s in sections)
    log.append("获取相关课程内容，整理章节大纲用于生成计划")

    result = {
        "topics": topics,
        "llm_used": False,
    }

    if llm_client.is_configured():
        prompt = (
            "你是一名学习规划助手。请严格根据下面的【课程资料大纲】，为学生制定一份具体的复习计划，"
            f"学生的目标是：\u201c{goal}\u201d。\n"
            "要求：\n"
            "1. 给出带具体时间段的时间表（例如 19:00-19:40 ...），覆盖资料中的主要主题；\n"
            "2. 明确指出最应该优先复习的1-3个主题，并说明理由；\n"
            "3. 只使用资料中出现的主题名称，不要编造资料之外的内容；\n"
            "4. 用简洁的 Markdown 列表输出，不要输出多余的寒暄。\n\n"
            f"【课程资料大纲】\n{brief}"
        )
        res = llm_client.chat([{"role": "user", "content": prompt}])
        if res.success:
            result["plan_text"] = res.content
            result["llm_used"] = True
            log.append("调用大模型生成结果：已基于课程大纲生成复习计划")
        else:
            result["plan_text"] = _fallback_plan(sections) + f"\n\n（提示：大模型调用失败：{res.error}）"
            log.append(f"大模型调用失败，已降级为模板计划：{res.error}")
    else:
        result["plan_text"] = _fallback_plan(sections)
        log.append("未配置大模型 API Key，使用简化模式（按章节均分时间）生成复习计划")

    result["detail_log"] = log
    return result


# ---------------------------------------------------------------------------
# Tool 3: quiz_generator
# ---------------------------------------------------------------------------

def _extract_sentences(content: str) -> List[str]:
    raw = re.split(r"[。！？\n]", content)
    sentences = []
    for s in raw:
        s = s.strip(" -*#\t")
        if len(s) >= 8:
            sentences.append(s)
    return sentences


def _fallback_quiz(sections: List[Dict[str, str]], num: int) -> List[Dict]:
    """未配置大模型时，基于原文句子构造"哪项描述符合资料"的选择题。"""
    pool: List[Tuple[str, str]] = []
    for s in sections:
        for sent in _extract_sentences(s["content"]):
            pool.append((s["title"], sent))

    random.shuffle(pool)
    letters = ["A", "B", "C", "D"]
    questions = []
    used_sentences = set()

    for title, sent in pool:
        if len(questions) >= num:
            break
        if sent in used_sentences:
            continue
        distractor_candidates = [s2 for t2, s2 in pool if s2 != sent and s2 not in used_sentences]
        random.shuffle(distractor_candidates)
        distractors = distractor_candidates[:3]
        if len(distractors) < 3:
            continue
        used_sentences.add(sent)

        options_content = [sent] + distractors
        random.shuffle(options_content)
        correct_idx = options_content.index(sent)

        questions.append({
            "question": f"以下哪一项描述符合课程资料《{title}》章节的内容？",
            "options": {letters[i]: options_content[i] for i in range(len(options_content))},
            "answer": letters[correct_idx],
            "explanation": f"该表述出自资料原文《{title}》章节，其余选项来自其他章节内容，作为干扰项。",
        })

    return questions


def _parse_quiz_json(content: str) -> Tuple[Optional[List[Dict]], Optional[str]]:
    text = content.strip()
    text = re.sub(r"^```(json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, str(e)

    if isinstance(data, dict):
        data = data.get("questions", [])
    if isinstance(data, list) and data:
        return data, None
    return None, "解析结果为空列表"


def quiz_generator(topic_hint: str, sections: List[Dict[str, str]], num: int = 5) -> Dict:
    log = []

    matched = []
    if topic_hint:
        matched = [s for s in sections if _title_matches_hint(s["title"], topic_hint)]
    if not matched:
        matched = search_relevant_sections(topic_hint or "", sections, top_k=3)
    if not matched:
        matched = sections

    log.append(f"检索课程资料，确定出题范围：{', '.join(s['title'] for s in matched)}")
    context = _build_context(matched)
    log.append(f"获取相关课程内容，提取上下文约 {len(context)} 字，计划生成 {num} 道题")

    result = {
        "sources": [s["title"] for s in matched],
        "llm_used": False,
        "parse_failed": False,
    }

    if llm_client.is_configured():
        prompt = (
            f"你是一名出题老师。请严格根据下面的【课程资料】出 {num} 道单选题，"
            "不要编造资料中没有的知识点。请只输出一个 JSON 数组，不要输出任何多余文字、"
            "解释或代码块标记，数组每一项的格式为：\n"
            '{"question": "题干", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, '
            '"answer": "A", "explanation": "简要解析"}\n\n'
            f"【课程资料】\n{context}"
        )
        res = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.4)
        if res.success:
            questions, err = _parse_quiz_json(res.content)
            if questions:
                result["questions"] = questions
                result["llm_used"] = True
                log.append(f"调用大模型生成结果：已生成 {len(questions)} 道题目")
            else:
                result["questions"] = []
                result["parse_failed"] = True
                result["raw_text"] = res.content
                log.append(f"大模型返回内容解析失败，已展示原始文本（{err}）")
        else:
            result["questions"] = _fallback_quiz(matched, num)
            log.append(f"大模型调用失败，已降级为基于原文抽取的简化出题：{res.error}")
    else:
        result["questions"] = _fallback_quiz(matched, num)
        log.append("未配置大模型 API Key，使用简化模式（基于原文抽取）生成题目")

    result["detail_log"] = log
    return result
