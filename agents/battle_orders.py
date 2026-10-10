"""模拟对战里的仓库和出场命令。

编号从 1 起。新的一套取已有最大编号加 1。
修改某一套时保留原编号，不改动其它套的编号。

模型先输出约定 JSON。技能、血脉和道具在这里核对，表格工具只负责把核对过的结果留下。
"""
import csv
import io
import logging
import re

from agents.dengdeng_persona import contains_banned
from agents.prompt_function_calling import (
    NONE_SPEC,
    _message_text,
    _resolve_sprite,
    _write_trace,
    build_fc_prompt,
    first_json,
)

logger = logging.getLogger("policy_qa.orders")

WAREHOUSE = "warehouse.csv"
TEAMS = "teams.csv"
ITEMS = ("愿力强化", "进化之力", "光合治愈")
TEAM_FIELDS = ["id", "slot", "name", "blood", "skill1", "skill2", "skill3", "skill4", "item"]
_ORDINALS = "一二三四五六"
_DIGITS = "零一二三四五六七八九"

ORDER_SPECS = [
    {
        "name": "list_warehouse",
        "description": "用户在问仓库里现有哪些精灵、各有几只，或说看看仓库时使用。arguments 为空对象。不要把它当成配六人队。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "change_warehouse",
        "description": "用户说加入、新增或减少若干只精灵时使用。一句里有多只时用 items。不要把它当成配六人队。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "单只时的精灵名"},
                "delta": {"type": "integer", "description": "单只时的增减，新增为正，减少为负"},
                "items": {
                    "type": "array",
                    "description": "一句里多只精灵时用。每项含 name 与 delta。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "delta": {"type": "integer"},
                        },
                        "required": ["name", "delta"],
                    },
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_teams",
        "description": "用户在问已经记下的出场方案，或问第几套是什么时使用。问某一套时带 team_id，问全部时 arguments 为空对象。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "integer", "description": "方案编号，从 1 起"},
            },
            "required": [],
        },
    },
    {
        "name": "save_team",
        "description": "用户要一套可以上场的配队，或说帮我配一队时使用。arguments 为空对象。成员只能来自仓库里数量大于 0 的精灵。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "delete_team",
        "description": "用户要删除、删掉或忘掉已经记下的某一套出场时使用。必须带 team_id。不要改其它套的编号。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "integer", "description": "要忘掉的出场编号"},
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "patch_team",
        "description": "用户要改某一套的精灵、血脉、技能或道具时使用。必须带 team_id。一句里多处修改放在 changes。换精灵用 from_name 与 name。只换一招用 replace_skill 的 from 与 to。没点名的字段不要补。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "integer"},
                "slot": {"type": "integer", "description": "号位，从 1 到 6。知道是哪一只时可以不填。"},
                "name": {"type": "string"},
                "blood": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}},
                "item": {"type": "string"},
                "changes": {
                    "type": "array",
                    "description": "一句里多处修改。每项可含 slot、from_name、name、blood、item、skills、replace_skill。",
                },
            },
            "required": ["team_id"],
        },
    },
    NONE_SPEC,
]
_ALLOWED = {item["name"] for item in ORDER_SPECS}
_COUNT_NAME = re.compile(
    r"([一二两三四五六七八九十0-9]+)\s*只\s*([^\s，,、。！？]+)"
)
_CN_COUNT = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _asks_saved_lineup(text: str) -> bool:
    """在问已经记下的出场，不是要新组一套。"""
    if any(token in text for token in ("出场方案", "配队方案", "已有配队", "记下的出场", "配队列表", "全部配队")):
        return True
    if re.search(r"(查看|看看|列出|有哪些|全部).{0,12}(配队|出场|方案|列表)", text):
        return True
    if re.search(r"第\s*\d+\s*套|第[一二三四五六七八九十]+套", text):
        return True
    return False


def _is_new_lineup(text: str) -> bool:
    return bool(re.search(r"配一队|组一队|组队|组建|排一套|排一支", text))


def _wants_delete_team(text: str) -> bool:
    if not re.search(r"删除|删掉|忘掉", text or ""):
        return False
    if not _team_id_from_text(text):
        return False
    if "仓库" in text and not re.search(r"配队|出场", text):
        return False
    return True


def _wants_release(text: str) -> bool:
    """放生或从仓库删掉精灵。删某一套出场不算。"""
    if _wants_delete_team(text):
        return False
    if re.search(r"放生|丢掉|不要了", text or ""):
        return True
    return bool(re.search(r"删除|删掉", text or "") and "仓库" in (text or ""))


def _wants_patch(text: str) -> bool:
    if _wants_delete_team(text) or not _team_id_from_text(text):
        return False
    return bool(re.search(r"换为|换成|替换|改为|改成|修改", text or ""))


def is_counter_talk(question: str) -> bool:
    """仓库、加减数量、已记下的出场方案。普通「帮我配队」不算。"""
    text = str(question or "").strip()
    if not text:
        return False
    if "仓库" in text:
        return True
    if _wants_delete_team(text) or _wants_release(text) or _wants_patch(text):
        return True
    if re.search(r"(加入|新增|添|放进|减少|收回).{0,20}只", text):
        return True
    if re.search(r"(加入|新增|帮我).{0,8}一只", text):
        if not re.search(r"组建|组队|组一队|组一套|配队|配一队|队伍|为核心|出场", text):
            return True
    if _asks_saved_lineup(text) and not _is_new_lineup(text):
        return True
    if "修改" in text and ("编号" in text or "套出场" in text):
        return True
    return False


def wants_lineup(question: str) -> bool:
    """只有原句明确要排六人时才组队。看仓库、加减数量、查看已有出场都不算。"""
    text = str(question or "").strip()
    if not text or is_counter_talk(text):
        return False
    if _asks_saved_lineup(text) and not _is_new_lineup(text):
        return False
    return bool(re.search(
        r"配一队|配队|组一队|组队|排一套|排好出场|组建|组一套|排一支|队伍|出场阵容|以.+?系为主",
        text,
    ))


