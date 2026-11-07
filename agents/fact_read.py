"""把一问收成最多三条事实，再按原文逐条核对。

对得上才允许开口。对不上的那一条留给现有的缺口。
多步的问题先定步数，查完一步再写下一步。下一步里的名字必须来自原问题或已经对上的原文。
"""
import json
import re
from pathlib import Path

_TYPES = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电", "毒",
    "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)
_ROOT = Path(__file__).resolve().parents[1]
_POKEMON = _ROOT / "knowledge" / "pokemon"


def split_facts(question: str) -> list:
    """收成最多三条要查的事实。认不出形状时返回空，调用方仍走原来的整句。"""
    text = (question or "").strip()
    if not text:
        return []
    if any(word in text for word in ("差别", "不同", "区别")):
        head = re.split(r"有什么|的区别|有何", text)[0]
        pieces = [item.strip(" ？?。，,、") for item in re.split(r"[和与]", head)]
        names = [item for item in pieces if 1 < len(item) <= 12]
        if len(names) >= 2:
            return names[:3]
    facts = []
    types = [name for name in _TYPES if name in text]
    matchup = len(types) >= 2 and any(word in text for word in ("打", "克制", "倍率", "伤害"))
    wants_total = any(word in text for word in ("最终", "算出")) and "数字" in text
    if matchup and wants_total:
        facts.append(f"{types[0]}系打{types[1]}系的倍率")
        facts.append("伤害公式")
        facts.append("这一下的最终伤害数字")
    elif matchup:
        facts.append(f"{types[0]}系的克制")
        facts.append(f"{types[1]}系的抵抗")
    if "首领" in text:
        name = _named_before(text, "首领")
        if name:
            facts.append(f"{name}首领化")
    if "能耗" in text:
        skill = _named_before(text, "这个技能") or _named_before(text, "的能耗")
        if skill:
            facts.append(f"{skill}的能耗")
    if "更换" in text and "技能" in text:
        facts.append("更换是否使用技能")
    if "星陨" in text:
        facts.append("星陨额外伤害")
    if "种族值" in text:
        name = _named_before(text, "的种族值")
        if name:
            facts.append(f"{name}的种族值")
    if not facts:
        name = _first_pokemon(text)
        if name and "特性" in text:
            facts.append(f"{name}的特性")
        elif name and ("什么系" in text or "属性" in text):
            facts.append(f"{name}的属性")
    leading = []
    outside = outside_query(text)
    if outside:
        leading.append(outside)
    pool = skill_pool_name(text)
    if pool:
        leading.append(f"{pool}的技能")
    facts = leading + facts
    seen = []
    for item in facts:
        if item and item not in seen:
            seen.append(item)
    return seen[:3]


def read_facts(question: str) -> dict:
    """返回 queries、covered、missing、speech、ask。"""
    facts = split_facts(question)
    covered = []
    missing = []
    for fact in facts:
        lines = _lines_for(fact)
        if _covers(fact, lines):
            covered.append({"fact": fact, "lines": lines[:4]})
        else:
            missing.append(fact)
    speech = _speech(covered)
    ask = ""
    if missing:
        ask = _ask_sentence(missing[0], speech)
    return {
        "queries": facts,
        "covered": covered,
        "missing": missing,
        "speech": speech,
        "ask": ask,
    }


_POWER_TAILS = (
    "的本系技能和威力",
    "的技能和威力",
    "的技能及威力",
    "的技能与威力",
)


def _power_tail(fact: str) -> str:
    for tail in _POWER_TAILS:
        if (fact or "").endswith(tail):
            return tail
    return ""


def _team_like(token: str) -> bool:
    """队伍/阵容是桥实体，不能当精灵去查属性技能。"""
    body = (token or "").strip()
    if not body:
        return False
    if any(word in body for word in ("阵容", "前十", "抄作业", "全国前十")):
        return True
    if "队" in body and not _mentioned(body):
        return True
    if re.search(r"榜[一二三四五六七八九十\d]+", body) and "队" in body:
        return True
    return body.endswith("队")


