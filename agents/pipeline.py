"""监督者先写计划，再按调度词派工。选人、核对和仓库仍交给原来的程序。"""
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


def _history_text(history: List, question: str = "") -> str:
    from agents.kv_blocks import pack_history

    return pack_history(question, history)


def standalone_query(question: str, history: List, invoke: Callable) -> str:
    """检索员把追问收成独立查询。没有历史时直接用原问题。改写必须留下精灵全名和板块号。"""
    from agents.kv_blocks import rewrite_keeps_anchors

    history_text = _history_text(history, question)
    if not history_text:
        return question.strip()
    prompt = (
        f"{load_skill('retriever')}\n\n"
        "根据检索员技能，把对话历史和最新问题收成一个独立检索查询。\n"
        "只输出查询词，不超过40个字，不要回答问题。\n"
        "原句里的精灵全名和板块号必须原样保留。\n\n"
        f"对话历史：\n{history_text}\n\n最新问题：\n{question.strip()}"
    )
    text = _llm_text(invoke, prompt).splitlines()[0].strip().strip("\"“”")
    if not text or len(text) > 80 or text.startswith("[citation:"):
        return question.strip()
    if not rewrite_keeps_anchors(question, text):
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
    from knowledge_search import _ace_label

    if _ace_label(question):
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
    user_id: str = "",
    history: List = None,
) -> Dict[str, Any]:
    """配队先分路。句中写明的命令走工具。要排六人或按条件改某一套，先走检索环。其余问题只查本地资料。"""
    from agents.fact_memory import absorb_history, fact_blocks
    from agents.kv_blocks import bind_model_context, blocks_from_traces, clear_model_context

    from agents.turn_memory import carry_subject, close_turn

    user_text = (question or "").strip()
    carried = carry_subject(user_text, session_id)
    question = carried["query"]
    absorb_history(session_id, history)
    from agents.work_cycle import context_blocks, prepare_turn

    prepared = prepare_turn(question, history or [], user_id, anchor=carried["anchor"])
    kv_stats = bind_model_context(
        question,
        history,
        blocks_from_traces(session_id, TRACE_DIR),
        extra=fact_blocks(session_id, question) + context_blocks(prepared),
    )
    kv_stats["lookup_query"] = prepared.get("query") or (question or "").strip()
    kv_stats["cycle"] = prepared.get("steps") or []
    kv_stats["user_text"] = user_text
    try:
        result = _run_collaborative_agents(
            question,
            on_progress,
            session_id,
            cancel,
            user_id,
            kv_stats,
        )
    finally:
        clear_model_context()
    if not (cancel and cancel()):
        close_turn(session_id, question, result.get("intent") or "")
    result["resolved"] = question
    return result


def _run_collaborative_agents(
    question: str,
    on_progress: Callable,
    session_id: str,
    cancel: Callable,
    user_id: str,
    kv_stats: Dict[str, Any],
) -> Dict[str, Any]:
    def progress(step: str, message: str) -> None:
        if on_progress is not None:
            on_progress(step, message)

    from pokemon_kb import catalog_ready

    retrieval_query = question.strip()
    intent = ""
    progress("retrieve", f"小洛克在问{retrieval_query}")
    lookup_query = (kv_stats.get("lookup_query") or retrieval_query).strip()
    snippets = []
    job_payload = None
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
        order = {}
        voice_calls = 0
    else:
        from agents.chat_notebook import learn
        from agents.thoughts import note_thought

        from agents.job_ledger import waiting as ledger_waiting

        held = ledger_waiting(session_id)
        learned = []
        if not held:
            learned = learn(session_id, retrieval_query)
            if user_id:
                from agents.preference_pages import learn_preference

                learned = learned + learn_preference(user_id, retrieval_query)
            if learned:
                note_thought("灯灯记下你的规矩了")
        from agents.intent_judge import judge_intent

        judged = judge_intent(retrieval_query)
        intent = judged.get("intent") or ""
        from agents.job_ledger import parked as ledger_parked
        from agents.supervisor import _continues_lineup

        earlier = ledger_parked(session_id)
        if earlier is not None and _continues_lineup(retrieval_query, earlier):
            intent_note = ""
        else:
            intent_note = intent
        if intent_note:
            heard = {
                "search": "查资料",
                "lineup": "配一套",
                "order": "改仓库",
                "battle": "问谁赢",
                "remember": "补充资料",
                "persona_story": "讲自个儿的故事",
            }.get(intent, "办这件事")
            from agents.react_stream import streaming

            if not streaming():
                note_thought(f"灯灯听出来这是在{heard}：{retrieval_query}")
        if lookup_query != retrieval_query and intent != "persona_story":
            note_thought("灯灯先把这句收成下一步")
        outside = _notebook_team_note(retrieval_query, session_id)
        stopped = cancel and cancel()
        if stopped:
            order = {"answer": "", "roster": "", "ok": False, "trial": None, "rounds": []}
        elif outside:
            order = {"answer": outside, "roster": "", "ok": True, "trial": None, "rounds": []}
        else:
            from agents.supervisor import run_cycle

            # 人设故事禁止用改写后的 lookup（防历史注入海豹船长等）
            heard = retrieval_query if intent == "persona_story" else (
                lookup_query if intent in {"search", "battle", "lineup"} else retrieval_query
            )
            from agents.cycle_graph import ask_dispatch

            cycle = run_cycle(
                heard,
                session_id=session_id,
                judged=judged,
                progress=progress,
                cancel=cancel,
                user_id=user_id,
                prepared={"query": lookup_query, "hits": [], "memory": "", "steps": kv_stats.get("cycle") or []},
                learned=learned,
                route_ask=ask_dispatch,
            )
            job_payload = cycle.get("ledger")
            order = cycle.get("order") or {}
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
        if order.get("pending_write"):
            progress("done", "灯灯等你点头")
        elif intent == "lineup":
            progress("done", "这一套排完了")
        elif intent == "order":
            progress("done", "仓库这句办完了")
        else:
            progress("done", f"查完了：{retrieval_query}")

    if job_payload is None:
        job_payload = {}

    trace = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "question": kv_stats.get("user_text") or question,
        "resolved": question,
        "retrieval_query": lookup_query,
        "cycle": kv_stats.get("cycle") or [],
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
        "session_id": session_id,
        "kv": {
            "bypassed": bool(kv_stats.get("bypassed")),
            "compression_ratio": kv_stats.get("compression_ratio"),
            "entity_hit": kv_stats.get("entity_hit"),
            "kept_ids": kv_stats.get("kept_ids") or [],
            "dropped_ids": kv_stats.get("dropped_ids") or [],
            "input_tokens": kv_stats.get("input_tokens"),
            "kept_tokens": kv_stats.get("kept_tokens"),
            "scorer": kv_stats.get("scorer") or "",
        },
        "rollout": job_payload or {},
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
        "web_sources": order.get("web_sources") or [],
        "rounds": rounds,
        "trace_path": str(trace_path),
        "intent": intent,
        "resolved": question,
        "pending_write": order.get("pending_write") or None,
    }