def run_battle_order(question: str) -> dict:
    """一句话先变成 JSON，再执行。听不懂或名字不对就不改仓库和出场。"""
    from agents.thoughts import note_thought

    text = str(question or "").strip()
    note_thought("灯灯听清这是一句吩咐")
    if not text:
        return _done("", "灯灯没听懂小洛克的意思。", False, [{"skipped": "empty"}])
    parsed, rounds = _ask(text)
    name = str((parsed or {}).get("name") or "")
    arguments = (parsed or {}).get("arguments") if isinstance((parsed or {}).get("arguments"), dict) else {}
    name, arguments = _correct_order(text, name, arguments or {})
    if rounds:
        rounds[-1]["parsed"] = {"name": name, "arguments": arguments}
    if name not in _ALLOWED or name == "none":
        logger.info("battle_order %s", name or "unparsed")
        return _done(text, "灯灯没听懂小洛克的意思。", False, rounds)
    logger.info("battle_order %s", name)
    try:
        answer, ok, roster = _dispatch(name, arguments or {}, text)
    except Exception as exc:
        logger.warning("battle order stopped: %s", type(exc).__name__)
        answer, ok, roster = "灯灯这会儿没接上话。", False, ""
    return _done(text, answer, ok, rounds, roster)


def _ask(question: str) -> tuple:
    from llm_provider import get_team_invoke

    system = build_fc_prompt(ORDER_SPECS)
    user = (
        f"用户原句：{question}\n"
        "只输出一个 JSON 对象，不要解释。\n"
        "问仓库里有什么、有哪些精灵、各有几只：list_warehouse。这不是配六人队。\n"
        "加入、新增、减少、放生或丢掉仓库里的精灵：change_warehouse。减少和放生的 delta 为负。一句里多只时 arguments.items 为数组。\n"
        "要一套可以上场的配队：save_team。\n"
        "删除、删掉或忘掉某一套已有出场：delete_team。arguments 带 team_id。这不是放生仓库精灵。\n"
        "问已有出场、第几套是什么、全部配队：list_teams。问其中一套时 arguments 带 team_id，问全部时 arguments 为空对象。\n"
        "修改某一套的精灵、血脉、技能或道具：patch_team。team_id 必填。一句里多处改动放进 changes。\n"
        "查种族值、特性、技能效果，或听不清时：none。\n"
        "例子：看看仓库 → {\"name\":\"list_warehouse\",\"arguments\":{}}\n"
        "例子：新增 2 只水灵 → {\"name\":\"change_warehouse\",\"arguments\":{\"name\":\"水灵\",\"delta\":2}}\n"
        "例子：加入一只水灵，一只双灯鱼 → {\"name\":\"change_warehouse\",\"arguments\":{\"items\":[{\"name\":\"水灵\",\"delta\":1},{\"name\":\"双灯鱼\",\"delta\":1}]}}\n"
        "例子：减少 9 只水灵 → {\"name\":\"change_warehouse\",\"arguments\":{\"name\":\"水灵\",\"delta\":-9}}\n"
        "例子：帮我放生掉仓库里的一只海枝枝 → {\"name\":\"change_warehouse\",\"arguments\":{\"name\":\"海枝枝\",\"delta\":-1}}\n"
        "例子：帮我查看已有配队 → {\"name\":\"list_teams\",\"arguments\":{}}\n"
        "例子：帮我查看当前全部配队列表 → {\"name\":\"list_teams\",\"arguments\":{}}\n"
        "例子：第 3 套是什么 → {\"name\":\"list_teams\",\"arguments\":{\"team_id\":3}}\n"
        "例子：帮我把第1套配队删除 → {\"name\":\"delete_team\",\"arguments\":{\"team_id\":1}}\n"
        "例子：把第 1 套出场的第 2 位血脉改成火血脉 → "
        "{\"name\":\"patch_team\",\"arguments\":{\"team_id\":1,\"slot\":2,\"blood\":\"火血脉\"}}\n"
        "例子：把第 1 套出场的第 2 位道具改成进化之力 → "
        "{\"name\":\"patch_team\",\"arguments\":{\"team_id\":1,\"slot\":2,\"item\":\"进化之力\"}}\n"
        "例子：帮我把第一套配队的贝古斯换为音速犬，把水灵的水炮换为润泽 → "
        "{\"name\":\"patch_team\",\"arguments\":{\"team_id\":1,\"changes\":[{\"from_name\":\"贝古斯\",\"name\":\"音速犬\"},{\"from_name\":\"水灵\",\"replace_skill\":{\"from\":\"水炮\",\"to\":\"润泽\"}}]}}\n"
        "例子：把第二套配队中，寂灭骨龙的血脉改为电血脉，吹炎技能改为电弧。恶魔狼换成龙息帕尔。战斗道具换为光合治愈 → "
        "{\"name\":\"patch_team\",\"arguments\":{\"team_id\":2,\"changes\":[{\"from_name\":\"寂灭骨龙\",\"blood\":\"电血脉\"},{\"from_name\":\"寂灭骨龙\",\"replace_skill\":{\"from\":\"吹炎\",\"to\":\"电弧\"}},{\"from_name\":\"恶魔狼\",\"name\":\"龙息帕尔\"},{\"item\":\"光合治愈\"}]}}"
    )
    rounds = []
    try:
        raw = _message_text(get_team_invoke()(system + "\n\n" + user))
    except Exception as exc:
        logger.warning("battle order model stopped: %s", type(exc).__name__)
        rounds.append({"raw": "", "error": type(exc).__name__})
        return None, rounds
    parsed = first_json(raw)
    rounds.append({"raw": raw, "parsed": parsed})
    return parsed, rounds


def _dispatch(name: str, arguments: dict, question: str) -> tuple:
    if name == "list_warehouse":
        sentence, ok = _list_warehouse()
    elif name == "change_warehouse":
        sentence, ok = _change_warehouse(arguments, question)
    elif name == "list_teams":
        return _list_teams(arguments, question)
    elif name == "save_team":
        return _save_team(question)
    elif name == "delete_team":
        sentence, ok = _delete_team(arguments, question)
    elif name == "patch_team":
        return _patch_team(arguments, question)
    else:
        sentence, ok = "灯灯没听懂小洛克的意思。", False
    return sentence, ok, ""


