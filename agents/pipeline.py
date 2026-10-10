"""检索知识库后，由一个配队助手作答，并按标签和克制规则核对。"""
import json
import logging
import re

logger = logging.getLogger(__name__)
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

from agents.skill_text import extract_steps, load_skill
from config import DATA_DIR

TRACE_DIR = Path(DATA_DIR) / "agent_traces"
MAX_ROUNDS = 2


REFUSE_ANSWER = "在所有已上传的资料中均未检索到相关信息"


def _plain_text(page_content: str) -> str:
    text = (page_content or "").strip()
    if text.startswith("[citation:"):
        text = text.split("\n", 1)[-1].strip()
    return text


def snippets_from_docs(docs: List[Any]) -> List[Dict[str, Any]]:
    snippets = []
    seen = set()
    for doc in docs or []:
        source = doc.metadata.get("source") or doc.metadata.get("file_name") or "未知来源"
        page = doc.metadata.get("page", "")
        text = _plain_text(doc.page_content)
        if not text:
            continue
        key = f"{source}::{page}::{text[:80]}"
        if key in seen:
            continue
        seen.add(key)
        snippets.append({
            "id": len(snippets) + 1,
            "source": source,
            "page": page,
            "text": text,
        })
    return snippets


def _knowledge_vector_snippets(snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """配队只保留知识库向量片段。政策 PDF 不进入配队上下文。"""
    kept = []
    for item in snippets:
        source = str(item.get("source") or "").replace("\\", "/")
        if "knowledge/" in source or source.endswith("rules.md"):
            kept.append(item)
    return kept


def format_snippets(snippets: List[Dict[str, Any]]) -> str:
    blocks = []
    for item in snippets:
        page = item.get("page", "")
        page_info = f" (第{page}页)" if str(page) else ""
        blocks.append(
            f"[citation:{item['id']}] 文件: {item['source']}{page_info}\n{item['text']}"
        )
    return "\n\n".join(blocks)


def _llm_text(invoke: Callable, prompt: str) -> str:
    response = invoke(prompt)
    if hasattr(response, "content"):
        return str(response.content).strip()
    return str(response).strip()


def _history_text(history: List) -> str:
    lines = []
    for msg in (history or [])[-6:]:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        role = "用户" if msg.get("role") == "user" else "助手"
        lines.append(f"{role}：{content[:200]}")
    return "\n".join(lines)


def standalone_query(question: str, history: List, invoke: Callable) -> str:
    """检索员把追问收成独立查询。没有历史时直接用原问题。"""
    history_text = _history_text(history)
    if not history_text:
        return question.strip()
    prompt = (
        f"{load_skill('retriever')}\n\n"
        "根据检索员技能，把对话历史和最新问题收成一个独立检索查询。\n"
        "只输出查询词，不超过40个字，不要回答问题。\n\n"
        f"对话历史：\n{history_text}\n\n最新问题：\n{question.strip()}"
    )
    text = _llm_text(invoke, prompt).splitlines()[0].strip().strip("\"“”")
    if not text or len(text) > 80 or text.startswith("[citation:"):
        return question.strip()
    return text


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "是", "通过"}
    return bool(value)


