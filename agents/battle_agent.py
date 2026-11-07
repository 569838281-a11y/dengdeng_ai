"""对战员。一个入口，里面三件事：模拟谁会赢、按克制比技能、按公式算伤害数字。

不新增调度词。名字还没查到时返回空，仍由资料员一步一步查。
图鉴上的威力、克制和种族值用来开口。计算页只在威力对得上时附在后面。
"""
import re

_TYPES = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电", "毒",
    "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)
_RATES = {2.0: "2", 3.0: "3", 1.0: "1", 0.5: "0.5", 0.25: "0.25"}


def open_battle(question: str):
    """认得出就返回模拟或伤害数字。比较要等资料员把双方属性查齐，这里不抢。"""
    text = question or ""
    if _asks_number(text):
        named = _named_strike(text)
        if not named:
            return None
        got = catalog_damage(named["attacker"], named["defender"], named["skill"])
        if not got:
            return None
        _subanswers(got)
        return {
            "kind": "number",
            "ready": True,
            "speech": _number_speech(text, got),
            "trial": None,
            "ask": "",
        }
    if not _asks_trial(text):
        return None
    pair = matchup_pair(text)
    if not pair:
        return None
    payload = bout_payload(*pair)
    if not payload:
        return None
    view = trial_view(payload)
    return {
        "kind": "simulate",
        "ready": True,
        "speech": view["intro"],
        "trial": view,
        "ask": "",
    }


def matchup_pair(question: str):
    """问句里点了两只，并且在问输赢。顺序按原句里先出现的名字。"""
    text = question or ""
    if not re.search(r"对战|谁会赢|谁赢|打得过", text):
        return None
    from pokemon_kb import _mentioned_names, _name_stem, load_pokemon

    names = []
    for name in _mentioned_names(text, load_pokemon()):
        if name not in names:
            names.append(name)
    if len(names) < 2:
        return None

    def position(name: str) -> int:
        stem = _name_stem(name)
        spots = [text.find(token) for token in (name, stem) if token and token in text]
        return min(spots) if spots else len(text)

    ranked = sorted(names, key=position)
    return ranked[0], ranked[1]


def bout_payload(left: str, right: str):
    from agents.dengdeng_persona import matchup_spoken
    from battle import scripted_bout

    bout = scripted_bout(left, right)
    if not bout.get("ok") or not bout.get("frames"):
        return None
    return {
        "sprite_a": left,
        "sprite_b": right,
        "winner": bout.get("winner") or "",
        "spoken": matchup_spoken(left, right, bout.get("winner") or ""),
        "lines": bout.get("lines") or [],
        "frames": bout.get("frames") or [],
        "ok": True,
    }


def trial_view(battle: dict) -> dict:
    return {
        "intro": "灯灯来想一想，这两只精灵对战会是什么情况呢，让灯灯来模拟一下。",
        "closing": battle.get("spoken") or "",
        "frames": battle.get("frames") or [],
        "pace_ms": 2000,
    }


def compare_speech(question: str, steps: list, host=None) -> str:
    """有防守方属性时，用威力乘克制。没有防守方时，仍按写明的威力排。"""
    from agents.fact_read import _compare_answer, _nature_note
    from agents.thoughts import note_read

    rows = [item for item in (steps or []) if (item.get("text") or "").strip() or item.get("lines")]
    skill = next((item for item in rows if str(item.get("fact") or "").endswith("的本系技能和威力")), None)
    if not skill:
        return ""
    defender, types = _defender_types(question, rows)
    ranked = _rank_skills(skill, types) if defender and types else []
    if not ranked:
        return _compare_answer(question, rows, skill)
    note_read(f"对战员正在按克制比{defender}这一下")
    ranked.sort(key=lambda item: item["score"], reverse=True)
    best = ranked[0]["score"]
    winners = [item for item in ranked if abs(item["score"] - best) < 1e-6]
    bits = []
    for item in rows:
        fact = str(item.get("fact") or "")
        text = (item.get("text") or "").strip()
        if text and (fact in {"出场率最高的精灵", "使用率最高的精灵"} or fact.endswith("的属性")) and text not in bits:
            bits.append(text)
    for item in winners:
        if item["line"] not in bits:
            bits.append(item["line"])
    from agents.answer_verify import review_draft

    draft = _compare_answer(question, rows, skill)
    report = review_draft(question, rows, skill, draft)
    verdict = report.get("spoken") or verdict_from_ranked(defender, winners)
    if report.get("note"):
        note_read(report["note"])
    speech = "灯灯翻到：" + " ".join(bits) + verdict + _nature_note(question)
    attacker = _skill_owner(skill)
    _subanswers({
        "attacker": attacker,
        "defender": defender,
        "skill": winners[0]["name"],
        "power": winners[0]["power"],
        "rate_text": winners[0].get("rate"),
        "amount_text": winners[0].get("score_text"),
    })
    return _attach_page(question, attacker, defender, winners[0]["name"], winners[0]["power"], speech, host=host)