def _done(question: str, answer: str, ok: bool, rounds: list, roster: str = "") -> dict:
    spoken = _speak(answer, ok)
    try:
        _write_trace(question, "battle_order", rounds)
    except Exception as exc:
        logger.warning("battle order trace skipped: %s", type(exc).__name__)
    return {
        "answer": spoken,
        "roster": roster if ok else "",
        "ok": ok,
        "mood": "normal" if ok else "cry",
    }


def _speak(template: str, ok: bool) -> str:
    base = template.strip()
    if contains_banned(base):
        base = "灯灯没听懂小洛克的意思。" if not ok else "灯灯记下了。"
    must = _must_keep(base)

    def accept(text: str) -> bool:
        spoken = text or ""
        if contains_banned(spoken) or ("name" in spoken and "arguments" in spoken):
            return False
        if "凑不齐" not in base and "凑不齐" in spoken:
            return False
        if "出场顺序" not in base and "出场顺序" in spoken:
            return False
        if "记牢" not in base and "记牢" in spoken:
            return False
        if "这样不太妥当" not in base and "这样不太妥当" in spoken:
            return False
        if not all(token in spoken for token in must):
            return False
        # 允许换个说法，但不许把没给过的见闻补成一大段。
        return len(spoken) <= max(len(base) + 240, int(len(base) * 1.4))

    try:
        from agents.dengdeng_reply import compose

        spoken = compose(
            "请用灯灯的口吻向小洛克讲下面这些事实。不要增删事实里的数量、名字、血脉、招式和道具。\n" + base,
            accept,
            lambda: base,
            "仓库",
        )
        text = spoken.get("text") or base
    except Exception:
        return base
    if contains_banned(text) or not accept(text):
        text = base
    return text


def _must_keep(template: str) -> list:
    keys = (
        "仓库里",
        "多放了",
        "收回了",
        "没有那么多",
        "记下了第",
        "套出场",
        "忘掉了",
        "放生了",
        "改好了",
        "这套里没有",
        "这样改不了",
        "这样不太妥当",
        "找不到第",
        "没听懂",
        "没见过",
        "凑不齐",
        "没接上话",
        "没有翻到",
        "要是知道",
        "要是再有",
        "同种伙伴",
    )
    found = [token for token in keys if token in template]
    for name in _catalog():
        if name and name in template:
            found.append(name)
    if "只" in template and "只" not in found:
        found.append("只")
    return found or ["灯灯"]


def _mcp(name: str, arguments: dict) -> str:
    from agents.mcp_host import get_mcp_host

    host = get_mcp_host()
    host.refresh_tools()
    return host.call_tool(name, arguments)


def _local_csv(path: str):
    from pathlib import Path
    from config import DATA_DIR

    return Path(DATA_DIR) / "party" / Path(path).name


def _read_table(path: str) -> str:
    try:
        text = _mcp("read_tabular", {"path": path})
        if str(text or "").strip() and str(text).strip() != "empty":
            return text
    except Exception as exc:
        logger.warning("read table skipped: %s", type(exc).__name__)
    local = _local_csv(path)
    if local.is_file():
        return local.read_text(encoding="utf-8-sig")
    return "empty"


def _write_table(path: str, csv_text: str) -> None:
    try:
        _mcp("write_tabular", {"path": path, "csv_text": csv_text})
        return
    except Exception as exc:
        logger.warning("write table skipped: %s", type(exc).__name__)
    local = _local_csv(path)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text((csv_text or "").rstrip() + "\n", encoding="utf-8")


def _catalog():
    from pokemon_kb import _by_name, load_pokemon

    return _by_name(load_pokemon())


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if text.startswith("+"):
        text = text[1:]
    try:
        return int(text)
    except ValueError:
        return None


def _count_word(count: int) -> str:
    if count == 2:
        return "两"
    if 0 <= count <= 9:
        return _DIGITS[count]
    if count == 10:
        return "十"
    if 11 <= count <= 19:
        return "十" + _DIGITS[count - 10]
    return str(count)


def _pick(arguments: dict, *keys):
    for key in keys:
        if key in arguments and arguments[key] not in (None, ""):
            return arguments[key]
    return None


def _warehouse_rows(text: str) -> list:
    sample = (text or "").lstrip("\ufeff").strip()
    if not sample or sample == "empty":
        return []
    header = sample.splitlines()[0].strip().lower()
    if header.startswith("name,") or header == "name":
        rows = []
        for row in csv.DictReader(io.StringIO(sample)):
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            count = _as_int(row.get("count"))
            rows.append({"name": name, "count": count if count is not None and count >= 0 else 0})
        return rows
    rows = []
    pending = ""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            if pending:
                rows.append({"name": pending, "count": 0})
            pending = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("count:") and pending:
            count = _as_int(stripped.split(":", 1)[1].strip())
            rows.append({"name": pending, "count": count if count is not None and count >= 0 else 0})
            pending = ""
    if pending:
        rows.append({"name": pending, "count": 0})
    return rows


def _warehouse_text(rows: list) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["name", "count"], lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({"name": row["name"], "count": int(row["count"])})
    return buffer.getvalue()


def _list_warehouse() -> tuple:
    from agents.thoughts import note_read

    note_read("仓库")
    catalog = _catalog()
    spoken = []
    for row in _warehouse_rows(_read_table(WAREHOUSE)):
        if row["name"] not in catalog:
            continue
        spoken.append(f"{row['name']}{_count_word(row['count'])}只")
    if not spoken:
        return "小洛克，仓库里灯灯什么也没看见。", True
    return "仓库里灯灯看见" + "、".join(spoken) + "。", True


