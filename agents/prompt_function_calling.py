"""基于提示词的 Function Calling。模型只输出约定 JSON，后端再执行。"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from config import DATA_DIR

logger = logging.getLogger("policy_qa.fc")

TRIAL_SPEC = {
    "name": "run_trial_battle",
    "description": "当用户在问两只精灵谁赢、对战或打得过时使用。参数 sprite_a 和 sprite_b 是精灵名。只查资料时不要使用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "sprite_a": {"type": "string", "description": "第一只精灵"},
            "sprite_b": {"type": "string", "description": "第二只精灵"},
        },
        "required": ["sprite_a", "sprite_b"],
    },
}
NONE_SPEC = {
    "name": "none",
    "description": "不需要调用任何函数时使用。arguments 为空对象。",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_NAME_LINE = re.compile(r"^name:\s*(.+?)\s*$", re.M)


def build_fc_prompt(tools: list) -> str:
    blocks = []
    for tool in tools:
        schema = json.dumps(tool.get("input_schema") or {}, ensure_ascii=False)
        blocks.append(f"函数名：{tool['name']}\n作用：{tool.get('description') or ''}\n参数：{schema}")
    catalog = "\n\n".join(blocks)
    return (
        "# 角色：函数调用助手\n"
        "# 任务：判断要不要调用函数；需要则【只】输出：\n"
        '{ "name": "函数名", "arguments": { "参数名": "参数值" } }\n'
        "不需要调用任何函数时【只】输出：\n"
        '{ "name": "none", "arguments": {} }\n'
        "不要输出解释，不要使用厂商的 tools 参数。\n"
        "# 函数定义信息：\n"
        f"{catalog}\n"
    )


def first_json(text: str):
    raw = text or ""
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(raw)):
        char = raw[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(raw[start:index + 1])
                except json.JSONDecodeError:
                    return None
                return data if isinstance(data, dict) else None
    return None


def names_from_table(text: str) -> list:
    found = []
    for name in _NAME_LINE.findall(text or ""):
        cleaned = name.strip()
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found


def _message_text(result) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part))
        content = "".join(parts)
    return str(content or "").strip()


def _resolve_sprite(label: str) -> str:
    from pokemon_kb import _mentioned_names, load_pokemon

    pokemon = load_pokemon()
    catalog = {mon["name"] for mon in pokemon}
    text = str(label or "").strip()
    if text in catalog:
        return text
    found = _mentioned_names(text, pokemon)
    if len(found) == 1:
        return found[0]
    return ""


def _run_trial(arguments: dict) -> tuple:
    from agents.dengdeng_persona import matchup_spoken
    from battle import scripted_bout

    left = _resolve_sprite(arguments.get("sprite_a") or arguments.get("a") or "")
    right = _resolve_sprite(arguments.get("sprite_b") or arguments.get("b") or "")
    if not left or not right or left == right:
        return "没有对上两只不同的精灵。", None
    bout = scripted_bout(left, right)
    spoken = matchup_spoken(left, right, bout.get("winner") or "")
    lines = bout.get("lines") or []
    preview = spoken + "\n" + "\n".join(str(line) for line in lines[:8])
    payload = {
        "sprite_a": left,
        "sprite_b": right,
        "winner": bout.get("winner") or "",
        "spoken": spoken,
        "lines": lines,
        "frames": bout.get("frames") or [],
        "ok": bool(bout.get("ok")),
    }
    return preview[:1500], payload


def _write_trace(question: str, mode: str, rounds: list) -> None:
    folder = Path(DATA_DIR) / "fc_traces"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    payload = {"question": question, "mode": mode, "rounds": rounds}
    (folder / f"{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_prompt_fc(question: str, mode: str, observe=None) -> dict:
    """检索里的试场。最多 3 轮。配队不再从这里选工具。"""
    from llm_provider import get_team_invoke
    from agents.mcp_host import get_mcp_host

    host = get_mcp_host()
    specs = host.list_tools() + [TRIAL_SPEC, NONE_SPEC]
    allowed = {item["name"] for item in specs}
    system = build_fc_prompt(specs)
    invoke = get_team_invoke()
    history = ""
    rounds = []
    party_names = []
    battle = None
    wrote = False
    saw_none = False
    for step in range(3):
        user = f"用户原句：{question}"
        if history:
            user += "\n" + history
        else:
            user += "\n若只是查一只精灵的资料，输出 none。若在问两只谁赢，输出 run_trial_battle，arguments 里给出 sprite_a 和 sprite_b。"
        try:
            raw = _message_text(invoke(system + "\n\n" + user))
        except Exception as exc:
            logger.warning("prompt fc stopped: %s", type(exc).__name__)
            rounds.append({"raw": "", "error": type(exc).__name__})
            break
        parsed = first_json(raw)
        record = {"raw": raw, "parsed": parsed}
        name = str((parsed or {}).get("name") or "")
        arguments = (parsed or {}).get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        if name not in allowed:
            record["skipped"] = "hallucination" if parsed else "unparsed"
            rounds.append(record)
            history = "刚才没有给出可执行的函数。请只输出约定结构；不需要函数时 name 用 none。"
            continue
        record["name"] = name
        record["arguments"] = arguments
        if name == "none":
            saw_none = True
            rounds.append(record)
            break
        if name == "run_trial_battle":
            result_text, battle = _run_trial(arguments)
            if battle is None:
                result_text = result_text or "没有执行。"
        else:
            try:
                result_text = host.call_tool(name, arguments)
            except Exception as exc:
                record["error"] = type(exc).__name__
                result_text = "没有完成。"
        record["result"] = (result_text or "")[:1500]
        rounds.append(record)
        if name == "read_tabular":
            party_names = names_from_table(result_text) or party_names
        if name in {"write_tabular", "write_document"}:
            wrote = True
        extra = ""
        if observe is not None:
            extra = observe(name, result_text, list(party_names)) or ""
        history = f"已执行 {name}。结果：\n{(result_text or '')[:1200]}"
        if extra:
            history += "\n" + extra
        if step == 2:
            break
    try:
        _write_trace(question, mode, rounds)
    except Exception as exc:
        logger.warning("fc trace skipped: %s", type(exc).__name__)
    return {
        "party_names": party_names,
        "battle": battle,
        "wrote": wrote,
        "json_only": not saw_none,
        "rounds": rounds,
    }