def _subanswers(got: dict) -> None:
    """拆开的每一小问再请模型说一次。模型没说出来时，仍用算好的那一句。"""
    from agents.react_stream import streaming

    if not streaming() or not got:
        return
    from agents.thoughts import note_read

    pieces = [
        f"攻击方是{got.get('attacker') or '这一只'}，技能是{got.get('skill') or '这一招'}，威力是{got.get('power')}",
        f"防守方是{got.get('defender') or '对方'}，克制倍率是{got.get('rate_text') or got.get('rate')}",
        f"按公式合起来是{got.get('amount_text') or got.get('amount')}",
    ]
    try:
        from llm_provider import get_team_invoke

        ask = get_team_invoke(12)
    except Exception:
        ask = None
    for piece in pieces:
        reply = ""
        if ask is not None:
            try:
                raw = ask("这是拆开的一小问。只用一句话回答，数字保持原样。\n" + piece)
                reply = str(getattr(raw, "content", None) or raw or "").strip().splitlines()[0]
            except Exception:
                reply = ""
        note_read((reply or piece)[:80])


def verdict_from_ranked(defender: str, ranked: list) -> str:
    """按已经乘过克制的名次写最终那一句。"""
    if not ranked:
        return ""
    ordered = sorted(ranked, key=lambda item: item["score"], reverse=True)
    best = ordered[0]["score"]
    winners = [item for item in ordered if abs(item["score"] - best) < 1e-6]
    if len(winners) == 1:
        item = winners[0]
        return (
            f"本系攻击技能打{defender}时，{item['name']}算上克制后更高，"
            f"威力{item['power']}，克制倍率{item['rate']}，合起来是{item['score_text']}。"
        )
    names = "、".join(item["name"] for item in winners)
    return f"本系攻击技能打{defender}时，{names}算上克制后同为{winners[0]['score_text']}。"


def type_multiplier(attack: str, defend: list) -> float:
    """板块 A 的五个倍率。没写进表的组合按 1。"""
    chart = _chart()
    sides = []
    for defend_type in defend or []:
        if defend_type not in _TYPES:
            continue
        attack_row = chart.get(attack) or {}
        defend_row = chart.get(defend_type) or {}
        if defend_type in (attack_row.get("克制") or []):
            sides.append("克制")
        elif attack in (defend_row.get("抵抗") or []):
            sides.append("抵抗")
        else:
            sides.append("中")
    if not sides:
        return 1.0
    if len(sides) == 1:
        return {"克制": 2.0, "抵抗": 0.5, "中": 1.0}[sides[0]]
    left, right = sides[0], sides[1]
    if left == "克制" and right == "克制":
        return 3.0
    if left == "抵抗" and right == "抵抗":
        return 0.25
    if {left, right} == {"克制", "抵抗"}:
        return 1.0
    if "克制" in (left, right):
        return 2.0
    if "抵抗" in (left, right):
        return 0.5
    return 1.0