def _correct_order(question: str, name: str, arguments: dict) -> tuple:
    text = str(question or "")
    args = dict(arguments or {})
    looking = "仓库" in text and re.search(r"有什么|有哪些|看看|里有", text)
    changing = bool(_deltas_from_text(text)) and re.search(r"加入|新增|减少|收回|添|放生|丢掉|不要了", text)
    if _wants_release(text):
        return "change_warehouse", args
    if looking and not changing:
        return "list_warehouse", {}
    if changing:
        return "change_warehouse", args
    if _wants_delete_team(text):
        return "delete_team", {"team_id": _team_id_from_text(text)}
    if _wants_patch(text):
        payload = {"team_id": _team_id_from_text(text)}
        changes = _changes_from_text(text)
        if changes:
            payload["changes"] = changes
        elif args:
            payload.update(args)
            payload["team_id"] = _team_id_from_text(text)
        return "patch_team", payload
    if _asks_saved_lineup(text) and not _is_new_lineup(text):
        team_id = _team_id_from_text(text)
        if team_id:
            return "list_teams", {"team_id": team_id}
        return "list_teams", {}
    if wants_lineup(text):
        return "save_team", {}
    return "none", {}


def _team_id_from_text(text: str):
    match = re.search(r"第\s*(\d+)\s*套", text or "")
    if match:
        return int(match.group(1))
    match = re.search(r"第([一二两三四五六七八九十]+)套", text or "")
    if match:
        return _CN_COUNT.get(match.group(1))
    return None


def _count_from_word(word: str):
    text = str(word or "").strip()
    if text in _CN_COUNT:
        return _CN_COUNT[text]
    return _as_int(text)


def _deltas_from_text(question: str) -> list:
    text = str(question or "")
    release = bool(re.search(r"放生|丢掉|不要了|删除|删掉|减少|收回", text))
    sign = -1 if release and not re.search(r"加入|新增", text) else 1
    found = []
    for count_word, label in _COUNT_NAME.findall(text):
        count = _count_from_word(count_word)
        name = _resolve_sprite(label)
        if not name or count is None or count <= 0:
            continue
        found.append({"name": name, "delta": sign * count})
    if found or not release or _wants_delete_team(text):
        return found
    from pokemon_kb import _mentioned_names, load_pokemon

    for name in _mentioned_names(text, load_pokemon()):
        found.append({"name": name, "delta": -1})
    return found


def _deltas_from_arguments(arguments: dict) -> list:
    found = []
    items = (arguments or {}).get("items") or (arguments or {}).get("changes")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            found.append({
                "name": item.get("name") or item.get("精灵"),
                "delta": item.get("delta") if item.get("delta") is not None else item.get("数量"),
            })
    if _pick(arguments or {}, "name", "精灵") is not None:
        found.append({
            "name": _pick(arguments, "name", "精灵"),
            "delta": _pick(arguments, "delta", "数量"),
        })
    return found


def _change_warehouse(arguments: dict, question: str = "") -> tuple:
    pairs = _deltas_from_arguments(arguments)
    spoken_pairs = _deltas_from_text(question)
    if _wants_release(question) and spoken_pairs:
        pairs = spoken_pairs
    elif len(spoken_pairs) > 1:
        pairs = spoken_pairs
    elif not pairs:
        pairs = spoken_pairs
    resolved = []
    unknown = []
    for item in pairs:
        name = _resolve_sprite(str(item.get("name") or ""))
        delta = _as_int(item.get("delta"))
        if not name:
            label = str(item.get("name") or "").strip()
            if label:
                unknown.append(label)
            continue
        if delta is None or delta == 0:
            continue
        resolved.append({"name": name, "delta": delta})
    if unknown and not resolved:
        return "灯灯没见过这只伙伴。", False
    if not resolved:
        return "灯灯没听懂小洛克的意思。", False
    rows = _warehouse_rows(_read_table(WAREHOUSE))
    for item in resolved:
        index = next((pos for pos, row in enumerate(rows) if row["name"] == item["name"]), None)
        current = rows[index]["count"] if index is not None else 0
        updated = current + item["delta"]
        if updated < 0:
            return "仓库里没有那么多这只伙伴。", False
        if index is None:
            rows.append({"name": item["name"], "count": updated})
        else:
            rows[index]["count"] = updated
    _write_table(WAREHOUSE, _warehouse_text(rows))
    added = [item for item in resolved if item["delta"] > 0]
    removed = [item for item in resolved if item["delta"] < 0]
    parts = []
    if added:
        bits = [f"{_count_word(item['delta'])}只{item['name']}" for item in added]
        parts.append("灯灯帮你在仓库里多放了" + "、".join(bits) + "。")
    if removed:
        bits = [f"{_count_word(abs(item['delta']))}只{item['name']}" for item in removed]
        if _wants_release(question):
            parts.append("灯灯帮你放生了" + "、".join(bits) + "。")
        else:
            parts.append("灯灯帮你在仓库里收回了" + "、".join(bits) + "。")
    from agents.thoughts import note_edit

    note_edit("仓库")
    return "".join(parts), True


def _team_rows(text: str) -> list:
    sample = (text or "").strip()
    if not sample or sample == "empty" or not sample.lower().startswith("id"):
        return []
    found = []
    for row in csv.DictReader(io.StringIO(sample)):
        team_id = _as_int(row.get("id"))
        slot = _as_int(row.get("slot"))
        if team_id is None or slot is None:
            continue
        found.append({
            "id": team_id,
            "slot": slot,
            "name": str(row.get("name") or "").strip(),
            "blood": str(row.get("blood") or "").strip(),
            "skill1": str(row.get("skill1") or "").strip(),
            "skill2": str(row.get("skill2") or "").strip(),
            "skill3": str(row.get("skill3") or "").strip(),
            "skill4": str(row.get("skill4") or "").strip(),
            "item": str(row.get("item") or "").strip(),
        })
    return found


def _group_teams(rows: list) -> dict:
    grouped = {}
    for row in rows:
        grouped.setdefault(row["id"], {})[row["slot"]] = row
    return grouped


def _teams_text(grouped: dict) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TEAM_FIELDS, lineterminator="\n")
    writer.writeheader()
    for team_id in sorted(grouped):
        for slot in range(1, 7):
            row = grouped[team_id].get(slot)
            if not row:
                continue
            writer.writerow({key: row.get(key, "") for key in TEAM_FIELDS})
    return buffer.getvalue()


def _skill_names(row: dict) -> list:
    return [row.get(f"skill{index}") or "" for index in range(1, 5)]