def _bridge_entity(text: str) -> str:
    """从阵容文里抽出可再搜的队/阵容名。"""
    body = text or ""
    patterns = (
        r"(榜[一二三四五六七八九十\d]+的[\u4e00-\u9fff]{1,8}队)",
        r"(榜[一二三四五六七八九十\d]+[\u4e00-\u9fff]{0,4}队)",
        r"([\u4e00-\u9fff]{1,8}阵容)",
        r"(全国前十|前十阵容)",
        r"([\u4e00-\u9fff]{1,6}队)",
    )
    for pattern in patterns:
        matched = re.search(pattern, body)
        if not matched:
            continue
        token = matched.group(1).strip()
        if _team_like(token) or "前十" in token or "阵容" in token:
            return token
    return ""


def bridge_followup(bridge: str) -> str:
    """桥实体的下一查询：只查成员/出场精灵，不查队的属性。"""
    name = (bridge or "").strip() or "这套阵容"
    return f"{name}出场精灵"


def _column_head(fact: str) -> str:
    """栏目主语：取「的属性/技能…」前整段，避免「借用的榜九的毒队的属性」只切到「借用」。"""
    body = fact or ""
    tails = (
        "的本系技能和威力",
        "的技能和威力",
        "的能耗",
        "的种族值",
        "的特性",
        "的属性",
        "的技能",
    )
    for tail in tails:
        if body.endswith(tail):
            return body[: -len(tail)].strip()
    if "的" in body:
        return body.split("的", 1)[0].strip()
    return body


def _known_column(fact: str) -> bool:
    body = fact or ""
    if body in {"完成", "伤害公式", "更换是否使用技能", "星陨额外伤害", "出场率最高的精灵", "使用率最高的精灵"}:
        return True
    if _rate_fact(body):
        return True
    if "系的克制" in body or "系的抵抗" in body or ("系打" in body and "倍率" in body):
        return True
    if body.endswith("首领化"):
        return True
    head = _column_head(body)
    if head and _team_like(head):
        return False
    sprite_tails = ("的能耗", "的种族值", "的特性", "的属性", "的技能", "的技能和威力", "的本系技能和威力")
    if any(body.endswith(tail) for tail in sprite_tails):
        # 允许名录外的桥接精灵名（如评测里的幻影鱼）；只拦队伍/阵容。
        return bool(head) and not _team_like(head)
    if _power_tail(body):
        return bool(head) and not _team_like(head)
    return False


def _covers(fact: str, lines: list) -> bool:
    if fact == "这一下的最终伤害数字":
        return False
    blob = "\n".join(lines)
    if _power_tail(fact):
        return bool(re.search(r"威力\s*\d+", blob))
    if not blob.strip():
        return False
    if "未提供" in blob and fact != "伤害公式":
        return True
    if fact.endswith("系的克制"):
        return "克制" in blob
    if fact.endswith("系的抵抗"):
        return "抵抗" in blob
    if "系打" in fact and fact.endswith("的倍率"):
        return "克制" in blob and "抵抗" in blob
    if fact == "伤害公式":
        return "伤害量" in blob
    if fact == "更换是否使用技能":
        return "更换等同于使用技能" in blob
    if fact.endswith("的特性"):
        return "特性" in blob
    if fact.endswith("的属性"):
        return "属性" in blob
    if fact.endswith("的种族值"):
        return "种族值" in blob
    if fact.endswith("的技能"):
        return "自带" in blob or "技能池是空的" in blob
    if fact.endswith("首领化"):
        return "首领" in blob
    anchors = _anchors(fact)
    return bool(anchors) and all(anchor in blob for anchor in anchors)


def _anchors(fact: str) -> list:
    tail = _power_tail(fact)
    if tail:
        return [fact[: -len(tail)], "威力"]
    if fact.endswith("的能耗"):
        return [fact[: -len("的能耗")], "能耗"]
    if fact.endswith("首领化"):
        return [fact[: -len("首领化")], "首领"]
    if fact.endswith("的种族值"):
        return ["种族值"]
    if fact.endswith("的特性"):
        return [fact[: -len("的特性")], "特性"]
    if fact.endswith("的属性"):
        return ["属性"]
    if fact.endswith("的技能"):
        return ["自带"]
    if _rate_fact(fact):
        anchors = []
        if "闪耀大赛" in fact:
            anchors.append("闪耀大赛")
        if "登场率" in fact:
            anchors.append("登场率")
        elif "出场率" in fact:
            anchors.append("出场率")
        elif "使用率" in fact:
            anchors.append("使用率")
        if "最高" in fact:
            anchors.append("最高")
        elif "最多" in fact:
            anchors.append("最多")
        return anchors or [fact]
    if fact == "星陨额外伤害":
        return ["星陨", "额外"]
    return [fact] if fact else []


