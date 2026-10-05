"""检索知识库后，由一个配队助手作答，并按标签和克制规则核对。"""
import json
import re
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


def run_collaborative_agents(
    question: str,
    retriever,
    invoke: Callable = None,
    chat_history: List = None,
    memory_context: str = "",
    on_progress: Callable = None,
) -> Dict[str, Any]:
    """程序选出 6 个名字并补全技能、血脉、道具。不再等待大模型。"""
    def progress(step: str, message: str) -> None:
        if on_progress is not None:
            on_progress(step, message)

    from pokemon_kb import (
        complete_team_answer,
        propose_team_line,
        roster_incomplete,
        validate_team_answer,
        catalog_ready,
    )

    progress("retrieve", "正在读取精灵名录和规则…")
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
        voice_calls = 0
        snippets = []
        retrieval_query = question.strip()
        team_skill = load_skill("team")
        retriever_skill = load_skill("retriever")
    else:
        team_skill = load_skill("team")
        retriever_skill = load_skill("retriever")
        retrieval_query = question.strip()
        snippets = []
        progress("generate", "正在按规则选出 6 只精灵…")
        raw = propose_team_line(question)
        fallback = "program"
        if roster_incomplete(raw, question):
            progress("rewrite", "人数不合规，正在按规则补齐 6 只精灵…")
            raw = propose_team_line(question)
        progress("fill", "正在补全每只 4 个技能、血脉和战斗道具…")
        draft = complete_team_answer(raw, question)
        progress("check", "正在按规则核对…")
        issues = validate_team_answer(draft, question)
        rounds = [{
            "round": 1,
            "llm_calls": 0,
            "draft": draft,
            "checker": {"pass": not issues, "issues": issues},
        }]
        verdict = {"pass": not issues, "issues": issues}
        roster = draft
        voice_calls = 0
        progress("check", "灯灯正在把队伍念给小洛克听…")
        from agents.dengdeng_persona import build_team_user
        from agents.dengdeng_reply import reply_team

        spoken = reply_team(build_team_user(question, roster), roster)
        draft = spoken["text"]
        voice_calls = 1 if spoken["via"] in {"teacher", "lora"} else 0
        if issues:
            draft = draft.rstrip() + "\n\n这套配置还没有满足规则：\n" + "\n".join(
                f"- {item}" for item in issues
            )
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
        "passed": bool(verdict.get("pass")),
        "llm_calls": voice_calls,
        "sources": [],
        "rounds": rounds,
        "trace_path": str(trace_path),
    }