def _member_line(slot: int, row: dict) -> str:
    label = _ORDINALS[slot - 1] if 1 <= slot <= 6 else str(slot)
    skills = "、".join(name for name in _skill_names(row) if name)
    return f"第{label}位是{row['name']}，血脉是{row['blood']}，四招是{skills}，道具是{row['item']}"


def _team_sentence(team_id: int, slots: dict) -> str:
    lines = [f"第 {team_id} 套出场"]
    for slot in range(1, 7):
        row = slots.get(slot)
        if row:
            lines.append(_member_line(slot, row))
    return "。".join(lines) + "。"


def _sheet_roster(slots: dict) -> str:
    """把已记下的六人还原成旧的配队正文，供卡片使用。磁盘上仍是宽表。"""
    from pokemon_kb import _style_tags, elf_skill_options, format_team_answer

    catalog = _catalog()
    members = []
    item = ""
    for slot in range(1, 7):
        row = slots.get(slot) or {}
        name = row.get("name") or ""
        if not name:
            continue
        mon = catalog.get(name)
        if not mon:
            skills = [
                {"name": skill_name, "raw": f"{skill_name}（自带）", "source": "自带"}
                for skill_name in _skill_names(row)
                if skill_name
            ]
            item = row.get("item") or item
            members.append({
                "name": name,
                "tags": [],
                "skills": skills,
                "blood": row.get("blood") or "初始血脉",
            })
            continue
        options = {skill["name"]: skill for skill in elf_skill_options(mon)}
        skills = []
        for skill_name in _skill_names(row):
            if not skill_name:
                continue
            skills.append(options.get(skill_name) or {"name": skill_name, "raw": skill_name, "source": ""})
        item = row.get("item") or item
        members.append({
            "name": name,
            "tags": _style_tags(mon),
            "skills": skills,
            "blood": row.get("blood") or "",
        })
    if len(members) != 6:
        return ""
    outside = [member["name"] for member in members if member["name"] not in catalog]
    if item == "进化之力":
        bosses = [member["name"] for member in members if member["blood"] == "首领血脉"]
        if bosses:
            reason = "队内有可首领化精灵（" + "、".join(bosses) + "），所以携带【进化之力】。"
        else:
            reason = "这一套携带【进化之力】，队里还没有首领血脉。"
    else:
        reason = "已经记下的这一套出场。"
    if outside:
        reason = "以" + "、".join(outside) + "为主力，标签和首领化留空。" + reason
    return format_team_answer(members, item, reason)


def _team_evolve_awkward(item: str, bloods: list) -> bool:
    """全队同一种道具。有任意一只首领血脉时，进化之力是正经用法。"""
    return item == "进化之力" and not any(blood == "首领血脉" for blood in bloods)


def _slot_evolve_awkward(previous_item: str, item: str, blood: str, item_was_set: bool) -> bool:
    """只在这一位的道具改成进化之力、且这一位不是首领血脉时提示。"""
    return bool(item_was_set and item == "进化之力" and previous_item != item and blood != "首领血脉")


def _team_brief(team_id: int, slots: dict) -> str:
    names = []
    item = ""
    for slot in range(1, 7):
        row = slots.get(slot)
        if not row or not row.get("name"):
            continue
        names.append(row["name"])
        item = row.get("item") or item
    text = f"第 {team_id} 套是" + "、".join(names)
    if item:
        text += f"，道具是{item}"
    return text


def _list_teams(arguments: dict, question: str = "") -> tuple:
    from agents.thoughts import note_read

    note_read("已有出场")
    grouped = _group_teams(_team_rows(_read_table(TEAMS)))
    wanted = _as_int(_pick(arguments, "team_id", "编号"))
    if wanted is None:
        wanted = _team_id_from_text(question)
    if wanted is not None:
        slots = grouped.get(wanted)
        if not slots:
            return f"灯灯找不到第 {wanted} 套出场。", False, ""
        roster = _sheet_roster(slots)
        return "灯灯记得" + _team_sentence(wanted, slots), True, roster
    if not grouped:
        return "灯灯还没有记下任何一套出场。", True, ""
    parts = ["灯灯记得这些出场"]
    for team_id in sorted(grouped):
        parts.append(_team_brief(team_id, grouped[team_id]))
    return "。".join(parts) + "。", True, ""


def _stock() -> dict:
    catalog = _catalog()
    found = {}
    for row in _warehouse_rows(_read_table(WAREHOUSE)):
        if row["name"] in catalog and row["count"] > 0:
            found[row["name"]] = found.get(row["name"], 0) + row["count"]
    return found


def _roster_unbounded(question: str) -> bool:
    """句中写明可以不局限仓库时，出场只要求精灵在名录里。"""
    return bool(re.search(r"不局限仓库|不必局限|不限于仓库|不限制仓库", question or ""))