def _lines_for(fact: str) -> list:
    from pokemon_kb import load_rules

    rules = load_rules() or ""
    if _rate_fact(fact):
        return []
    tail = _power_tail(fact)
    if tail == "的本系技能和威力":
        return _same_type_lines(fact[: -len(tail)], rules)
    if tail:
        return _pool_power_lines(fact[: -len(tail)])
    if fact.endswith("的技能"):
        return _skill_pool_lines(fact[: -len("的技能")])
    if "系打" in fact and fact.endswith("的倍率"):
        left, right = fact.split("系打", 1)
        other = right.split("系", 1)[0]
        return _type_lines(rules, left) + _type_lines(rules, other)
    if fact.endswith("系的克制") or fact.endswith("系的抵抗"):
        return _type_lines(rules, fact[: fact.index("系")])
    if fact == "伤害公式":
        return _matching(rules, lambda line: "伤害量 =" in line and "吸血" not in line)
    if fact == "更换是否使用技能":
        return _matching(rules, lambda line: "更换等同于使用技能" in line)
    if fact == "星陨额外伤害":
        return _matching(
            rules,
            lambda line: "星陨" in line and "未提供" in line and "图标" not in line,
        )
    if fact.endswith("的种族值"):
        return _own_record_lines(fact[: -len("的种族值")], "种族值")
    if fact.endswith("的特性"):
        name = fact[: -len("的特性")]
        own = _own_record_lines(name, "特性")
        listed = _matching(rules, lambda line: line.startswith(f"- {name}｜") or line.startswith(f"- 特性：{name}"))
        return own + listed
    if fact.endswith("的属性"):
        return _own_record_lines(fact[: -len("的属性")], "属性")
    if fact.endswith("首领化"):
        return [
            line for line in _own_record_lines(fact[: -len("首领化")], "首领化形态")
            if "形态" in line
        ]
    if fact.endswith("的能耗"):
        skill = fact[: -len("的能耗")]
        return _clean(_matching(rules, lambda line: line.startswith(f"- {skill}｜") and "能耗" in line))
    named = _clean(_matching(
        rules,
        lambda line: (
            line.startswith(f"- {fact}｜")
            or line.startswith(f"- {fact}：")
            or line.startswith(f"{fact}：")
        ),
    ))
    return named