def _parse_checker(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            return {
                "pass": _as_bool(data.get("pass")),
                "issues": [str(item) for item in data.get("issues") or []],
                "raw": text,
            }
        except json.JSONDecodeError:
            pass
    passed = bool(re.search(r'"pass"\s*:\s*true', text, re.IGNORECASE))
    return {"pass": passed, "issues": [] if passed else ["核对员没有返回可解析的 JSON"], "raw": text}


def _notebook_team_note(question: str, session_id: str) -> str:
    """名录里没有、但这句对话已经记下的精灵，直接用记下的资料讲配队思路。"""
    if re.search(r"以\s*.{1,16}?\s*为\s*(?:核心|主力)", question or ""):
        return ""
    if not re.search(r"配队|思路|怎么配|为核心|主力|出场", question or ""):
        return ""
    from agents.chat_notebook import recall_pages, style_sentence
    from agents.thoughts import note_read
    from pokemon_kb import _mentioned_names, load_pokemon

    pages = recall_pages(session_id, question)
    known = set(_mentioned_names(question, load_pokemon()))
    outside = [page for page in pages if page.get("name") not in known]
    if not outside:
        return ""
    from agents.chat_notebook import remember_page
    from knowledge_search import _card_is_thin, _wiki_lookup, outside_team_speech, present_outside_sprite

    parts = []
    for page in outside:
        label = page.get("name") or "记下的资料"
        note_read(label)
        card = present_outside_sprite(label, page.get("text") or "")
        if _card_is_thin(card):
            wiki = _wiki_lookup(label)
            if wiki:
                card = wiki["extract"]
                remember_page(session_id, label, card, [{"title": wiki["title"], "url": wiki["url"]}])
        elif card != (page.get("text") or ""):
            remember_page(session_id, label, card, page.get("sources") or [])
        parts.append(outside_team_speech(label, card))
    answer = "\n\n".join(parts)
    habit = style_sentence(session_id)
    if habit and habit not in answer:
        answer = answer.rstrip() + "\n\n" + habit
    return answer


def run_collaborative_agents(
    question: str,
    on_progress: Callable = None,
    session_id: str = "",
    cancel: Callable = None,
) -> Dict[str, Any]:
    """配队先分路。句中写明的命令走工具。要排六人或按条件改某一套，先走检索环。其余问题只查本地资料。"""
    def progress(step: str, message: str) -> None:
        if on_progress is not None:
            on_progress(step, message)

    from pokemon_kb import catalog_ready

    progress("retrieve", "正在读取精灵名录和规则…")
    retrieval_query = question.strip()
    snippets = []
    team_skill = load_skill("team")
    retriever_skill = load_skill("retriever")
    if not catalog_ready():
        draft = REFUSE_ANSWER
        rounds = [{
            "round": 1,
            "llm_calls": 0,
            "draft": draft,
            "checker": {"pass": True, "issues": []},
        }]
        verdict = {"pass": True, "issues": []}
        fallback = ""
        roster = ""
        trial = None
        voice_calls = 0
    else:
        from agents.battle_orders import run_battle_order, wants_lineup
        from agents.chat_notebook import learn
        from agents.rag_agent import is_direct_order, needs_team_rag, run_team_rag
        from agents.thoughts import note_thought

        learned = learn(session_id, retrieval_query)
        if learned:
            note_thought("灯灯记下你的规矩了")
        outside = _notebook_team_note(retrieval_query, session_id)
        stopped = cancel and cancel()
        if stopped:
            order = {"answer": "", "roster": "", "ok": False, "trial": None, "rounds": []}
        elif outside:
            order = {"answer": outside, "roster": "", "ok": True, "trial": None, "rounds": []}
        elif is_direct_order(retrieval_query):
            order = run_battle_order(retrieval_query)
        elif needs_team_rag(retrieval_query) or wants_lineup(retrieval_query):
            order = run_team_rag(retrieval_query, progress, session_id=session_id, cancel=cancel)
        else:
            from knowledge_search import run_knowledge_search

            def report(step_id, status, detail, message):
                progress("retrieve", message or detail or "灯灯在查资料…")

            found = run_knowledge_search(retrieval_query, report, use_web=False, session_id=session_id)
            order = {
                "answer": found.get("answer") or "",
                "roster": "",
                "ok": bool(found.get("found") or found.get("trial")),
                "trial": found.get("trial"),
                "rounds": [],
            }
        draft = order.get("answer") or ""
        roster = order.get("roster") or ""
        trial = order.get("trial")
        rounds = [{
            "round": 1,
            "llm_calls": 1,
            "draft": draft,
            "checker": {"pass": bool(order.get("ok")), "issues": []},
        }]
        verdict = {"pass": bool(order.get("ok")), "issues": []}
        fallback = "order"
        voice_calls = 0
        progress("done", "配队完成")

    trace = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "retrieval_query": retrieval_query,
        "skill_name": "team",
        "skill_text": team_skill,
        "skill_steps": extract_steps(team_skill),
        "retriever_skill": retriever_skill,
        "snippets": snippets,
        "rounds": rounds,
        "answer": draft,
        "roster": roster,
        "passed": bool(verdict.get("pass")),
        "llm_calls": voice_calls,
        "fallback": fallback,
    }
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    trace_path = TRACE_DIR / f"{stamp}.json"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    trace["trace_path"] = str(trace_path)
    return {
        "answer": draft,
        "roster": roster,
        "trial": trial,
        "passed": bool(verdict.get("pass")),
        "llm_calls": voice_calls,
        "sources": [],
        "rounds": rounds,
        "trace_path": str(trace_path),
    }

