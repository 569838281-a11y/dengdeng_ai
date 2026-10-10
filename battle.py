"""对战结算。伤害只按板块 M，不调用模型。聚能不占 4 个技能栏。"""
import logging
import random
import re
import time
import uuid

from pokemon_kb import (
    _TYPE_ORDER,
    _by_name,
    _multiplier,
    elf_skill_options,
    load_pokemon,
    skill_catalog,
    type_chart,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ITEMS = ("愿力强化", "进化之力", "光合治愈")
_BATTLES = {}
_TTL = 1800
_PAREN_NOTE = "第一版所有精灵入场能量都是 10。瞌睡王按板块 B 应为 0，这里做了简化。"
_STAT_KEYS = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")


def _cleanup():
    now = time.time()
    stale = [key for key, row in _BATTLES.items() if now - row["created_at"] > _TTL]
    for key in stale:
        _BATTLES.pop(key, None)


def _reduction(effect: str) -> int:
    matched = re.search(r"减伤\s*(\d+)\s*%", effect or "")
    if not matched:
        return 0
    return max(0, min(100, int(matched.group(1))))


def combat_stats(mon: dict) -> dict:
    stats = mon.get("base_stats") or {}

    def conv(key):
        return float(stats.get(key) or 0) * 1.2 + 50

    return {
        "max_hp": float(stats.get("hp") or 0) * 2 + 100,
        "attack": conv("attack"),
        "defense": conv("defense"),
        "special_attack": conv("special_attack"),
        "special_defense": conv("special_defense"),
        "speed": conv("speed"),
    }


def attack_damage(power: int, attack: float, defense: float, stab: float, multiplier: float) -> int:
    """板块 M：威力 ×（攻÷防）× 本系 × 克制 × 37/41，四舍五入。"""
    if power <= 0:
        return 0
    guard = defense if defense > 0 else 1
    raw = power * (attack / guard) * stab * multiplier * 37 / 41
    return max(0, int(round(raw)))


def _skill_view(name: str, option: dict) -> dict:
    meta = skill_catalog().get(name) or {}
    types = list(option.get("types") or meta.get("types") or [])
    return {
        "name": name,
        "source": option.get("source") or "",
        "blood_type": option.get("blood_type") or "",
        "category": option.get("category") or meta.get("category") or "",
        "damage": option.get("damage") or meta.get("damage") or "",
        "power": int(option.get("power") or meta.get("power") or 0),
        "cost": int(option.get("cost") if option.get("cost") is not None else meta.get("cost") or 0),
        "effect": option.get("effect") or meta.get("effect") or "",
        "types": types,
    }


def _boss_profile(name: str) -> tuple:
    """首领名、种族值、特性。种族值优先结构化字段，否则解析 record。"""
    mon = _by_name(load_pokemon()).get(name) or {}
    boss = str(mon.get("boss") or "").strip()
    record = str(mon.get("record") or "")
    structured = mon.get("boss_stats") or mon.get("boss_base_stats")
    stats = None
    if isinstance(structured, dict) and any(structured.get(key) not in (None, "") for key in _STAT_KEYS):
        stats = {key: structured.get(key) or 0 for key in _STAT_KEYS}
    if stats is None and boss:
        matched = re.search(
            rf"{re.escape(boss)}的种族值：生命\s*(\d+)\s*，\s*物攻\s*(\d+)\s*，\s*魔攻\s*(\d+)\s*，\s*物防\s*(\d+)\s*，\s*魔防\s*(\d+)\s*，\s*速度\s*(\d+)",
            record,
        )
        if matched:
            stats = {
                "hp": int(matched.group(1)),
                "attack": int(matched.group(2)),
                "special_attack": int(matched.group(3)),
                "defense": int(matched.group(4)),
                "special_defense": int(matched.group(5)),
                "speed": int(matched.group(6)),
            }
    trait = ""
    if boss:
        trait_match = re.search(rf"{re.escape(boss)}的特性：(.+)", record)
        if trait_match:
            trait = trait_match.group(1).strip().split("。", 1)[0].strip()
    return boss, stats, trait


def validate_fighter(payload: dict) -> tuple:
    """返回 (fighter or None, errors)。"""
    errors = []
    catalog = _by_name(load_pokemon())
    name = str((payload or {}).get("name") or "").strip()
    mon = catalog.get(name)
    if not mon:
        return None, [f"没有这只已记录精灵：{name or '空'}"]
    skills = payload.get("skills") or []
    if len(skills) != 4 or len({str(item).strip() for item in skills}) != 4:
        errors.append(f"{name} 必须正好携带 4 个不同技能")
    blood = str(payload.get("blood") or "").strip()
    if blood not in {"初始血脉", "首领血脉"} and not (
        blood.endswith("血脉") and blood[:-2] in _TYPE_ORDER
    ):
        errors.append(f"{name} 的血脉必须是初始血脉、某系血脉或首领血脉")
    item = str(payload.get("item") or "").strip()
    if item not in _ITEMS:
        errors.append(f"{name} 的战斗道具必须是愿力强化、进化之力或光合治愈")
    options = {skill["name"]: skill for skill in elf_skill_options(mon)}
    resolved = []
    for raw in skills:
        skill_name = str(raw or "").strip()
        if skill_name == "聚能":
            errors.append(f"{name} 不能携带【聚能】")
            continue
        option = options.get(skill_name)
        if not option:
            errors.append(f"{name} 的技能池里没有「{skill_name}」")
            continue
        resolved.append(_skill_view(skill_name, option))
    blood_skills = [skill for skill in resolved if skill["source"] == "血脉"]
    if len(blood_skills) > 1:
        errors.append(f"{name} 的血脉技能超过 1 个")
    if blood == "首领血脉" and blood_skills:
        errors.append(f"{name} 是首领血脉，不能带血脉技能")
    if blood == "初始血脉" and blood_skills:
        errors.append(f"{name} 是初始血脉，不能带血脉技能")
    if blood.endswith("血脉") and blood not in {"初始血脉", "首领血脉"}:
        expected = blood[:-2]
        for skill in blood_skills:
            if skill["blood_type"] != expected:
                errors.append(f"{name} 的血脉是{blood}，不能带{skill['blood_type'] or '其他'}血脉技能「{skill['name']}」")
    if errors:
        return None, errors
    numbers = combat_stats(mon)
    return {
        "name": name,
        "display_name": name,
        "photo_name": name,
        "types": list(mon.get("types") or []),
        "trait": mon.get("trait") or "",
        "skills": resolved,
        "blood": blood,
        "item": item,
        "item_left": 2 if item == "愿力强化" else 1,
        "item_cd": 0,
        "item_cd_hold": False,
        "can_boss": str(mon.get("can_boss") or "").strip() == "是",
        "boss": False,
        "hp": numbers["max_hp"],
        "max_hp": numbers["max_hp"],
        "energy": 10,
        "max_energy": 10,
        "stats": numbers,
        "guard": None,
        "heal_turns": 0,
        "mods": _blank_mods(),
        "ailments": {"中毒": 0, "灼烧": 0, "冻结": 0},
        "will_turn": False,
    }, []


def _stab(skill: dict, types: list) -> float:
    if set(skill.get("types") or []) & set(types or []):
        return 1.25
    return 1.0


def _blank_mods() -> dict:
    """同名属性修正累加，不覆盖。百分比和固定值分开记。"""
    return {
        "attack": 0.0,
        "defense": 0.0,
        "special_attack": 0.0,
        "special_defense": 0.0,
        "speed": 0.0,
        "attack_flat": 0.0,
        "defense_flat": 0.0,
        "special_attack_flat": 0.0,
        "special_defense_flat": 0.0,
        "speed_flat": 0.0,
        "power_pct": 0.0,
        "power_flat": 0.0,
        "cost_delta": 0,
    }


def _effective_stats(side: dict) -> dict:
    """板块 M：先把增益减益加进换算后的能力，再交给攻÷防。"""
    base = side.get("stats") or {}
    mods = side.get("mods") or {}
    values = {}
    for key in ("attack", "defense", "special_attack", "special_defense", "speed"):
        number = float(base.get(key) or 0) * (1 + float(mods.get(key) or 0))
        number += float(mods.get(f"{key}_flat") or 0)
        values[key] = max(0.0, number) if key == "speed" else max(1.0, number)
    return values


def _buff_layers(side: dict) -> int:
    """变形活画按增益条目数计层：正的百分比、正的固定值、威力增益、能耗降低各算 1。"""
    mods = side.get("mods") or {}
    count = 0
    for key in ("attack", "defense", "special_attack", "special_defense", "speed"):
        if float(mods.get(key) or 0) > 0:
            count += 1
        if float(mods.get(f"{key}_flat") or 0) > 0:
            count += 1
    if float(mods.get("power_pct") or 0) > 0 or float(mods.get("power_flat") or 0) > 0:
        count += 1
    if int(mods.get("cost_delta") or 0) < 0:
        count += 1
    return count


def _act_speed(side: dict, other: dict) -> float:
    speed = _effective_stats(side)["speed"]
    if "变形活画" in (side.get("trait") or ""):
        speed += 5 * _buff_layers(other)
    return speed


def _pay_cost(side: dict, skill: dict) -> int:
    delta = int((side.get("mods") or {}).get("cost_delta") or 0)
    return max(0, int(skill.get("cost") or 0) + delta)


def _adjusted_power(attacker: dict, skill: dict, defender: dict, status_boost: bool) -> float:
    mods = attacker.get("mods") or {}
    power = float(skill.get("power") or 0) + float(mods.get("power_flat") or 0)
    power *= 1 + float(mods.get("power_pct") or 0)
    if "变形活画" in (attacker.get("trait") or ""):
        power *= 1 + 0.10 * _buff_layers(defender)
    if status_boost and "威力提高150%" in (skill.get("effect") or ""):
        power *= 2.5
    return max(0.0, power)


def _hit_damage(attacker: dict, defender: dict, skill: dict, chart: dict) -> int:
    attack_type = next(iter(skill.get("types") or []), "")
    multiplier = _multiplier(attack_type, defender.get("types") or [], chart) if attack_type else 1
    stats_atk = _effective_stats(attacker)
    stats_def = _effective_stats(defender)
    if skill.get("damage") == "物攻":
        attack = stats_atk["attack"]
        defense = stats_def["defense"]
    else:
        attack = stats_atk["special_attack"]
        defense = stats_def["special_defense"]
    amount = attack_damage(skill["power"], attack, defense, _stab(skill, attacker.get("types")), multiplier)
    if defender.get("guard") is not None:
        amount = int(round(amount * (100 - int(defender["guard"])) / 100))
        defender["guard"] = None
    return max(0, amount)


def _signed_number(value: float, percent: bool) -> str:
    if percent:
        return f"{value * 100:+.0f}%"
    if float(value).is_integer():
        return f"{value:+.0f}"
    return f"{value:+.1f}"


def _buff_labels(side: dict) -> list:
    mods = side.get("mods") or {}
    labels = []
    names = (
        ("attack", "物攻"),
        ("defense", "物防"),
        ("special_attack", "魔攻"),
        ("special_defense", "魔防"),
        ("speed", "速度"),
    )
    for key, label in names:
        percent = float(mods.get(key) or 0)
        flat = float(mods.get(f"{key}_flat") or 0)
        if percent:
            labels.append(f"{label}{_signed_number(percent, True)}")
        if flat:
            labels.append(f"{label}{_signed_number(flat, False)}")
    if float(mods.get("power_pct") or 0):
        labels.append(f"威力{_signed_number(float(mods['power_pct']), True)}")
    if float(mods.get("power_flat") or 0):
        labels.append(f"威力{_signed_number(float(mods['power_flat']), False)}")
    if int(mods.get("cost_delta") or 0):
        labels.append(f"能耗{int(mods['cost_delta']):+d}")
    return labels


def _ailment_labels(side: dict) -> list:
    labels = []
    for name in ("中毒", "灼烧", "冻结"):
        stacks = int((side.get("ailments") or {}).get(name) or 0)
        if stacks:
            labels.append(f"{name}×{stacks}")
    return labels


def _public_skills(side: dict) -> list:
    visible = [skill for skill in side["skills"] if skill["name"] != "聚能"]
    rows = []
    for index, skill in enumerate(visible):
        if index == 0 and side.get("will_turn"):
            rows.append({"name": "愿力冲击", "cost": _pay_cost(side, {"cost": 2}), "category": "攻击"})
        else:
            rows.append({"name": skill["name"], "cost": _pay_cost(side, skill), "category": skill["category"]})
    return rows


def _public_side(side: dict) -> dict:
    stats = _effective_stats(side)
    return {
        "name": side["name"],
        "display_name": side.get("display_name") or side["name"],
        "photo_name": side.get("photo_name") or side["name"],
        "hp": side["hp"],
        "max_hp": side["max_hp"],
        "energy": side["energy"],
        "max_energy": side["max_energy"],
        "skills": _public_skills(side),
        "buffs": _buff_labels(side),
        "ailments": _ailment_labels(side),
        "will_turn": bool(side.get("will_turn")),
        "item": side["item"],
        "item_left": side.get("item_left", 0),
        "item_cd": side.get("item_cd", 0),
        "blood": side["blood"],
        "boss": bool(side.get("boss")),
        "can_boss": bool(side.get("can_boss")),
        "trait": side.get("trait") or "",
        "stats": {
            "attack": stats.get("attack", 0),
            "defense": stats.get("defense", 0),
            "special_attack": stats.get("special_attack", 0),
            "special_defense": stats.get("special_defense", 0),
            "speed": stats.get("speed", 0),
        },
    }


def _public(battle: dict) -> dict:
    return {
        "battle_id": battle["id"],
        "over": battle["over"],
        "winner": battle["winner"],
        "note": battle["note"],
        "log": battle["log"],
        "player": _public_side(battle["player"]),
        "enemy": _public_side(battle["enemy"]),
    }


def _playback(battle: dict, line: str) -> dict:
    """给自动试场用的一拍。不带累计战报，避免每一拍都把前面的句子再带一遍。"""
    view = _public(battle)
    view.pop("log", None)
    return {"line": line, "battle": view}


def start_battle(player: dict, enemy: dict, script_seed: int = None) -> dict:
    _cleanup()
    left, left_errors = validate_fighter(player)
    right, right_errors = validate_fighter(enemy)
    errors = [f"己方：{item}" for item in left_errors] + [f"敌方：{item}" for item in right_errors]
    if errors:
        return {"ok": False, "errors": errors}
    battle_id = uuid.uuid4().hex
    note = _PAREN_NOTE + f" 己方携带【{left['item']}】，敌方携带【{right['item']}】。"
    battle = {
        "id": battle_id,
        "created_at": time.time(),
        "player": left,
        "enemy": right,
        "over": False,
        "winner": "",
        "note": note,
        "log": [note],
        "chart": type_chart(),
        "turn": 0,
    }
    if script_seed is not None:
        battle["script_seed"] = int(script_seed)
    _BATTLES[battle_id] = battle
    return {"ok": True, "battle": _public(battle)}


def _will_skill(side: dict) -> dict:
    stats = _effective_stats(side)
    damage = "物攻" if float(stats.get("attack") or 0) >= float(stats.get("special_attack") or 0) else "魔攻"
    element = side["blood"][:-2] if str(side.get("blood") or "").endswith("血脉") else ""
    return {
        "name": "愿力冲击",
        "category": "攻击",
        "damage": damage,
        "power": 80,
        "cost": 2,
        "effect": "应对状态：威力提高150%。",
        "types": [element] if element in _TYPE_ORDER else [],
        "source": "道具",
    }


def _item_error(side: dict, item: str) -> str:
    if item != side.get("item"):
        return "这不是当前携带的道具"
    if item == "进化之力":
        if side.get("blood") != "首领血脉":
            return "不是首领血脉"
        if not side.get("can_boss"):
            return "不能首领化"
        if side.get("boss") or side.get("item_left", 0) <= 0:
            return "已经用过"
        _boss, stats, _trait = _boss_profile(side["name"])
        if not stats:
            return "不能首领化"
        return ""
    if side.get("item_left", 0) <= 0:
        return "已经用过"
    if item == "愿力强化":
        if side.get("blood") == "首领血脉":
            return "首领血脉不能愿力冲击"
        if side.get("blood") == "初始血脉":
            return "愿力强化只能给系别血脉使用"
        if side.get("item_cd", 0) > 0:
            return f"愿力强化冷却中，还需 {side['item_cd']} 回合"
        return ""
    if item == "光合治愈":
        return ""
    return "无法使用该道具"


def _player_action(player: dict, action: str, skill_name: str, item: str):
    kind = (action or "skill").strip() or "skill"
    if kind == "charge":
        return {"kind": "charge"}, ""
    if kind == "item":
        chosen = (item or player.get("item") or "").strip()
        error = _item_error(player, chosen)
        if error:
            return None, error
        return {"kind": "item", "item": chosen}, ""
    if (skill_name or "").strip() == "愿力冲击":
        if not player.get("will_turn"):
            return None, "这不是己方携带的技能"
        if _pay_cost(player, {"cost": 2}) > player["energy"]:
            return None, "能量不足，放不出愿力冲击"
        return {"kind": "skill", "skill": _will_skill(player)}, ""
    if (skill_name or "").strip() == "聚能":
        return None, "聚能不在 4 个技能栏里"
    chosen = next((skill for skill in player["skills"] if skill["name"] == skill_name), None)
    if not chosen:
        return None, "这不是己方携带的技能"
    if _pay_cost(player, chosen) > player["energy"]:
        return None, f"能量不足，放不出「{skill_name}」"
    return {"kind": "skill", "skill": chosen}, ""


def _choose_ai(enemy: dict, player: dict, chart: dict, turn: int, rng=None) -> dict:
    # 道具不占回合。敌方暂不自动进化之力，避免玩家点技能时被顺手改掉种族值。
    affordable = [
        skill for skill in enemy["skills"]
        if _pay_cost(enemy, skill) <= enemy["energy"] and skill["name"] != "聚能"
    ]
    if not affordable:
        return {"kind": "charge"}
    killers = []
    for skill in affordable:
        if skill["category"] != "攻击":
            continue
        preview = dict(player)
        preview["guard"] = player.get("guard")
        amount = _hit_damage(enemy, preview, skill, chart)
        if player["hp"] - amount <= 0:
            killers.append(skill)
    if killers:
        return {"kind": "skill", "skill": killers[0]}
    picker = rng.choice if rng is not None else random.choice
    return {"kind": "skill", "skill": picker(affordable)}


def _action_name(action: dict) -> str:
    if not action:
        return ""
    if action.get("kind") == "charge":
        return "聚能"
    if action.get("kind") == "will":
        return "愿力冲击"
    if action.get("kind") == "item":
        return action.get("item") or ""
    return (action.get("skill") or {}).get("name") or ""


def _skill_of(action: dict) -> dict:
    if not action:
        return {}
    if action.get("kind") == "charge":
        return {"name": "聚能", "category": "状态", "effect": "回复 5 点能量", "cost": 0, "power": 0, "damage": "", "types": []}
    return action.get("skill") or {}


def _is_attack(action: dict) -> bool:
    return action.get("kind") in {"skill", "will"} and _skill_of(action).get("category") == "攻击"


def _is_status(action: dict) -> bool:
    if action.get("kind") == "charge":
        return True
    return action.get("kind") == "skill" and _skill_of(action).get("category") == "状态"


def _counters_attack(action: dict, other: dict) -> bool:
    skill = _skill_of(action)
    return (
        action.get("kind") == "skill"
        and skill.get("category") == "防御"
        and "应对攻击" in (skill.get("effect") or "")
        and _is_attack(other)
    )


def _counters_status(action: dict, other: dict) -> bool:
    skill = _skill_of(action)
    return "应对状态" in (skill.get("effect") or "") and _is_status(other)


def _decide_order(player: dict, enemy: dict, player_action: dict, enemy_action: dict):
    """返回 (order, respond_line, interrupted_who, status_boost_who)。"""
    packs = {
        "己方": ("己方", player, enemy, player_action),
        "敌方": ("敌方", enemy, player, enemy_action),
    }
    if _counters_attack(player_action, enemy_action):
        player_action["counter"] = "攻击"
        return [packs["己方"], packs["敌方"]], _respond_line(player_action, enemy_action, "防御应对攻击"), "", ""
    if _counters_attack(enemy_action, player_action):
        enemy_action["counter"] = "攻击"
        return [packs["敌方"], packs["己方"]], _respond_line(enemy_action, player_action, "防御应对攻击"), "", ""
    player_status = _counters_status(player_action, enemy_action)
    enemy_status = _counters_status(enemy_action, player_action)
    if player_status and not enemy_status:
        player_action["counter"] = "状态"
        return [packs["己方"], packs["敌方"]], _respond_line(player_action, enemy_action, ""), "敌方", "己方"
    if enemy_status and not player_status:
        enemy_action["counter"] = "状态"
        return [packs["敌方"], packs["己方"]], _respond_line(enemy_action, player_action, ""), "己方", "敌方"
    player_first = _act_speed(player, enemy) >= _act_speed(enemy, player)
    order = [packs["己方"], packs["敌方"]] if player_first else [packs["敌方"], packs["己方"]]
    return order, "", "", ""


def _respond_line(action: dict, other: dict, note: str) -> str:
    text = f"【{_action_name(action)}】成功应对【{_action_name(other)}】"
    if note:
        text += f"（{note}）"
    return text + "。"


def _heal(side: dict, ratio: float) -> float:
    gain = float(side["max_hp"]) * ratio
    before = float(side["hp"])
    side["hp"] = min(float(side["max_hp"]), before + gain)
    return side["hp"] - before


def _apply_boss(side: dict, who: str) -> str:
    boss, stats, trait = _boss_profile(side["name"])
    numbers = combat_stats({"base_stats": stats})
    old_max = float(side["max_hp"])
    ratio = (float(side["hp"]) / old_max) if old_max > 0 else 0
    side["stats"] = numbers
    side["max_hp"] = numbers["max_hp"]
    side["hp"] = min(float(numbers["max_hp"]), ratio * float(numbers["max_hp"]))
    if trait:
        side["trait"] = trait
    side["boss"] = True
    side["item_left"] = 0
    side["display_name"] = f"{side['name']}（首领化）"
    side["photo_name"] = side["name"]
    return f"{who}对【{side['name']}】使用【进化之力】，首领化为【{boss or '首领形态'}】。"


_STAT_GROUPS = (
    ("物攻和魔攻", ("attack", "special_attack")),
    ("魔攻和魔防", ("special_attack", "special_defense")),
    ("物攻和物防", ("attack", "defense")),
    ("魔攻和物防", ("special_attack", "defense")),
    ("双攻", ("attack", "special_attack")),
    ("双防", ("defense", "special_defense")),
    ("物攻", ("attack",)),
    ("魔攻", ("special_attack",)),
    ("物防", ("defense",)),
    ("魔防", ("special_defense",)),
    ("速度", ("speed",)),
)
_STAT_LABEL = {
    "attack": "物攻",
    "defense": "物防",
    "special_attack": "魔攻",
    "special_defense": "魔防",
    "speed": "速度",
}
_STAT_RE = re.compile(
    r"(物攻和魔攻|魔攻和魔防|物攻和物防|魔攻和物防|双攻|双防|物攻|魔攻|物防|魔防|速度)\s*([+-])\s*(\d+)\s*(%?)"
)
_POWER_RE = re.compile(r"全技能威力\s*([+-])\s*(\d+)\s*(%?)")
_COST_RE = re.compile(r"全技能能耗\s*([+-])\s*(\d+)")
_AILMENT_RE = re.compile(r"(\d+)\s*层\s*(灼烧|中毒|冻结)")
_POISON_ADD_RE = re.compile(r"附加中毒\s*(\d+)")
_IMMUNE = {"中毒": "毒", "灼烧": "火", "冻结": "冰"}
_GROUP_OF = {name: keys for name, keys in _STAT_GROUPS}


def _immune(side: dict, ailment: str) -> bool:
    return _IMMUNE.get(ailment, "") in (side.get("types") or [])


def _clear_positive(side: dict) -> None:
    mods = side.setdefault("mods", _blank_mods())
    for key, value in list(mods.items()):
        if key == "cost_delta":
            if int(value) < 0:
                mods[key] = 0
        elif float(value) > 0:
            mods[key] = 0.0


def _clear_negative(side: dict) -> None:
    mods = side.setdefault("mods", _blank_mods())
    for key, value in list(mods.items()):
        if key == "cost_delta":
            if int(value) > 0:
                mods[key] = 0
        elif float(value) < 0:
            mods[key] = 0.0
    for name in side.setdefault("ailments", {"中毒": 0, "灼烧": 0, "冻结": 0}):
        side["ailments"][name] = 0


def _side_of(clause: str, actor: dict, other: dict):
    if "双方" in clause and "驱散" in clause:
        return "both"
    if "敌方" in clause and "自己" not in clause:
        return other
    if "自己" in clause and "敌方" not in clause:
        return actor
    if "敌方获得" in clause or "驱散敌方" in clause:
        return other
    if "获得" in clause or "驱散" in clause:
        return actor
    return None


def _add_ailment(side: dict, ailment: str, stacks: int, who: str, notes: list) -> bool:
    if stacks <= 0:
        return False
    if _immune(side, ailment):
        notes.append(f"{who}免疫{ailment}。")
        return True
    box = side.setdefault("ailments", {"中毒": 0, "灼烧": 0, "冻结": 0})
    box[ailment] = int(box.get(ailment) or 0) + stacks
    notes.append(f"{who}获得 {stacks} 层{ailment}，当前 {box[ailment]} 层。")
    return True


def _apply_clause(target, text: str, who: str, notes: list) -> bool:
    applied = False
    if "驱散" in text and "增益" in text and "所有" in text:
        _clear_positive(target)
        notes.append(f"{who}的增益被驱散。")
        applied = True
    if "驱散" in text and "减益" in text and "层" not in text:
        _clear_negative(target)
        notes.append(f"{who}的减益被驱散。")
        applied = True
    mods = target.setdefault("mods", _blank_mods())
    gained = []
    for matched in _STAT_RE.finditer(text):
        sign = 1 if matched.group(2) == "+" else -1
        amount = sign * int(matched.group(3))
        percent = bool(matched.group(4))
        for key in _GROUP_OF[matched.group(1)]:
            if percent:
                mods[key] = float(mods.get(key) or 0) + amount / 100
            else:
                mods[f"{key}_flat"] = float(mods.get(f"{key}_flat") or 0) + amount
            gained.append(f"{_STAT_LABEL[key]}{_signed_number(amount / 100 if percent else amount, percent)}")
        applied = True
    if gained:
        notes.append(f"{who}获得{'、'.join(gained)}。")
    for matched in _POWER_RE.finditer(text):
        sign = 1 if matched.group(1) == "+" else -1
        amount = sign * int(matched.group(2))
        if matched.group(3):
            mods["power_pct"] = float(mods.get("power_pct") or 0) + amount / 100
            notes.append(f"{who}获得威力{_signed_number(amount / 100, True)}。")
        else:
            mods["power_flat"] = float(mods.get("power_flat") or 0) + amount
            notes.append(f"{who}获得威力{_signed_number(amount, False)}。")
        applied = True
    for matched in _COST_RE.finditer(text):
        sign = 1 if matched.group(1) == "+" else -1
        amount = sign * int(matched.group(2))
        mods["cost_delta"] = int(mods.get("cost_delta") or 0) + amount
        notes.append(f"{who}获得能耗{amount:+d}。")
        applied = True
    for matched in _AILMENT_RE.finditer(text):
        applied = _add_ailment(target, matched.group(2), int(matched.group(1)), who, notes) or applied
    for matched in _POISON_ADD_RE.finditer(text):
        applied = _add_ailment(target, "中毒", int(matched.group(1)), who, notes) or applied
    return applied


def _effect_notes(actor: dict, other: dict, effect: str, counter: str, status_boost: bool) -> tuple:
    notes = []
    pending = []
    names = {id(actor): "自己", id(other): "对方"}
    for raw in re.split(r"[，。；]", effect or ""):
        clause = raw.strip()
        if not clause or re.fullmatch(r"(对敌方精灵)?造成(物伤|魔伤|物理伤害|魔法伤害)", clause) or re.fullmatch(r"减伤\s*\d+\s*%", clause):
            continue
        body = clause
        for label, kind in (("应对攻击", "攻击"), ("应对状态", "状态"), ("应对防御", "防御")):
            if label in clause:
                if counter != kind:
                    body = ""
                else:
                    body = clause.split("：", 1)[-1].strip()
                break
        if body == "":
            continue
        if status_boost and re.search(r"威力提高\s*150\s*%", body):
            continue
        if any(flag in body for flag in ("若", "选择", "巧变", "蓄力", "每有", "每携带", "期间")):
            pending.append(body)
            continue
        target = _side_of(body, actor, other)
        if target == "both":
            applied = _apply_clause(actor, body, "己方", notes) or _apply_clause(other, body, "对方", notes)
        elif target is None:
            applied = False
        else:
            applied = _apply_clause(target, body, names.get(id(target), "自己"), notes)
        if not applied:
            pending.append(body)
    return notes, pending


def _use_item_now(side: dict, item: str, who: str) -> str:
    if item == "进化之力":
        _boss, stats, _trait = _boss_profile(side["name"])
        if not stats:
            return f"{who}不能首领化。"
        return _apply_boss(side, who)
    if item == "光合治愈":
        gained = _heal(side, 0.15)
        side["heal_turns"] = 3
        side["item_left"] = 0
        return (
            f"{who}使用【光合治愈】，回复 {gained:.0f} 点生命，之后 3 个回合结束再各回复 15%。"
            f"当前生命 {side['hp']:.0f}。"
        )
    if item == "愿力强化":
        side["item_left"] = max(0, int(side.get("item_left") or 0) - 1)
        side["item_cd"] = 3
        side["will_turn"] = True
        return f"{who}使用【愿力强化】，本回合第 1 栏变为【愿力冲击】。"
    return f"{who}无法使用该道具。"


def _resolve(actor: dict, other: dict, action: dict, chart: dict, who: str, status_boost: bool) -> str:
    kind = action.get("kind")
    if kind == "charge":
        actor["energy"] = min(int(actor["max_energy"]), int(actor["energy"]) + 5)
        return f"{who}使用【聚能】，回复 5 点能量，当前能量 {int(actor['energy'])}。"
    skill = _skill_of(action)
    cost = _pay_cost(actor, skill)
    if cost > actor["energy"]:
        return f"{who}能量不足，放不出【{skill.get('name') or '技能'}】。"
    actor["energy"] -= cost
    other_name = "对方" if who == "己方" else "己方"
    self_name = who
    notes, pending = _effect_notes(actor, other, skill.get("effect") or "", action.get("counter") or "", status_boost)
    notes = [note.replace("自己", self_name).replace("对方", other_name) for note in notes]
    extra = "".join(notes)
    if pending:
        extra += "未结算：" + "；".join(pending) + "。"
    if skill.get("category") == "攻击":
        used = dict(skill)
        used["power"] = _adjusted_power(actor, used, other, status_boost)
        amount = _hit_damage(actor, other, used, chart)
        amount = min(amount, max(0, int(round(other["hp"]))))
        other["hp"] = max(0, other["hp"] - amount)
        text = (
            f"{who}使用【{skill['name']}】，造成 {amount} 点伤害。"
            f"对方剩余生命 {other['hp']:.0f}，自己剩余能量 {int(actor['energy'])}。"
        )
        if status_boost and "打断" in (skill.get("effect") or ""):
            text += "应对状态：造成打断。"
        return text + extra
    if skill.get("category") == "防御":
        percent = _reduction(skill.get("effect") or "")
        actor["guard"] = percent
        text = f"{who}使用【{skill['name']}】，本回合下一次受到的攻击减伤 {percent}%。剩余能量 {int(actor['energy'])}。"
        return text + extra
    text = f"{who}使用【{skill['name']}】。"
    if extra:
        return text + extra + f"剩余能量 {int(actor['energy'])}。"
    return text + f"未结算：{skill.get('effect') or '没有效果原文'}。剩余能量 {int(actor['energy'])}。"


def _tick_side(side: dict, who: str) -> list:
    """先异常，再光合治愈，再灼烧衰减。冻结阈值按最大生命，避免和当前生命自比。"""
    lines = []
    if side["hp"] <= 0:
        return lines
    ailments = side.setdefault("ailments", {"中毒": 0, "灼烧": 0, "冻结": 0})
    poison = int(ailments.get("中毒") or 0)
    if poison and not _immune(side, "中毒"):
        damage = min(int(round(float(side["hp"]) * 0.03)), max(0, int(round(side["hp"]))))
        if damage:
            side["hp"] = max(0, float(side["hp"]) - damage)
            lines.append(f"{who}中毒，受到 {damage} 点毒伤，当前生命 {side['hp']:.0f}。")
    if side["hp"] <= 0:
        return lines
    burn = int(ailments.get("灼烧") or 0)
    if burn and not _immune(side, "灼烧"):
        damage = min(int(round(float(side["hp"]) * 0.02)), max(0, int(round(side["hp"]))))
        if damage:
            side["hp"] = max(0, float(side["hp"]) - damage)
            lines.append(f"{who}灼烧，受到 {damage} 点火伤，当前生命 {side['hp']:.0f}。")
    if side["hp"] <= 0:
        return lines
    freeze = int(ailments.get("冻结") or 0)
    if freeze and not _immune(side, "冻结"):
        ratio = min(0.95, freeze * 0.05)
        if float(side["hp"]) < ratio * float(side["max_hp"]):
            side["hp"] = 0
            lines.append(f"{who}冻结比例 {ratio:.0%}，当前生命低于阈值，力竭。")
            return lines
    if side["hp"] > 0 and side.get("heal_turns", 0) > 0:
        gained = _heal(side, 0.15)
        side["heal_turns"] -= 1
        lines.append(f"{who}【光合治愈】回合结束回复 {gained:.0f} 点生命，当前生命 {side['hp']:.0f}。")
    if side["hp"] > 0 and burn and not _immune(side, "灼烧"):
        ailments["灼烧"] = burn // 2
        lines.append(f"{who}灼烧层数减半，剩余 {ailments['灼烧']} 层。")
    if side.get("item_cd_hold"):
        side["item_cd_hold"] = False
    elif side.get("item_cd", 0) > 0:
        side["item_cd"] -= 1
    return lines


def _close_if_down(battle: dict, lines: list) -> None:
    player = battle["player"]
    enemy = battle["enemy"]
    if player["hp"] > 0 and enemy["hp"] > 0:
        return
    if battle.get("over"):
        return
    battle["over"] = True
    battle["winner"] = "敌方" if player["hp"] <= 0 else "己方"
    lines.append(f"对战结束，{battle['winner']}获胜。")


def play_move(battle_id: str, skill_name: str = "", action: str = "skill", item: str = "") -> dict:
    logger.info("play_move")
    _cleanup()
    battle = _BATTLES.get(battle_id)
    if not battle:
        return {"ok": False, "errors": ["这场对战不存在或已过期"]}
    if battle["over"]:
        return {"ok": False, "errors": ["对战已经结束"], "battle": _public(battle)}
    player = battle["player"]
    enemy = battle["enemy"]
    player_action, error = _player_action(player, action, skill_name, item)
    if error:
        return {"ok": False, "errors": [error], "battle": _public(battle)}
    beats = []

    def _beat(line: str) -> None:
        if battle.get("script_seed") is None:
            return
        beats.append(_playback(battle, line))

    if player_action.get("kind") == "item":
        line = _use_item_now(player, player_action.get("item") or "", "己方")
        battle["log"].append(line)
        _beat(line)
        return {"ok": True, "lines": [line], "battle": _public(battle), "beats": beats}
    rng = None
    if battle.get("script_seed") is not None:
        rng = random.Random(int(battle["script_seed"]) + int(battle.get("turn") or 0))
    enemy_action = _choose_ai(enemy, player, battle["chart"], battle.get("turn") or 0, rng)
    order, respond_line, interrupted, boost_who = _decide_order(player, enemy, player_action, enemy_action)
    lines = []

    def _say(line: str) -> None:
        lines.append(line)
        _beat(line)

    if respond_line:
        _say(respond_line)
    for who, actor, other, chosen in order:
        if actor["hp"] <= 0 or other["hp"] <= 0:
            continue
        if who == interrupted:
            _say(f"被打断，未能使用【{_action_name(chosen)}】。")
            continue
        _say(_resolve(actor, other, chosen, battle["chart"], who, who == boost_who))
        if player["hp"] <= 0 or enemy["hp"] <= 0:
            break
    if player["hp"] > 0 and enemy["hp"] > 0:
        for line in _tick_side(player, "己方"):
            _say(line)
        for line in _tick_side(enemy, "敌方"):
            _say(line)
        before = len(lines)
        _close_if_down(battle, lines)
        for line in lines[before:]:
            _beat(line)
    else:
        before = len(lines)
        _close_if_down(battle, lines)
        for line in lines[before:]:
            _beat(line)
    player["will_turn"] = False
    enemy["will_turn"] = False
    battle["turn"] = int(battle.get("turn") or 0) + 1
    battle["log"].extend(lines)
    return {"ok": True, "lines": lines, "battle": _public(battle), "beats": beats}


def _fixed_four(name: str) -> list:
    """资料顺序：先自带，再技能石。不取血脉招，以便固定初始血脉。"""
    catalog = _by_name(load_pokemon())
    mon = catalog.get(name)
    if not mon:
        return []
    native = []
    stone = []
    for option in elf_skill_options(mon):
        if option.get("source") == "自带":
            native.append(option["name"])
        elif option.get("source") == "技能石":
            stone.append(option["name"])
    picked = []
    for skill_name in native + stone:
        if skill_name not in picked:
            picked.append(skill_name)
        if len(picked) == 4:
            break
    return picked


def scripted_bout(left_name: str, right_name: str) -> dict:
    """规则看见「谁赢」后自己开的一场。

    技能按资料出现顺序取前 4 个（先自带，再技能石），不用随机。
    血脉固定为初始血脉，道具固定为光合治愈，本场不使用道具。
    敌方在付得起的招式里用 Random(20261008 + 回合) 选取，同一对精灵每次相同。
    己方按技能栏顺序循环，能量不够就聚能。最多 40 回合。
    """
    left_skills = _fixed_four(left_name)
    right_skills = _fixed_four(right_name)
    if len(left_skills) != 4 or len(right_skills) != 4:
        return {"ok": False, "winner": "", "lines": [], "errors": ["技能不足四招"]}
    opened = start_battle(
        {"name": left_name, "skills": left_skills, "blood": "初始血脉", "item": "光合治愈"},
        {"name": right_name, "skills": right_skills, "blood": "初始血脉", "item": "光合治愈"},
        script_seed=20261008,
    )
    if not opened.get("ok"):
        return {"ok": False, "winner": "", "lines": [], "errors": opened.get("errors") or ["无法开战"]}
    battle_id = opened["battle"]["battle_id"]
    lines = []
    winner = ""
    current = _BATTLES.get(battle_id)
    frames = [_playback(current, "")] if current else []
    for turn in range(40):
        battle = _BATTLES.get(battle_id)
        if not battle or battle.get("over"):
            break
        slot = [skill["name"] for skill in battle["player"]["skills"]]
        skill_name = slot[turn % len(slot)]
        result = play_move(battle_id, skill_name, "skill", "")
        if not result.get("ok"):
            errors = " ".join(result.get("errors") or [])
            if "能量" in errors:
                result = play_move(battle_id, "", "charge", "")
            else:
                break
        lines.extend(result.get("lines") or [])
        frames.extend(result.get("beats") or [])
        winner = ((result.get("battle") or {}).get("winner") or winner)
        if (result.get("battle") or {}).get("over"):
            break
    return {"ok": True, "winner": winner, "lines": lines, "frames": frames, "errors": []}