def catalog_damage(attacker: str, defender: str, skill: str):
    """图鉴里威力、攻防、本系和克制都齐了才算出数字。缺任何一项就返回空。"""
    from agents.fact_read import _pokemon_data, read_one

    card = _skills().get(skill or "")
    attacker_data = _pokemon_data(attacker)
    defender_data = _pokemon_data(defender)
    if not card or not attacker_data or not defender_data:
        return None
    if skill not in _move_names(attacker_data):
        return None
    power = card.get("power")
    category = card.get("category") or ""
    attack_type = card.get("type") or ""
    if power is None or category not in {"物攻", "魔攻"} or attack_type not in _TYPES:
        return None
    attack_stats = attacker_data.get("base_stats") or {}
    defend_stats = defender_data.get("base_stats") or {}
    if category == "物攻":
        attack_base = attack_stats.get("attack")
        defend_base = defend_stats.get("defense")
    else:
        attack_base = attack_stats.get("special_attack")
        defend_base = defend_stats.get("special_defense")
    if not isinstance(attack_base, (int, float)) or not isinstance(defend_base, (int, float)):
        return None
    defend_types = [name for name in (defender_data.get("types") or []) if name in _TYPES]
    attack_types = [name for name in (attacker_data.get("types") or []) if name in _TYPES]
    if not defend_types or not attack_types:
        return None
    formula = read_one("伤害公式")
    if not formula.get("covered"):
        return None
    attack_value = float(attack_base) * 1.2 + 50
    defend_value = float(defend_base) * 1.2 + 50
    if defend_value == 0:
        return None
    rate = type_multiplier(attack_type, defend_types)
    stab = 1.25 if attack_type in attack_types else 1.0
    amount = power * (attack_value / defend_value) * stab * rate * 37 / 41
    return {
        "attacker": attacker,
        "defender": defender,
        "skill": skill,
        "line": card.get("line") or "",
        "formula": (formula.get("lines") or [""])[0],
        "power": power,
        "type": attack_type,
        "rate": rate,
        "rate_text": _rate_text(rate),
        "stab": stab,
        "stab_text": _amount_text(stab),
        "amount": amount,
        "amount_text": _amount_text(amount),
        "defend_types": defend_types,
    }


def _asks_trial(text: str) -> bool:
    if _asks_number(text) or "倍率" in (text or ""):
        return False
    return any(word in (text or "") for word in ("谁会赢", "谁赢", "打得过", "对战"))


def _asks_number(text: str) -> bool:
    body = text or ""
    if "多少伤害" in body or "伤害数字" in body:
        return True
    return "最终" in body and "伤害" in body and "数字" in body


def _named_strike(text: str):
    from agents.fact_read import _pokemon_data, _targets
    from pokemon_kb import _mentioned_names, load_pokemon

    names = _mentioned_names(text or "", load_pokemon())
    targets = _targets(text or "")
    owners = [name for name in names if name not in targets]
    if len(owners) != 1 or len(targets) != 1:
        return None
    skill = _skill_in_text(text)
    if not skill:
        return None
    data = _pokemon_data(owners[0])
    if not data or skill not in _move_names(data):
        return None
    return {"attacker": owners[0], "defender": targets[0], "skill": skill}


def _number_speech(question: str, got: dict) -> str:
    from agents.fact_read import _nature_note

    defend = "、".join(got.get("defend_types") or [])
    bits = [item for item in (got.get("formula") or "", got.get("line") or "") if item]
    sentence = (
        f"{got['skill']}打{got['defender']}，{got['type']}系打{defend}的克制倍率是{got['rate_text']}，"
        f"本系加成是{got['stab_text']}，伤害量是{got['amount_text']}。"
    )
    speech = "灯灯翻到：" + " ".join(bits) + sentence
    if "星陨" in (question or ""):
        speech += "星陨额外伤害的数值未提供，这一下没有加上。"
    return speech + _nature_note(question)


def _defender_types(question: str, steps: list):
    from agents.fact_read import _targets

    targets = _targets(question or "")
    if not targets:
        return "", []
    name = targets[0]
    for step in steps or []:
        if step.get("fact") != f"{name}的属性":
            continue
        text = (step.get("text") or "").strip() or " ".join(step.get("lines") or [])
        return name, _attr_types(text)
    return name, []


def _attr_types(text: str) -> list:
    matched = re.search(r"属性[:：]\s*([^。\n]+)", text or "")
    if not matched:
        return []
    found = []
    for part in re.split(r"[、，,\s]+", matched.group(1)):
        name = part.strip()
        if name in _TYPES and name not in found:
            found.append(name)
    return found