def _save_team(question: str, names: list = None, replace_id: int = None) -> tuple:
    from pokemon_kb import (
        _can_boss,
        _name_stem,
        complete_team_answer,
        fill_member_skills,
        parse_team_config,
        propose_team_line,
        type_chart,
    )

    stock = _stock()
    catalog = _catalog()
    unbounded = _roster_unbounded(question)
    allowed = list(catalog) if unbounded else [name for name, count in stock.items() if count > 0]
    if names is None and len({_name_stem(name) for name in allowed}) < 6:
        return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
    if names is None:
        proposed = propose_team_line(question, allowed=allowed)
    else:
        picked = []
        for raw in names:
            resolved = _resolve_sprite(raw) or str(raw or "").strip()
            if resolved not in catalog:
                return "灯灯没见过这只伙伴。", False, ""
            if not unbounded and stock.get(resolved, 0) <= 0:
                return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
            picked.append(resolved)
        stems = [_name_stem(name) for name in picked]
        if len(picked) != 6 or len(set(stems)) != 6:
            return "这样改不了，同一套里不能有同种伙伴。", False, ""
        proposed = "队伍配置为" + "、".join(picked)
    filled = complete_team_answer(proposed, question, allowed=allowed) if proposed else ""
    parsed = parse_team_config(filled) if filled else {"members": [], "item": ""}
    members = parsed.get("members") or []
    if len(members) != 6:
        return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
    item = parsed.get("item") or ""
    if item not in ITEMS:
        return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
    catalog = _catalog()
    chart = None
    if item == "进化之力":
        for member in members:
            mon = catalog.get(member.get("name") or "")
            if not mon or not _can_boss(mon) or member.get("blood") == "首领血脉":
                continue
            member["blood"] = "首领血脉"
            kept = [skill for skill in (member.get("skills") or []) if skill.get("source") != "血脉"]
            if len(kept) < 4:
                if chart is None:
                    chart = type_chart()
                member["skills"] = fill_member_skills(mon, kept, False, chart)
            else:
                member["skills"] = kept[:4]
    usage = {}
    built = []
    for member in members:
        name = member.get("name") or ""
        skills = [skill.get("name") or "" for skill in (member.get("skills") or [])]
        blood = member.get("blood") or ""
        issues = _inspect(name, blood, skills, item)
        if issues:
            return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
        usage[name] = usage.get(name, 0) + 1
        if not unbounded and usage[name] > stock.get(name, 0):
            return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
        built.append((name, blood, skills, item))
    stems = [_name_stem(name) for name, _blood, _skills, _item in built]
    if len(stems) != len(set(stems)):
        return "这样改不了，同一套里不能有同种伙伴。", False, ""
    grouped = _group_teams(_team_rows(_read_table(TEAMS)))
    if replace_id is not None:
        if replace_id not in grouped:
            return f"灯灯找不到第 {replace_id} 套出场。", False, ""
        team_id = replace_id
        sentence_head = f"灯灯改好了第 {team_id} 套出场。"
    else:
        team_id = (max(grouped) if grouped else 0) + 1
        sentence_head = "灯灯记下了第 " + str(team_id) + " 套出场。"
    grouped[team_id] = {}
    for slot, (name, blood, skills, item_name) in enumerate(built, start=1):
        grouped[team_id][slot] = _row(team_id, slot, name, blood, skills, item_name)
    _write_table(TEAMS, _teams_text(grouped))
    from agents.thoughts import note_edit

    note_edit(f"第 {team_id} 套出场")
    sentence = sentence_head + _team_sentence(team_id, grouped[team_id])
    if _team_evolve_awkward(item, [blood for _name, blood, _skills, _item in built]):
        sentence += "这样不太妥当。"
    return sentence, True, _sheet_roster(grouped[team_id])


def _save_with_guest(question: str, companions: list, guest: dict) -> tuple:
    """五名仓库伙伴沿用原来的补招。主力来自这段对话记下的卡片，不写进名录，也不扣仓库。"""
    from pokemon_kb import complete_team_answer, format_team_answer, parse_team_config

    stock = _stock()
    catalog = _catalog()
    guest_name = guest.get("name") or ""
    guest_skills = [str(skill) for skill in (guest.get("skills") or [])][:4]
    if not guest_name or len(guest_skills) != 4 or len(companions) != 5:
        return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
    filler = next((name for name in stock if stock.get(name, 0) > 0 and name not in companions and name != guest_name), "")
    if not filler:
        return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
    proposed = "队伍配置为" + "、".join(list(companions) + [filler])
    filled = complete_team_answer(proposed, question, allowed=list(catalog))
    parsed = parse_team_config(filled) if filled else {"members": [], "item": ""}
    members = [member for member in (parsed.get("members") or []) if member.get("name") != filler]
    if len(members) != 5:
        return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
    item = parsed.get("item") or ""
    if item not in ITEMS:
        return "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False, ""
    guest_tags = [tag for tag in (guest.get("tags") or []) if tag]
    guest_blood = guest.get("blood") or "初始血脉"
    guest_member = {
        "name": guest_name,
        "tags": guest_tags,
        "blood": guest_blood,
        "skills": [
            {"name": skill, "raw": f"{skill}（自带）", "source": "自带"}
            for skill in guest_skills
        ],
    }
    members = [guest_member] + members
    if guest_blood == "首领血脉" and "光合治愈" not in (question or "") and "愿力强化" not in (question or ""):
        item = "进化之力"
    tag_text = "、".join(guest_tags) if guest_tags else "留空"
    boss_text = "是" if guest_blood == "首领血脉" else "留空"
    reason = f"以{guest_name}为主力，标签{tag_text}，首领化{boss_text}。" + (parsed.get("reason") or "")
    roster = format_team_answer(members, item, reason)
    grouped = _group_teams(_team_rows(_read_table(TEAMS)))
    team_id = (max(grouped) if grouped else 0) + 1
    grouped[team_id] = {}
    for slot, member in enumerate(members, start=1):
        skills = [skill.get("name") or "" for skill in (member.get("skills") or [])]
        grouped[team_id][slot] = _row(team_id, slot, member["name"], member.get("blood") or "", skills, item)
    _write_table(TEAMS, _teams_text(grouped))
    from agents.thoughts import note_edit

    note_edit(f"第 {team_id} 套出场")
    sentence = "灯灯记下了第 " + str(team_id) + " 套出场。" + _team_sentence(team_id, grouped[team_id])
    if _team_evolve_awkward(item, [member.get("blood") or "" for member in members]):
        sentence += "这样不太妥当。"
    return sentence, True, roster or _sheet_roster(grouped[team_id])


def _row(team_id: int, slot: int, name: str, blood: str, skills: list, item: str) -> dict:
    packed = list(skills) + ["", "", "", ""]
    return {
        "id": team_id,
        "slot": slot,
        "name": name,
        "blood": blood,
        "skill1": packed[0],
        "skill2": packed[1],
        "skill3": packed[2],
        "skill4": packed[3],
        "item": item,
    }


def _skill_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        found = []
        for item in value:
            text = str(item or "").strip()
            if text:
                found.append(text.split("（", 1)[0].strip())
        return found
    text = str(value).strip()
    if not text:
        return []
    found = []
    for part in text.replace("，", "、").replace(",", "、").split("、"):
        name = part.strip().split("（", 1)[0].strip()
        if name:
            found.append(name)
    return found


