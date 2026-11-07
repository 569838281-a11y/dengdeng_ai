"""成文交出去之前，看这句话本身。

四件事：有没有答上这句的核心、有没有多答；顺不顺、完整不完整；
前后有没有矛盾或重复；有没有编出来的内容，或是不像灯灯的词。
改写只能收措辞，不能新加精灵、技能和数字，也不能删掉已经点到的名字。
模型没答上时，只留下程序能判定的那几条。
"""
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

ISSUES = ("core", "extra", "fluency", "repeat", "conflict", "hallucination", "voice")

_SYSTEM = """你在看灯灯准备告诉小洛克的这句话。只输出一个 JSON，不要解释。
格式：{"pass":true或false,"issues":["core","extra","fluency","repeat","conflict","hallucination","voice"],"text":""}
core：没答上小洛克这句的核心要求。点名的核心没有进入六只、只解释做不到，也算 core。
extra：答了小洛克没问的事。
fluency：语句不顺，或说到一半没有收束。
repeat：同一层意思说了两遍。
conflict：前后矛盾。
hallucination：出现了给定原文和允许点名里没有的精灵、技能、数字或胜负。
voice：不像灯灯在说话，或出现助手、机器、人工智能这类词。灯灯自称灯灯。
text：需要改写时给出整段；不需要就留空。改写不得新增精灵、技能和数字，不得删掉原文里的精灵名。"""

_VOICE = ("作为语言模型", "根据您的问题", "我是人工智能", "人工智能", "AI助手")


def review_speech(question: str, speech: str, evidence: dict = None, ask=None) -> dict:
    """返回 pass、issues、text、repaired。text 是可以交出去的那一版。"""
    evidence = evidence or {}
    original = (speech or "").strip()
    if not original:
        return {"pass": False, "issues": ["fluency"], "text": original, "repaired": False}
    deduped = _dedupe(original)
    issues = _program_issues(question, deduped, evidence)
    if deduped != original:
        _add(issues, "repeat")
    model_issues, model_text = _model_review(question, deduped, evidence, ask)
    for item in model_issues:
        _add(issues, item)
    candidate = (model_text or "").strip()
    if candidate and candidate != deduped and _accept(question, deduped, candidate, evidence):
        left = _program_issues(question, candidate, evidence)
        return {"pass": not left, "issues": issues, "text": candidate, "repaired": True}
    if deduped != original and not _program_issues(question, deduped, evidence) and not model_issues:
        return {"pass": True, "issues": ["repeat"], "text": deduped, "repaired": True}
    return {
        "pass": not issues,
        "issues": issues,
        "text": deduped if deduped != original else original,
        "repaired": deduped != original,
    }


def parse_review(raw: str) -> dict:
    from agents.prompt_function_calling import first_json

    data = first_json(raw or "")
    if not isinstance(data, dict):
        return {"pass": None, "issues": [], "text": ""}
    issues = []
    for item in data.get("issues") or []:
        name = str(item or "").strip()
        if name in ISSUES and name not in issues:
            issues.append(name)
    passed = data.get("pass")
    if isinstance(passed, str):
        passed = passed.strip().lower() in {"true", "1", "yes"}
    return {
        "pass": bool(passed) if isinstance(passed, bool) else None,
        "issues": issues,
        "text": str(data.get("text") or "").strip(),
    }


def _program_issues(question: str, speech: str, evidence: dict) -> list:
    from agents.dengdeng_persona import contains_banned
    from knowledge_search import _ace_label

    issues = []
    text = speech or ""
    names = [str(name) for name in (evidence.get("names") or []) if str(name).strip()]
    ace = _ace_label(question or "")
    if len(text) > 8 and not re.search(r"[。！？]$", text.strip()):
        _add(issues, "fluency")
    if contains_banned(text) or any(word.lower() in text.lower() for word in _VOICE):
        _add(issues, "voice")
    if ace and names and ace not in names:
        _add(issues, "core")
    if ace and ace in names and f"没有叫{ace}" in text:
        _add(issues, "conflict")
    stray = _stray_names(question, text, names)
    if stray:
        _add(issues, "hallucination")
    return issues


def _stray_names(question: str, speech: str, names: list) -> list:
    from pokemon_kb import _mentioned_names, load_pokemon

    allowed = set(names)
    allowed.update(_mentioned_names(question or "", load_pokemon()))
    stray = []
    for name in _mentioned_names(speech or "", load_pokemon()):
        if name not in allowed and name not in stray:
            stray.append(name)
    return stray


def _accept(question: str, original: str, candidate: str, evidence: dict) -> bool:
    from agents.dengdeng_persona import contains_banned
    from pokemon_kb import _mentioned_names, load_pokemon

    if not candidate or contains_banned(candidate):
        return False
    if any(word.lower() in candidate.lower() for word in _VOICE):
        return False
    for name in evidence.get("names") or []:
        if name and name not in candidate:
            return False
    for token in evidence.get("keep") or []:
        if token and token not in candidate:
            return False
    pokemon = load_pokemon()
    allowed = set(_mentioned_names(original, pokemon))
    allowed.update(_mentioned_names(question or "", pokemon))
    allowed.update(str(name) for name in (evidence.get("names") or []))
    for name in _mentioned_names(candidate, pokemon):
        if name not in allowed:
            return False
    return True


def _dedupe(text: str) -> str:
    parts = re.split(r"(?<=[。！？])", text or "")
    kept = []
    seen = set()
    for part in parts:
        key = part.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        kept.append(part)
    return "".join(kept).strip()


def _add(issues: list, name: str) -> None:
    if name in ISSUES and name not in issues:
        issues.append(name)


def _model_review(question: str, speech: str, evidence: dict, ask) -> tuple:
    names = "、".join(str(name) for name in (evidence.get("names") or []) if str(name).strip())
    body = f"小洛克的要求：{question or ''}\n允许点名：{names or '无'}\n灯灯准备说：{speech}"
    try:
        raw = (ask or _ask_teacher)(body)
    except Exception as exc:
        logger.warning("成文审查未完成：%s", type(exc).__name__)
        return [], ""
    parsed = parse_review(raw)
    issues = list(parsed["issues"])
    if parsed["pass"] is False and not issues:
        issues = ["core"]
    if parsed["pass"] is True:
        issues = [item for item in issues if item != "core"]
    return issues, parsed["text"]


def _ask_teacher(body: str) -> str:
    from llm_provider import _voice_timeout, get_team_invoke

    invoke = get_team_invoke(_voice_timeout())
    result = invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=body),
    ])
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "").strip()