def _rank_skills(skill: dict, defend_types: list) -> list:
    lines = list(skill.get("lines") or [])
    if not lines and skill.get("text"):
        lines = [skill["text"]]
    index = _skills()
    ranked = []
    for line in lines:
        body = line.strip()
        matched = re.search(r"威力\s*(\d+)", body)
        if not matched:
            continue
        name = body.split("｜", 1)[0].strip()
        card = index.get(name) or {}
        attack = card.get("type") or ""
        rate = type_multiplier(attack, defend_types) if attack else 1.0
        power = int(matched.group(1))
        score = power * rate
        ranked.append({
            "name": name,
            "power": power,
            "rate": _rate_text(rate),
            "score": score,
            "score_text": _amount_text(score),
            "line": body,
        })
    return ranked


def _skill_owner(skill: dict) -> str:
    fact = str(skill.get("fact") or "")
    if fact.endswith("的本系技能和威力"):
        return fact.split("的", 1)[0]
    return ""


def _attach_page(question: str, attacker: str, defender: str, skill: str, power: int, speech: str, host=None) -> str:
    body = question or ""
    if "攻击" not in body or "威力" not in body:
        return speech
    if host is None:
        from agents.external_mcp import tools_live
        if not tools_live():
            return speech
    from agents.page_calc import excerpt, operate_damage_page

    extra = excerpt(operate_damage_page(attacker, defender, skill, host=host))
    if not extra:
        return speech
    stated = re.findall(r"威力\s*(\d+)", extra)
    if stated and int(stated[0]) != int(power):
        return speech
    return f"{speech.rstrip()}{extra}"


def _skill_in_text(text: str) -> str:
    body = text or ""
    names = sorted(_skills(), key=len, reverse=True)
    for name in names:
        if name and name in body:
            return name
    return ""


def _move_names(data: dict) -> set:
    found = set()
    for item in (data or {}).get("moves") or []:
        name = str(item).split("｜", 1)[0].strip()
        if name:
            found.add(name)
    return found


def _rate_text(value: float) -> str:
    for key, label in _RATES.items():
        if abs(float(value) - key) < 1e-9:
            return label
    return _amount_text(value)


def _amount_text(value: float) -> str:
    if abs(float(value) - round(float(value))) < 1e-6:
        return str(int(round(float(value))))
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _chart() -> dict:
    cached = getattr(_chart, "rows", None)
    if cached is not None:
        return cached
    from pokemon_kb import load_rules

    rows = {}
    for line in (load_rules() or "").splitlines():
        if not line.startswith("|"):
            continue
        cells = [item.strip() for item in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] not in _TYPES:
            continue
        rows[cells[0]] = {"克制": _type_list(cells[1]), "抵抗": _type_list(cells[2])}
    _chart.rows = rows
    return rows


def _skills() -> dict:
    cached = getattr(_skills, "cards", None)
    if cached is not None:
        return cached
    from pokemon_kb import load_rules

    cards = {}
    current = ""
    in_attack = False
    for line in (load_rules() or "").splitlines():
        if line.startswith("## "):
            matched = re.match(r"##\s*([\u4e00-\u9fff]+)系", line)
            current = matched.group(1) if matched and matched.group(1) in _TYPES else ""
            in_attack = False
            continue
        if line.startswith("### "):
            in_attack = bool(current) and line.startswith("### 攻击")
            continue
        if not in_attack or not line.strip().startswith("- "):
            continue
        body = re.sub(r"｜图标.*$", "", line.strip().lstrip("- ").strip()).strip()
        name = body.split("｜", 1)[0].strip()
        power = re.search(r"威力\s*(\d+)", body)
        fields = [item.strip() for item in body.split("｜")]
        category = fields[1] if len(fields) > 1 and fields[1] in {"物攻", "魔攻"} else ""
        if name and name not in cards:
            cards[name] = {
                "type": current,
                "power": int(power.group(1)) if power else None,
                "category": category,
                "line": body,
            }
    _skills.cards = cards
    return cards


def _type_list(cell: str) -> list:
    if not cell or cell == "无":
        return []
    found = []
    for part in re.split(r"[、，,\s]+", cell):
        name = part.strip()
        if name in _TYPES and name not in found:
            found.append(name)
    return found