def _slot_from_clause(text: str):
    match = re.search(r"第\s*([1-6])\s*位", text or "")
    if match:
        return int(match.group(1))
    match = re.search(r"第([一二三四五六])位", text or "")
    if not match:
        return None
    return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}[match.group(1)]


def _owner_sprite(text: str) -> str:
    resolved = _resolve_sprite(text)
    if resolved:
        return resolved
    from pokemon_kb import _mentioned_names, load_pokemon

    found = _mentioned_names(text, load_pokemon())
    return found[-1] if found else ""


_CHANGE_MARK = re.compile(r"(.+?)(?:替换为|替换成|换为|换成|改为|改成|替换)(.+)")


def _skill_label(text: str) -> str:
    return re.sub(r"(技能|招式|这一招|这招)$", "", str(text or "").strip()).strip()


def _changes_from_text(text: str) -> list:
    """模型没把改动写全时，从原句拆出换精灵、换一招、改血脉和改道具。"""
    changes = []
    recent = ""
    for part in re.split(r"[，,。；;]", text or ""):
        part = part.strip()
        swap = _CHANGE_MARK.search(part)
        if not swap:
            owner = _owner_sprite(part)
            if owner:
                recent = owner
            continue
        left, right = swap.group(1).strip(), swap.group(2).strip()
        if "道具" in left:
            changes.append({"item": right.strip()})
            continue
        if re.search(r"血脉\s*$", left):
            owner = ""
            cut = re.search(r"的\s*血脉\s*$", left)
            if cut:
                owner = _owner_sprite(left[:cut.start()])
            if owner:
                recent = owner
            change = {"blood": right.strip()}
            if owner:
                change["from_name"] = owner
            else:
                slot = _slot_from_clause(part)
                if slot:
                    change["slot"] = slot
            changes.append(change)
            continue
        owner_split = re.search(r"的([^的]+)$", left)
        if owner_split:
            mid = _skill_label(owner_split.group(1))
            head = left[:owner_split.start()]
            mid_sprite = _resolve_sprite(mid)
            right_sprite = _resolve_sprite(right)
            if mid_sprite and right_sprite:
                recent = right_sprite
                changes.append({"from_name": mid_sprite, "name": right_sprite})
                continue
            owner = _owner_sprite(head) or recent
            if owner and not mid_sprite:
                if owner:
                    recent = owner
                changes.append({"from_name": owner, "replace_skill": {"from": mid, "to": right.strip()}})
                continue
        left_sprite = _resolve_sprite(left)
        right_sprite = _resolve_sprite(right)
        if left_sprite and right_sprite:
            recent = right_sprite
            changes.append({"from_name": left_sprite, "name": right_sprite})
            continue
        skill_from = _skill_label(left)
        if recent and skill_from and not _resolve_sprite(skill_from) and not _resolve_sprite(right):
            changes.append({"from_name": recent, "replace_skill": {"from": skill_from, "to": right.strip()}})
    return changes


def _find_slot(slots: dict, label: str):
    wanted = _resolve_sprite(label) or str(label or "").strip()
    if not wanted:
        return None
    for slot in range(1, 7):
        row = slots.get(slot) or {}
        if row.get("name") == wanted:
            return slot
    return None


def _rebuilt_member(name: str):
    from pokemon_kb import _blood_label, fill_member_skills, type_chart

    mon = _catalog().get(name)
    if not mon:
        return None
    filled = fill_member_skills(mon, [], True, type_chart())
    skills = [skill.get("name") or "" for skill in filled if skill.get("name")]
    if len(skills) != 4 or len(set(skills)) != 4:
        return None
    return _blood_label(filled), skills


def _delete_team(arguments: dict, question: str = "") -> tuple:
    team_id = _as_int(_pick(arguments, "team_id", "编号"))
    if team_id is None:
        team_id = _team_id_from_text(question)
    if team_id is None:
        return "灯灯没听懂小洛克的意思。", False
    grouped = _group_teams(_team_rows(_read_table(TEAMS)))
    if team_id not in grouped:
        return f"灯灯找不到第 {team_id} 套出场。", False
    del grouped[team_id]
    _write_table(TEAMS, _teams_text(grouped))
    from agents.thoughts import note_edit

    note_edit(f"第 {team_id} 套出场")
    return f"灯灯把第 {team_id} 套出场忘掉了。", True


def _change_list(arguments: dict, question: str) -> list:
    spoken = _changes_from_text(question)
    if spoken:
        return spoken
    incoming = (arguments or {}).get("changes")
    if isinstance(incoming, list) and incoming:
        return [item for item in incoming if isinstance(item, dict)]
    if any(_pick(arguments or {}, key) is not None for key in ("slot", "号位", "name", "精灵", "blood", "血脉", "skills", "item", "道具", "from_name")):
        return [arguments or {}]
    return []


def _apply_team_change(slots: dict, change: dict) -> tuple:
    slot = _as_int(change.get("slot") if change.get("slot") is not None else change.get("号位"))
    from_name = change.get("from_name") or change.get("原精灵")
    if slot is None and from_name:
        slot = _find_slot(slots, str(from_name))
        if slot is None:
            shown = _resolve_sprite(str(from_name)) or str(from_name)
            return f"灯灯这套里没有{shown}。", None
    if slot is None or slot not in slots:
        return "灯灯没听懂小洛克的意思。", None
    row = slots[slot]
    new_name = _pick(change, "name", "精灵")
    if new_name is not None and str(new_name).strip():
        resolved = _resolve_sprite(str(new_name))
        if not resolved:
            return "灯灯没见过这只伙伴。", None
        rebuilt = _rebuilt_member(resolved)
        if not rebuilt:
            return "这样改不了，技能和血脉对不上。", None
        row["name"] = resolved
        row["blood"], skills = rebuilt
        for index, skill_name in enumerate(skills, start=1):
            row[f"skill{index}"] = skill_name
    if _pick(change, "blood", "血脉") is not None:
        row["blood"] = str(_pick(change, "blood", "血脉")).strip()
    if _pick(change, "skills", "skill", "技能") is not None:
        skills = _skill_list(_pick(change, "skills", "skill", "技能"))
        for index in range(1, 5):
            row[f"skill{index}"] = skills[index - 1] if index - 1 < len(skills) else ""
    replacement = change.get("replace_skill") if isinstance(change.get("replace_skill"), dict) else {}
    if replacement:
        source = str(replacement.get("from") or replacement.get("原技能") or "").strip()
        target = str(replacement.get("to") or replacement.get("技能") or "").strip()
        skills = _skill_names(row)
        if not source or source not in skills or not target:
            return "这样改不了，技能和血脉对不上。", None
        skills = [target if item == source else item for item in skills]
        for index, skill_name in enumerate(skills, start=1):
            row[f"skill{index}"] = skill_name
    if _pick(change, "item", "道具") is not None:
        row["item"] = str(_pick(change, "item", "道具")).strip()
    return "", slot