def _clean(lines: list) -> list:
    cleaned = []
    for line in lines:
        text = re.sub(r"｜图标.*$", "", line).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _type_lines(rules: str, type_name: str) -> list:
    row = ""
    for line in rules.splitlines():
        cells = [item.strip() for item in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == type_name:
            row = f"{type_name}系作为攻击属性时克制：{cells[1]}。作为防守属性时抵抗：{cells[2]}。"
            break
    lines = [row] if row else []
    lines.append("未出现的属性组合，伤害倍率按 1。")
    return lines


def _matching(rules: str, keep) -> list:
    found = []
    for line in rules.splitlines():
        text = line.strip()
        if text and keep(text) and text not in found:
            found.append(text.lstrip("- ").strip())
        if len(found) >= 3:
            break
    return found


def _own_record_lines(name: str, needle: str) -> list:
    path = _POKEMON / f"{name}.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    record = str(data.get("record") or "")
    found = []
    for line in record.splitlines():
        text = line.strip()
        if needle in text and text.startswith("-"):
            found.append(text.lstrip("- ").strip())
        if len(found) >= 3:
            break
    return found


def _skill_pool_lines(name: str) -> list:
    """这只精灵卡片上的自带、血脉、技能石。列表题用；比较威力另走全池升格。"""
    from pokemon_kb import load_pokemon

    mon = next((item for item in load_pokemon() if item.get("name") == name), None)
    if not mon:
        return []

    def join(items: list) -> str:
        names = []
        for item in items or []:
            skill = str(item).split("｜")[0].strip()
            if skill and skill not in names:
                names.append(skill)
        return "、".join(names) if names else "未提供"

    native = join(mon.get("native_skills"))
    blood = join(mon.get("blood_skills"))
    stone = join(mon.get("stone_skills"))
    if native == "未提供" and blood == "未提供" and stone == "未提供":
        data = _pokemon_data(name)
        if data and data.get("moves"):
            moved = join(data.get("moves") or [])
            if moved != "未提供":
                return [f"自带：{moved}", "血脉：未提供", "技能石：未提供"]
        return [f"{name}的技能池是空的。"]
    return [f"自带：{native}", f"血脉：{blood}", f"技能石：{stone}"]


def _all_skill_names(name: str) -> tuple:
    """Parent 升格：卡片三类技能 ∪ moves，尽量读全再比较。返回 (names, pool_complete)。"""
    from pokemon_kb import load_pokemon

    names = []
    seen = set()

    def add(token: str):
        skill = str(token or "").split("｜")[0].strip()
        if skill and skill not in seen and skill != "未提供":
            seen.add(skill)
            names.append(skill)

    mon = next((item for item in load_pokemon() if item.get("name") == name), None)
    sources = 0
    if mon:
        for key in ("native_skills", "blood_skills", "stone_skills"):
            bucket = mon.get(key) or []
            if bucket:
                sources += 1
            for item in bucket:
                add(item)
    data = _pokemon_data(name)
    if data:
        moves = data.get("moves") or []
        if moves:
            sources += 1
        for item in moves:
            add(item)
        record = str(data.get("record") or "")
        for line in record.splitlines():
            text = line.strip()
            if "｜" in text and any(word in text for word in ("物攻", "魔攻", "威力")):
                add(text.lstrip("- ").split("｜", 1)[0])
    # 三类或 moves 至少有一类非空，且能列出招，视为可读全这一级
    pool_complete = bool(names) and sources >= 1
    return names, pool_complete


def skill_tokens(lines: list) -> list:
    """技能池原句里的招式名。未提供不算。"""
    found = []
    for line in lines or []:
        body = str(line).split("：", 1)[-1].rstrip("。")
        for part in body.split("、"):
            name = part.strip()
            if name and name != "未提供" and name not in found:
                found.append(name)
    return found


def _pool_power_lines(name: str) -> list:
    """全池升格后再对总表威力（Parent–Child：小名定位，大池比较）。"""
    lines, _complete = _pool_power_bundle(name)
    return lines


def _pool_power_bundle(name: str) -> tuple:
    """返回 (威力行列表, pool_complete)。比较类 hop 用完整束做充足性判定。"""
    from agents.battle_agent import _skills

    names, pool_complete = _all_skill_names(name)
    cards = _skills()
    lines = []
    for skill in names:
        card = cards.get(skill) or {}
        line = str(card.get("line") or "").strip()
        if card.get("category") not in {"物攻", "魔攻"}:
            continue
        if not line or not re.search(r"威力\s*\d+", line):
            continue
        if line not in lines:
            lines.append(line)
    # 带威力行够多才算比较级齐全
    if len(lines) >= 2:
        pool_complete = True
    elif len(lines) == 1:
        pool_complete = False
    return lines, pool_complete


def _speech(covered: list) -> str:
    bits = []
    for item in covered:
        for line in item["lines"]:
            text = line.strip()
            if text and text not in bits:
                bits.append(text)
    if not bits:
        return ""
    return "灯灯翻到：" + " ".join(bits)


def _ask_sentence(fact: str, covered: str) -> str:
    if fact == "这一下的最终伤害数字":
        tail = "还缺技能威力、攻击和防御，灯灯算不出这一下的数字。"
    else:
        tail = f"灯灯还没翻到{fact}。跟灯灯说一下。"
    if covered:
        return covered + tail
    return tail


def _named_before(text: str, marker: str) -> str:
    index = text.find(marker)
    if index <= 0:
        return ""
    head = text[:index]
    matched = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{1,8}", head)
    if not matched:
        return ""
    return matched[-1]


def _first_pokemon(text: str) -> str:
    from pokemon_kb import _mentioned_names, load_pokemon

    names = _mentioned_names(text or "", load_pokemon())
    return names[0] if names else ""


_APPEAR = re.compile(r"(出场率|登场率|使用率).{0,6}(最高|最多)")
_HOP_LIMIT = 4
_SKILL_LIST = re.compile(
    r"技能池|自带技能|血脉技能|技能石技能|有什么技能|有哪些技能|会什么技能|会哪些技能|"
    r"会什么招|有什么招|有哪些招|会哪些招|什么招式|的招式"
)


def skill_pool_name(question: str) -> str:
    """点到一只精灵、又在问它的技能名单时，返回这只的名字。"""
    text = (question or "").strip()
    if not text:
        return ""
    listed = bool(_SKILL_LIST.search(text))
    plain = ("的技能" in text) and not re.search(r"威力|效果|能耗|伤害|怎么用|最大的技能", text)
    if not listed and not plain:
        return ""
    names = []
    for name in _mentioned(text):
        if name not in names:
            names.append(name)
    if len(names) != 1:
        return ""
    return names[0]


def outside_query(question: str) -> str:
    """名录里没有栏目的出场、登场、使用率。空字符串表示这句不用出门查这一条。"""
    text = (question or "").strip()
    if not text:
        return ""
    if "登场率" in text or "出场率" in text:
        if "闪耀大赛" in text and ("最高" in text or "最多" in text):
            return "闪耀大赛登场率最高的精灵"
        if "最高" in text or "最多" in text:
            word = "登场率" if "登场率" in text else "出场率"
            return f"{word}最高的精灵"
        if "闪耀大赛" in text:
            return "闪耀大赛登场率"
        return "登场率" if "登场率" in text else "出场率"
    if "使用率" in text:
        if "最高" in text or "最多" in text:
            return "使用率最高的精灵"
        return "使用率"
    return ""


def _rate_fact(fact: str) -> bool:
    return any(word in (fact or "") for word in ("出场率", "使用率", "登场率"))


def classify_hops(question: str) -> dict:
    """单步沿用原来的事实。多步只给出第一句和步数上限。"""
    text = (question or "").strip()
    if _chain_question(text):
        first = _first_chain_fact(text)
        if first:
            return {"kind": "chain", "limit": _HOP_LIMIT, "first": first}
    return {"kind": "single", "limit": 1, "first": ""}


def read_one(fact: str) -> dict:
    """核对一条事实。对上时带上原文行，并做充足性闸（SURE-RAG 三态）。"""
    from agents.evidence_gate import INSUFFICIENT, PARTIAL, SUPPORT, judge_sufficiency

    body = fact or ""
    meta = {}
    tail = _power_tail(body)
    if tail == "的本系技能和威力":
        # 本系只读同属性攻击段，不升格到全池（避免升龙咆哮等外系假最大）。
        from pokemon_kb import load_rules

        lines = _same_type_lines(body[: -len(tail)], load_rules() or "")
        meta["pool_complete"] = len([row for row in lines if re.search(r"威力\s*\d+", row)]) >= 2
        meta["same_type"] = True
    elif tail:
        owner = body[: -len(tail)]
        lines, pool_complete = _pool_power_bundle(owner)
        meta["pool_complete"] = pool_complete
    else:
        lines = _lines_for(body)
    covered = _covers(body, lines)
    kept = lines if covered else []
    if covered and not _power_tail(body):
        kept = kept[:12]
    gate = judge_sufficiency(body, kept, meta)
    # partial/insufficient 不算真正 covered，避免半池写进 hop 当成功。
    if gate.get("status") == PARTIAL:
        return {
            "fact": body,
            "covered": False,
            "lines": kept,
            "gate": gate,
            "escalate": gate.get("action") or "full_pool",
        }
    if gate.get("status") == INSUFFICIENT:
        return {
            "fact": body,
            "covered": False,
            "lines": [],
            "gate": gate,
            "escalate": gate.get("action") or "ask",
        }
    if gate.get("status") == SUPPORT and kept:
        covered = True
    return {
        "fact": body,
        "covered": bool(covered and kept),
        "lines": kept if covered else [],
        "gate": gate,
    }


def next_fact(question: str, steps: list, ask=None) -> dict:
    """根据已经对上的步骤写下一句事实。写不出就停下。"""
    done = [item for item in (steps or []) if item.get("fact") and item.get("text")]
    templ = _template_next(question, done)
    last = done[-1]["fact"] if done else ""
    if templ and templ.get("action") == "next":
        fact = templ.get("fact") or ""
        if not fact or fact == last or fact in {item["fact"] for item in done} or not _fact_grounded(fact, question, done):
            templ = None
    if ask is not None:
        try:
            raw = ask(question, done) or ""
        except Exception:
            raw = ""
        fact = _clean_model_fact(raw)
        if fact == "完成":
            return {"action": "done", "fact": "", "answer": chain_answer(question, done)}
        if fact and fact != last and fact not in {item["fact"] for item in done} and _fact_grounded(fact, question, done) and _known_column(fact):
            return {"action": "next", "fact": fact, "answer": ""}
    if templ:
        if templ.get("action") == "next":
            return {"action": "next", "fact": templ["fact"], "answer": ""}
        return {"action": templ.get("action") or "stop", "fact": "", "answer": templ.get("answer") or chain_answer(question, done)}
    return {"action": "stop", "fact": "", "answer": chain_answer(question, done)}


def chain_answer(question: str, steps: list) -> str:
    """多步已经对上的原文，拼成可以开口的一句。比技能时交给对战员。"""
    rows = [item for item in (steps or []) if (item.get("text") or "").strip()]
    skill = next((item for item in rows if _power_tail(str(item.get("fact") or ""))), None)
    if skill and str(skill.get("fact") or "").endswith("的本系技能和威力"):
        from agents.battle_agent import compare_speech
        return compare_speech(question, rows)
    if skill:
        return _pool_hit_speech(question, rows, skill)
    bits = []
    for item in rows:
        text = item["text"].strip()
        if text and text not in bits:
            bits.append(text)
    if not bits:
        return ""
    return "灯灯翻到：" + " ".join(bits)


def names_in(fact: str, text: str) -> list:
    """这一步原文里能交给下一步使用的名字。只收名录精灵，不收微博昵称/榜次。"""
    found = [name for name in _mentioned(text) if not _team_like(name)]
    if _rate_fact(fact):
        extra = _name_from_appearance([{"fact": fact, "text": text, "names": found}])
        if extra and extra not in found and not _team_like(extra):
            found.insert(0, extra)
        return found
    body = fact or ""
    # 桥跳「某队出场精灵」：名字只从正文名录出，不把「榜九」当精灵。
    if "出场精灵" in body or body.endswith("成员"):
        return found
    if "的" in body:
        head = _column_head(body)
        if (
            head
            and head not in found
            and head not in {"出场率最高", "使用率最高"}
            and not _team_like(head)
            and not re.match(r"^榜[一二三四五六七八九十\d]+$", head)
            and _mentioned(head)
        ):
            found.insert(0, head)
    return found


def _strongest_hit(text: str) -> bool:
    body = text or ""
    return "技能" in body and any(word in body for word in ("威力最大", "威力最高", "最大的技能", "最高的技能"))


def _chain_question(text: str) -> bool:
    body = text or ""
    compares = "威力" in body and "本系" in body and any(word in body for word in ("更高", "更大", "最高", "哪个"))
    rate = bool(_APPEAR.search(body))
    unbound = rate and "精灵" in body and ("本系" in body or _strongest_hit(body))
    named = _strongest_hit(body) and any(word in body for word in ("伤害", "打", "攻击")) and bool(_attacker_name(body))
    return compares or unbound or named


def _first_chain_fact(text: str) -> str:
    if _APPEAR.search(text) and "精灵" in text:
        if "使用率" in text:
            return "使用率最高的精灵"
        return "出场率最高的精灵"
    owner = _attacker_name(text)
    if owner:
        return f"{owner}的属性"
    return ""


def _template_next(question: str, steps: list):
    if not _chain_question(question or ""):
        return None
    done = {item["fact"] for item in steps}
    if _APPEAR.search(question or "") and "精灵" in (question or ""):
        first = _first_chain_fact(question)
        if first and first not in done:
            return {"action": "next", "fact": first, "answer": ""}
    attacker = _attacker(question, steps)
    if not attacker:
        return None
    attr = f"{attacker}的属性"
    same = f"{attacker}的本系技能和威力"
    pool = f"{attacker}的技能和威力"
    if attr not in done:
        return {"action": "next", "fact": attr, "answer": ""}
    if "本系" in (question or "") and same not in done:
        return {"action": "next", "fact": same, "answer": ""}
    if _strongest_hit(question or "") and pool not in done and not any(_power_tail(fact) for fact in done):
        return {"action": "next", "fact": pool, "answer": ""}
    for name in _targets(question):
        if name == attacker:
            continue
        fact = f"{name}的属性"
        if fact not in done:
            return {"action": "next", "fact": fact, "answer": ""}
    if any(_power_tail(str(fact)) for fact in done):
        return {"action": "done", "fact": "", "answer": chain_answer(question, steps)}
    return None


def _attacker(question: str, steps: list) -> str:
    if not (_APPEAR.search(question or "") and "精灵" in (question or "")):
        named = _attacker_name(question)
        if named:
            return named
    return _name_from_appearance(steps)


def _attacker_name(text: str) -> str:
    if _APPEAR.search(text or "") and "精灵" in (text or ""):
        return ""
    names = _mentioned(text)
    if not names:
        return ""
    targets = set(_targets(text))
    owners = [name for name in names if name not in targets]
    if owners:
        return owners[0]
    if len(names) == 1:
        return names[0]
    return ""


def _targets(text: str) -> list:
    found = []
    body = text or ""
    for marker in ("攻击", "打"):
        start = 0
        while True:
            at = body.find(marker, start)
            if at < 0:
                break
            for name in _mentioned(body[at:at + 16]):
                if name not in found:
                    found.append(name)
            start = at + len(marker)
    return found


def _name_from_appearance(steps: list) -> str:
    """出场率 hop 里抽出的攻击方：必须是名录精灵。禁止「是小小贰哦」类假名。"""
    for step in steps or []:
        if not _rate_fact(step.get("fact") or ""):
            continue
        text = step.get("text") or ""
        # 优先「最高/榜首/第一是名录名」；裸「是XX」容易撞上微博标题。
        matched = re.search(
            r"(?:最高|榜首|第一).{0,8}是([\u4e00-\u9fff]{2,8})"
            r"|(?:出场率|登场率|使用率)[^\n。]{0,16}是([\u4e00-\u9fff]{2,8})"
            r"|是([\u4e00-\u9fff]{2,8})",
            text,
        )
        if matched:
            token = next((g for g in matched.groups() if g), "").strip()
            names = _mentioned(token)
            if names and not _team_like(names[0]):
                return names[0]
            # 名录对不上就空着，交给桥跳失败 / 问人；不再把任意汉字当精灵。
            continue
        names = [
            name
            for name in (list(step.get("names") or []) or _mentioned(text))
            if not _team_like(name) and _mentioned(name)
        ]
        if names:
            return names[0]
    return ""


def _fact_grounded(fact: str, question: str, steps: list) -> bool:
    if fact in {"出场率最高的精灵", "使用率最高的精灵"} or _rate_fact(fact):
        return True
    head = _column_head(fact or "")
    if head and _team_like(head):
        return False
    blob = (question or "") + "\n" + "\n".join((item.get("text") or "") for item in steps)
    if head and head not in blob:
        return False
    return all(name in blob for name in _mentioned(fact))


def _clean_model_fact(raw: str) -> str:
    line = (raw or "").strip().splitlines()[0].strip(" 。\"'“”") if (raw or "").strip() else ""
    if not line or len(line) > 24:
        return ""
    if line in {"完成", "完成。"}:
        return "完成"
    return line


def _pool_hit_speech(question: str, steps: list, skill: dict) -> str:
    """技能池里威力最大的一招。问的是伤害数字时，再用公式算这一下。半池不收束。"""
    from agents.battle_agent import catalog_damage
    from agents.evidence_gate import SUPPORT, judge_sufficiency

    lines = list(skill.get("lines") or [])
    if not lines and skill.get("text"):
        lines = [skill["text"]]
    fact = str(skill.get("fact") or "")
    owner = fact.split("的", 1)[0] if "的" in fact else ""
    if owner:
        full, complete = _pool_power_bundle(owner)
        if len(full) > len(lines):
            lines = full
        gate = judge_sufficiency(fact or f"{owner}的技能和威力", lines, {"pool_complete": complete})
        if gate.get("status") != SUPPORT:
            bits = []
            for item in steps:
                text = (item.get("text") or "").strip()
                if text and text not in bits:
                    bits.append(text)
            tip = gate.get("detail") or "技能资料还不齐"
            return (("灯灯翻到：" + " ".join(bits) + "。") if bits else "") + f"灯灯还不敢比威力：{tip}。跟灯灯说一下技能池。"
    ranked = []
    for line in lines:
        matched = re.search(r"威力\s*(\d+)", line)
        if not matched:
            continue
        ranked.append((int(matched.group(1)), line.split("｜", 1)[0].strip(), line.strip()))
    ranked.sort(key=lambda item: item[0], reverse=True)
    bits = []
    for item in steps:
        hop_fact = str(item.get("fact") or "")
        if _power_tail(hop_fact):
            continue
        text = (item.get("text") or "").strip()
        if text and (_rate_fact(hop_fact) or hop_fact.endswith("的属性")) and text not in bits:
            bits.append(text)
    if not ranked:
        if skill.get("text") and skill["text"] not in bits:
            bits.append(skill["text"])
        return ("灯灯翻到：" + " ".join(bits)) if bits else ""
    best = ranked[0][0]
    winners = [item for item in ranked if item[0] == best]
    for item in winners:
        if item[2] not in bits:
            bits.append(item[2])
    if len(winners) == 1:
        verdict = f"技能池里，{winners[0][1]}的威力最大，是{best}。"
    else:
        verdict = f"技能池里，{'、'.join(item[1] for item in winners)}的威力同为{best}。"
    attacker = str(skill.get("fact") or "").split("的", 1)[0]
    targets = [name for name in _targets(question) if name != attacker]
    if targets and ("多少伤害" in (question or "") or ("伤害" in (question or "") and "打" in (question or ""))):
        got = catalog_damage(attacker, targets[0], winners[0][1])
        if got:
            verdict += f"打{targets[0]}的伤害量是{got['amount_text']}。"
    return "灯灯翻到：" + " ".join(bits) + verdict + _nature_note(question)


def _compare_answer(question: str, steps: list, skill: dict) -> str:
    lines = list(skill.get("lines") or [])
    if not lines and skill.get("text"):
        lines = [skill["text"]]
    ranked = []
    for line in lines:
        matched = re.search(r"威力\s*(\d+)", line)
        if not matched:
            continue
        ranked.append((int(matched.group(1)), line.split("｜", 1)[0].strip(), line.strip()))
    ranked.sort(key=lambda item: item[0], reverse=True)
    bits = []
    for item in steps:
        fact = str(item.get("fact") or "")
        text = (item.get("text") or "").strip()
        if text and (fact in {"出场率最高的精灵", "使用率最高的精灵"} or fact.endswith("的属性")) and text not in bits:
            bits.append(text)
    if not ranked:
        if skill.get("text") and skill["text"] not in bits:
            bits.append(skill["text"])
        return ("灯灯翻到：" + " ".join(bits)) if bits else ""
    best = ranked[0][0]
    winners = [item for item in ranked if item[0] == best]
    for item in winners:
        if item[2] not in bits:
            bits.append(item[2])
    if len(winners) == 1:
        verdict = f"本系攻击技能里，{winners[0][1]}的威力更高，是{best}。"
    else:
        verdict = f"本系攻击技能里，{'、'.join(item[1] for item in winners)}的威力同为{best}。"
    return "灯灯翻到：" + " ".join(bits) + verdict + _nature_note(question)


def _nature_note(question: str) -> str:
    matched = re.search(r"([\u4e00-\u9fff]{1,4})性格", question or "")
    if not matched:
        return ""
    from pokemon_kb import load_rules

    rules = load_rules() or ""
    for line in rules.splitlines():
        text = line.strip()
        if "性格" in text and "威力" in text:
            return text.lstrip("- ").strip()
    return f"{matched.group(1)}性格没有写在威力规则里，这一比只看技能威力。"


def _mentioned(text: str) -> list:
    from pokemon_kb import _mentioned_names, load_pokemon

    return _mentioned_names(text or "", load_pokemon())


def _same_type_lines(name: str, rules: str) -> list:
    """本系取这只精灵自己的每一系，只留攻击技能里写了威力数字的原句。"""
    data = _pokemon_data(name)
    if not data:
        return []
    moves = set()
    for item in data.get("moves") or []:
        skill = str(item).split("｜", 1)[0].strip()
        if skill:
            moves.add(skill)
    lines = []
    for type_name in data.get("types") or []:
        section = _attack_section(rules or "", str(type_name))
        for line in section.splitlines():
            text = line.strip()
            if not text.startswith("- "):
                continue
            body = re.sub(r"｜图标.*$", "", text.lstrip("- ").strip()).strip()
            skill = body.split("｜", 1)[0].strip()
            if skill in moves and re.search(r"威力\s*\d+", body) and body not in lines:
                lines.append(body)
    return lines


def _pokemon_data(name: str):
    path = _POKEMON / f"{name}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _attack_section(rules: str, type_name: str) -> str:
    marker = f"## {type_name}系"
    start = rules.find(marker)
    if start < 0:
        return ""
    rest = rules[start:]
    attack = rest.find("### 攻击")
    if attack < 0:
        return ""
    body = rest[attack:]
    end = len(body)
    for token in ("### 防御", "### 状态", "\n## "):
        at = body.find(token, 4)
        if 0 < at < end:
            end = at
    return body[:end]