def _fit_blood_skill(row: dict, protected: set) -> None:
    """血脉改成某一系时，四招里要有且只有这一系的血脉招，否则整句对不上。"""
    from pokemon_kb import elf_skill_options

    blood = str(row.get("blood") or "")
    if blood in {"初始血脉", "首领血脉"} or not blood.endswith("血脉"):
        return
    mon = _catalog().get(row.get("name") or "")
    if not mon:
        return
    expected = blood[:-2]
    pool = list(elf_skill_options(mon))
    match = next((skill for skill in pool if skill.get("source") == "血脉" and skill.get("blood_type") == expected), None)
    if not match:
        return
    skills = _skill_names(row)
    if match["name"] in skills:
        return
    blood_names = {skill["name"] for skill in pool if skill.get("source") == "血脉"}
    index = next((pos for pos, name in enumerate(skills) if name in blood_names and name not in protected), None)
    if index is None:
        for pos in range(len(skills) - 1, -1, -1):
            if skills[pos] not in protected:
                index = pos
                break
    if index is None:
        return
    skills[index] = match["name"]
    for pos, skill_name in enumerate(skills, start=1):
        row[f"skill{pos}"] = skill_name


def _patch_team(arguments: dict, question: str = "") -> tuple:
    team_id = _as_int(_pick(arguments, "team_id", "编号"))
    if team_id is None:
        team_id = _team_id_from_text(question)
    changes = _change_list(arguments, question)
    if team_id is None or not changes:
        return "灯灯没听懂小洛克的意思。", False, ""
    grouped = _group_teams(_team_rows(_read_table(TEAMS)))
    slots = grouped.get(team_id)
    if not slots:
        return f"灯灯找不到第 {team_id} 套出场。", False, ""
    working = {slot: dict(row) for slot, row in slots.items()}
    previous_item = (working.get(1) or {}).get("item") or ""
    touched = []
    shared_item = None
    protected = set()
    for change in changes:
        replacement = change.get("replace_skill") if isinstance(change.get("replace_skill"), dict) else {}
        if replacement.get("to") or replacement.get("技能"):
            protected.add(str(replacement.get("to") or replacement.get("技能")).strip())
        item_value = _pick(change, "item", "道具")
        if item_value is not None:
            shared_item = str(item_value).strip()
        has_body = any(change.get(key) for key in ("from_name", "原精灵", "name", "精灵", "blood", "血脉", "skills", "skill", "技能", "replace_skill"))
        has_body = has_body or _as_int(change.get("slot") if change.get("slot") is not None else change.get("号位")) is not None
        if not has_body:
            continue
        message, slot = _apply_team_change(working, change)
        if message:
            return message, False, ""
        if slot not in touched:
            touched.append(slot)
    if shared_item is not None:
        for row in working.values():
            row["item"] = shared_item
    for row in working.values():
        _fit_blood_skill(row, protected)
    for slot in sorted(working):
        row = working[slot]
        issues = _inspect(row["name"], row["blood"], _skill_names(row), row["item"])
        if issues:
            return "这样改不了，技能和血脉对不上。", False, ""
        working[slot] = _row(team_id, slot, row["name"], row["blood"], _skill_names(row), row["item"])
    from pokemon_kb import _name_stem

    stems = [_name_stem(working[slot]["name"]) for slot in sorted(working)]
    if len(stems) != len(set(stems)):
        return "这样改不了，同一套里不能有同种伙伴。", False, ""
    grouped[team_id] = working
    _write_table(TEAMS, _teams_text(grouped))
    from agents.thoughts import note_edit

    note_edit(f"第 {team_id} 套出场")
    bits = [_member_line(slot, working[slot]) for slot in touched]
    sentence = f"灯灯改好了第 {team_id} 套出场。" + "。".join(bits) + "。"
    if shared_item:
        sentence += f"战斗道具是{shared_item}。"
    bloods = [working[slot]["blood"] for slot in working]
    item = (working.get(1) or {}).get("item") or ""
    if shared_item is not None and _team_evolve_awkward(item, bloods) and previous_item != item:
        sentence += "这样不太妥当。"
    return sentence, True, _sheet_roster(working)


def _inspect(name: str, blood: str, skills: list, item: str) -> list:
    from pokemon_kb import elf_skill_options

    issues = []
    catalog = _catalog()
    mon = catalog.get(name)
    if mon is None:
        return ["unknown"]
    cleaned = [str(skill or "").strip() for skill in skills]
    if len(cleaned) != 4 or len(set(cleaned)) != 4 or any(skill == "聚能" or not skill for skill in cleaned):
        issues.append("skills")
    pool = {skill["name"]: skill for skill in elf_skill_options(mon)}
    resolved = []
    for skill_name in cleaned:
        skill = pool.get(skill_name)
        if skill is None:
            issues.append("pool")
            continue
        resolved.append(skill)
    if item not in ITEMS:
        issues.append("item")
    bloods = [skill for skill in resolved if skill.get("source") == "血脉"]
    if blood == "首领血脉" or blood == "初始血脉":
        if bloods:
            issues.append("blood")
    elif str(blood).endswith("血脉") and blood not in {"首领血脉", "初始血脉"}:
        expected = blood[:-2]
        if len(bloods) != 1 or bloods[0].get("blood_type") != expected:
            issues.append("blood")
    else:
        issues.append("blood")
    return issues
