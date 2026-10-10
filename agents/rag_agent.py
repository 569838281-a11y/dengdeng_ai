"""检索环。最多五圈：拆问题、取证、判断够不够。命令句不进这里。

配队只查本地。检索里本地没有的那一条，才在联网打开时收下网页。
证据够了才写出场。能排出基础方案时先记下，并说明还缺什么。
一条都没有，就说灯灯没有翻到。
"""
import logging
import re

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5
_HOT = re.compile(r"热门|环境|版本强势|主流")
_FOCUS = re.compile(r"以\s*(普通|草|火|水|光|地|冰|龙|电|毒|虫|武|翼|萌|幽|恶|机械|幻)\s*系为主")
_TARGET = re.compile(r"(?:针对|克制)\s*([^\s，。,、]{1,12})")
_MATCHUP = re.compile(r"对战|谁会赢|谁赢|打得过")


def is_direct_order(question: str) -> bool:
    """仓库增减、查看、删除和句中已经写明的改动，仍走原来的工具。"""
    from agents.battle_orders import (
        _asks_saved_lineup,
        _changes_from_text,
        _is_new_lineup,
        _team_id_from_text,
        _wants_delete_team,
        _wants_patch,
        _wants_release,
        wants_lineup,
    )

    text = str(question or "")
    if wants_lineup(text):
        return False
    if _team_id_from_text(text) and _TARGET.search(text) and not _changes_from_text(text):
        return False
    if _wants_release(text) or _wants_delete_team(text):
        return True
    if _wants_patch(text) and _changes_from_text(text):
        return True
    if "仓库" in text:
        return True
    if _asks_saved_lineup(text) and not _is_new_lineup(text):
        return True
    return False


def needs_team_rag(question: str) -> bool:
    """要排六人，或要把某一套改成针对某只，才进配队检索环。"""
    from agents.battle_orders import _changes_from_text, _team_id_from_text, wants_lineup

    text = str(question or "")
    if wants_lineup(text):
        return True
    if _team_id_from_text(text) and _TARGET.search(text) and not _changes_from_text(text):
        return True
    return False


def _focus_type(question: str) -> str:
    matched = _FOCUS.search(question or "")
    return matched.group(1) if matched else ""


def _target_label(question: str) -> str:
    matched = _TARGET.search(question or "")
    if not matched:
        return ""
    label = matched.group(1)
    label = re.sub(r"(的精灵|的队伍|配队|组一队|组队|出场).*$", "", label)
    return label.strip()


def _copes(mon: dict, target_types: list, chart: dict) -> bool:
    from pokemon_kb import _beats, _multiplier, elf_skill_options

    types = mon.get("types") or []
    for attack in target_types:
        if types and _multiplier(attack, types, chart) < 1:
            return True
    for skill in elf_skill_options(mon):
        if skill.get("category") != "攻击":
            continue
        for kind in skill.get("types") or []:
            if _beats(kind, target_types, chart):
                return True
    return False


def _too_uniform(mons: list, chart: dict) -> bool:
    from pokemon_kb import _TYPE_ORDER, _beats

    if len(mons) < 6:
        return False
    for attack in _TYPE_ORDER:
        if all(_beats(attack, mon.get("types") or [], chart) for mon in mons):
            return True
    return False


def _resolve_target(label: str, catalog: dict) -> dict:
    from pokemon_kb import _TYPE_ORDER, _mentioned_names, load_pokemon

    if not label:
        return {"types": [], "missing": ""}
    if label in _TYPE_ORDER:
        return {"types": [label], "missing": ""}
    found = _mentioned_names(label, load_pokemon())
    if found and found[0] in catalog:
        mon = catalog[found[0]]
        return {"types": list(mon.get("types") or []), "missing": "", "name": mon["name"]}
    return {"types": [], "missing": label}


def _opponent_names(question: str) -> list:
    from pokemon_kb import _mentioned_names, load_pokemon

    found = []
    pokemon = load_pokemon()
    for match in _TARGET.finditer(question or ""):
        for name in _mentioned_names(match.group(1), pokemon):
            if name not in found:
                found.append(name)
    return found


def _select_six(question: str, pool: list, catalog: dict, chart: dict, target_types: list, focus: str, target_name: str = "", session_id: str = "") -> dict:
    from pokemon_kb import _mentioned_names, _name_stem, can_learn_tilt, load_pokemon

    opponents = set(_opponent_names(question))
    if target_name:
        opponents.add(target_name)
    by_stem = {}
    for name in pool:
        mon = catalog.get(name)
        if not mon or name in opponents or _name_stem(name) in {_name_stem(item) for item in opponents}:
            continue
        by_stem.setdefault(_name_stem(name), mon)
    pool_names = {mon["name"] for mon in by_stem.values()}
    required = []
    missing = []
    for name in _mentioned_names(question, load_pokemon()):
        if name in opponents:
            continue
        if name in pool_names or _name_stem(name) in by_stem:
            picked = by_stem.get(_name_stem(name), {}).get("name") or name
            if picked not in required:
                required.append(picked)
        elif name not in missing:
            missing.append(name)
    from agents.chat_notebook import favored_names

    liked = set(favored_names(session_id))
    mons = list(by_stem.values())

    def cope_count(chosen: list) -> int:
        if not target_types:
            return 0
        return sum(1 for name in chosen if _copes(catalog[name], target_types, chart))

    def tilted(chosen: list) -> bool:
        return any(can_learn_tilt(catalog[name]) for name in chosen)

    names = []
    used = set()

    def add(name: str) -> bool:
        stem = _name_stem(name)
        if stem in used or name not in catalog:
            return False
        names.append(name)
        used.add(stem)
        return True

    for name in required:
        if len(names) >= 6:
            break
        add(name)
    if target_types:
        ranked = sorted(mons, key=lambda mon: _copes(mon, target_types, chart), reverse=True)
        for mon in ranked:
            if cope_count(names) >= 2:
                break
            add(mon["name"])
    if not tilted(names):
        for mon in mons:
            if can_learn_tilt(mon) and add(mon["name"]):
                break

    def score(mon: dict, chosen: list) -> int:
        trial = [catalog[name] for name in chosen] + [mon]
        value = 0
        if mon["name"] in liked:
            value += 8
        if focus and focus in (mon.get("types") or []):
            value += 3
        if target_types and _copes(mon, target_types, chart):
            value += 2
        if can_learn_tilt(mon):
            value += 1
        from pokemon_kb import _style_tags

        tags = _style_tags(mon)
        if "联防" in (question or "") and "联防" in tags:
            value += 3
        if "消强" in (question or "") and "强化" in (question or "") and "消强" in tags:
            value += 3
        if not focus and len(trial) == 6 and not _too_uniform(trial, chart):
            value += 4
        return value

    while len(names) < 6:
        rest = [mon for mon in mons if _name_stem(mon["name"]) not in used]
        if not rest:
            break
        rest.sort(key=lambda mon: score(mon, names), reverse=True)
        if not add(rest[0]["name"]):
            break

    if not focus:
        for _ in range(8):
            current = [catalog[name] for name in names]
            if len(current) < 6 or not _too_uniform(current, chart):
                break
            swapped = False
            for index in range(len(names) - 1, -1, -1):
                if names[index] in required:
                    continue
                for mon in mons:
                    if _name_stem(mon["name"]) in used and mon["name"] != names[index]:
                        continue
                    trial = list(names)
                    trial[index] = mon["name"]
                    stems = {_name_stem(item) for item in trial}
                    if len(stems) != len(trial):
                        continue
                    group = [catalog[item] for item in trial]
                    if _too_uniform(group, chart):
                        continue
                    if target_types and cope_count(trial) < min(2, cope_count(names)):
                        continue
                    if not tilted(trial):
                        continue
                    used.discard(_name_stem(names[index]))
                    names = trial
                    used.add(_name_stem(mon["name"]))
                    swapped = True
                    break
                if swapped:
                    break
            if not swapped:
                break

    group = [catalog[name] for name in names if name in catalog]
    gaps = []
    if len(names) != 6:
        gaps.append("short")
    if names and not tilted(names):
        gaps.append("tilt")
    if names and len(names) == 6 and not focus and _too_uniform(group, chart):
        gaps.append("uniform")
    if target_types and cope_count(names) < 2:
        gaps.append("counter")
    if missing:
        gaps.append("core")
    hard = [item for item in gaps if item in {"short", "tilt", "uniform", "core"}]
    return {
        "names": names[:6],
        "hard": hard,
        "gaps": gaps,
        "counters": cope_count(names),
        "missing": missing,
    }


def _pool(question: str) -> list:
    from agents.battle_orders import _catalog, _roster_unbounded, _stock

    if _roster_unbounded(question):
        return list(_catalog())
    return [name for name, count in _stock().items() if count > 0]


def _gap_sentence(question: str, evidence: dict) -> str:
    parts = []
    if evidence.get("hot"):
        parts.append("要是知道最热门的精灵是谁，还能更贴着你的要求")
    missing = (evidence.get("target") or {}).get("missing") or ""
    if missing:
        parts.append(f"要是知道{missing}到底是谁，还能对着它再排")
    gaps = (evidence.get("selection") or {}).get("gaps") or []
    if "counter" in gaps:
        label = evidence.get("target_label") or "那只精灵"
        parts.append(f"要是再有能扛住{label}、或带着克制它的攻击招的伙伴，就能把这一条补上")
    if not parts:
        return ""
    return "灯灯先按查得到的伙伴排了这一套。" + "。".join(parts) + "。"


def _favorite_swap(session_id: str, names: list, catalog: dict, question: str) -> dict:
    """选到某属性时，若这段对话用过同属性的精灵，就换成那一只。点名的伙伴不动。"""
    from agents.chat_notebook import type_favorites
    from pokemon_kb import _mentioned_names, _name_stem, can_learn_tilt, load_pokemon

    required = set(_mentioned_names(question, load_pokemon()))
    opponents = set(_opponent_names(question))
    for fav in reversed(type_favorites(session_id)):
        title = fav.get("name") or ""
        kinds = set(fav.get("types") or [])
        if not title or not kinds or title in names or title in opponents:
            continue
        if re.search(r"不(?:要|用)|别用", question or "") and title in (question or ""):
            continue
        same = []
        for name in names:
            mon = catalog.get(name) or {}
            if kinds & set(mon.get("types") or []) and _name_stem(name) != _name_stem(title):
                same.append(name)
        replaceable = [name for name in same if name not in required]
        if not replaceable:
            continue
        drop = replaceable[-1]
        remain = [name for name in names if name != drop]
        if any(can_learn_tilt(catalog[name]) for name in names) and not any(can_learn_tilt(catalog[name]) for name in remain if name in catalog):
            continue
        return {"name": title, "drop": drop, "types": list(kinds), "remain": remain}
    return {}


def _guest_copes(guest: dict, target_types: list, chart: dict) -> bool:
    from pokemon_kb import _beats, _multiplier

    types = guest.get("types") or []
    for attack in target_types or []:
        if types and _multiplier(attack, types, chart) < 1:
            return True
    return any(_beats(kind, target_types, chart) for kind in types)


def _companions(guest: dict, pool: list, catalog: dict, chart: dict, target_types: list, question: str) -> dict:
    """主力占一位。其余五只仍按仓库、倾斜、克制和输出联防来排。"""
    from pokemon_kb import _name_stem, _style_tags, can_learn_tilt

    guest_name = guest.get("name") or ""
    guest_stem = _name_stem(guest_name) or guest_name
    mons = []
    seen = set()
    for name in pool:
        mon = catalog.get(name)
        if not mon:
            continue
        stem = _name_stem(name)
        if stem == guest_stem or stem in seen:
            continue
        tags = _style_tags(mon)
        if "输出" not in tags and "联防" not in tags:
            continue
        seen.add(stem)
        mons.append(mon)

    def cope(mon: dict) -> bool:
        return bool(target_types) and _copes(mon, target_types, chart)

    need_cope = 2 - (1 if target_types and _guest_copes(guest, target_types, chart) else 0)
    if not target_types:
        need_cope = 0
    picked = []
    used = set()

    def add(mon: dict) -> bool:
        if len(picked) >= 5 or _name_stem(mon["name"]) in used:
            return False
        outputs = sum(1 for name in picked + [mon["name"]] if "输出" in _style_tags(catalog[name]))
        if outputs > 3:
            return False
        picked.append(mon["name"])
        used.add(_name_stem(mon["name"]))
        return True

    for mon in mons:
        if any(can_learn_tilt(catalog[name]) for name in picked):
            break
        if can_learn_tilt(mon):
            add(mon)
    if need_cope:
        for mon in sorted(mons, key=cope, reverse=True):
            if sum(1 for name in picked if cope(catalog[name])) >= need_cope:
                break
            if cope(mon):
                add(mon)
    rest = [mon for mon in mons if _name_stem(mon["name"]) not in used]
    rest.sort(key=lambda mon: cope(mon), reverse=True)
    for mon in rest:
        add(mon)
        if len(picked) >= 5:
            break
    outputs = sum(1 for name in picked if "输出" in _style_tags(catalog[name]))
    if outputs < 1:
        for mon in mons:
            if "输出" not in _style_tags(mon):
                continue
            if add(mon):
                break
            for index in range(len(picked) - 1, -1, -1):
                current = catalog[picked[index]]
                if can_learn_tilt(current):
                    continue
                if need_cope and cope(current) and sum(1 for name in picked if cope(catalog[name])) <= need_cope:
                    continue
                used.discard(_name_stem(picked[index]))
                picked[index] = mon["name"]
                used.add(_name_stem(mon["name"]))
                break
    group = [{"name": guest_name, "types": guest.get("types") or []}]
    group.extend(catalog[name] for name in picked if name in catalog)
    gaps = []
    if len(picked) != 5:
        gaps.append("short")
    if not any(can_learn_tilt(catalog[name]) for name in picked):
        gaps.append("tilt")
    if need_cope and sum(1 for name in picked if cope(catalog[name])) < need_cope:
        gaps.append("counter")
    if len(group) == 6 and not _focus_type(question) and _too_uniform(group, chart):
        gaps.append("uniform")
    return {"names": picked, "gaps": gaps}


def run_team_rag(question: str, progress=None, session_id: str = "", cancel=None) -> dict:
    """配队检索环。本地取证，够了或能给出基础方案才写出场。"""
    from agents.battle_orders import _catalog, _speak, _save_team, _team_id_from_text
    from pokemon_kb import load_rules, type_chart

    def tell(step: str, message: str) -> None:
        if progress is not None:
            progress(step, message)

    text = str(question or "").strip()
    from agents.chat_notebook import preference_clause
    from agents.thoughts import note_thought

    clause = preference_clause(session_id)
    guided = text if not clause else text.rstrip("。") + "。" + clause
    if clause:
        note_thought("灯灯按这段对话里的规矩来排")
    evidence = {
        "rounds": [],
        "hot": bool(_HOT.search(text)),
        "focus": _focus_type(text),
        "target_label": _target_label(text),
    }
    verdict = "empty"
    for index in range(1, MAX_ROUNDS + 1):
        tasks = []
        if "pool" not in evidence:
            tasks.append("仓库或名录")
        if "rules" not in evidence:
            tasks.append("出场规则")
        if evidence.get("target_label") and "target" not in evidence:
            tasks.append("针对的对象")
        if "chart" not in evidence:
            tasks.append("属性克制")
        if "selection" not in evidence and evidence.get("chart") and evidence.get("pool") is not None:
            tasks.append("六只候选")
        evidence["rounds"].append({"round": index, "tasks": tasks})
        tell("retrieve", f"灯灯在拆第 {index} 圈要查的事…")
        if not tasks:
            verdict = evidence.get("verdict") or "enough"
            break
        if "pool" not in evidence:
            evidence["pool"] = _pool(text)
            from agents.thoughts import note_read

            note_read("名录" if "不局限仓库" in text else "仓库")
        if "rules" not in evidence:
            evidence["rules"] = bool(load_rules())
            from agents.thoughts import note_read as read_rules

            read_rules("出场规则")
        if evidence.get("target_label") and "target" not in evidence:
            evidence["target"] = _resolve_target(evidence["target_label"], _catalog())
            from agents.thoughts import note_read as read_target

            target_name = (evidence["target"].get("name") or evidence["target"].get("missing") or "")
            if target_name:
                read_target(target_name)
        if "chart" not in evidence:
            evidence["chart"] = type_chart()
        if "selection" not in evidence and "六只候选" in tasks:
            target_types = (evidence.get("target") or {}).get("types") or []
            evidence["selection"] = _select_six(
                guided,
                evidence.get("pool") or [],
                _catalog(),
                evidence["chart"],
                target_types,
                evidence.get("focus") or "",
                (evidence.get("target") or {}).get("name") or "",
                session_id,
            )
            hard = evidence["selection"]["hard"]
            soft = [item for item in evidence["selection"]["gaps"] if item not in hard]
            if hard:
                verdict = "short" if "short" in hard else "blocked"
            elif soft or evidence.get("hot") or (evidence.get("target") or {}).get("missing"):
                verdict = "partial"
            else:
                verdict = "enough"
            evidence["verdict"] = verdict
            if verdict in {"enough", "partial", "short", "blocked"}:
                break
        elif "selection" in evidence:
            break
    tell("check", "灯灯在看这些证据够不够…")
    selection = evidence.get("selection") or {}
    names = selection.get("names") or []
    hard = selection.get("hard") or []
    if not evidence.get("rules"):
        spoken = _speak("灯灯没有翻到相关信息。", False)
        return _pack(spoken, "", False, evidence)
    from knowledge_search import ace_guest

    guest = ace_guest(text, session_id)
    if guest and guest.get("blocked"):
        return _pack(guest["blocked"], "", False, evidence)
    if guest:
        from agents.thoughts import note_read

        note_read(guest["name"])
        seated = _companions(
            guest,
            evidence.get("pool") or [],
            _catalog(),
            evidence.get("chart") or {},
            (evidence.get("target") or {}).get("types") or [],
            guided,
        )
        gaps = seated.get("gaps") or []
        if gaps or cancel and cancel():
            if cancel and cancel():
                return _pack("", "", False, evidence)
            if "counter" in gaps:
                spoken = _speak(f"灯灯想以{guest['name']}为主力，可是还凑不齐两只应对{evidence.get('target_label') or '对面'}的伙伴。", False)
            elif "tilt" in gaps:
                spoken = _speak("灯灯按现有伙伴排不出六只。要是再有一只能让队伍倾斜的伙伴，就能排完整。", False)
            elif "uniform" in gaps:
                spoken = _speak("灯灯按现有伙伴排不出六只。要是属性再散开一些，才不会被一只完全克制。", False)
            else:
                spoken = _speak("仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False)
            return _pack(spoken, "", False, evidence)
        from agents.battle_orders import _save_with_guest

        sentence, ok, roster = _save_with_guest(guided, seated["names"], guest)
        if ok:
            from agents.chat_notebook import note_used

            note_used(session_id, guest["name"], guest.get("types") or [])
        spoken = _speak(sentence, ok)
        if guest["name"] not in spoken:
            spoken = sentence
        tell("done", "配队完成")
        return _pack(spoken, roster if ok else "", ok, evidence)
    if hard or len(names) != 6:
        if "core" in hard:
            missing = "、".join(selection.get("missing") or []) or "点名的伙伴"
            spoken = _speak(f"灯灯按现有伙伴排不出六只。要是仓库里有{missing}，就能以它为核心。", False)
        elif "tilt" in hard:
            spoken = _speak("灯灯按现有伙伴排不出六只。要是再有一只能让队伍倾斜的伙伴，就能排完整。", False)
        elif "uniform" in hard:
            spoken = _speak("灯灯按现有伙伴排不出六只。要是属性再散开一些，才不会被一只完全克制。", False)
        else:
            spoken = _speak("仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", False)
        return _pack(spoken, "", False, evidence)
    if cancel and cancel():
        return _pack("", "", False, evidence)
    swap = _favorite_swap(session_id, names, _catalog(), text)
    if swap and swap["name"] in (evidence.get("pool") or []):
        names = [swap["name"] if name == swap["drop"] else name for name in names]
        from agents.thoughts import note_thought as remember_use

        remember_use(f"灯灯记得你用过{swap['name']}")
    elif swap and swap["name"] not in _catalog():
        from knowledge_search import _guest_ready
        from agents.chat_notebook import recall_pages

        page = next((item for item in recall_pages(session_id, swap["name"]) if item.get("name") == swap["name"]), {})
        ready = _guest_ready(swap["name"], page.get("text") or "")
        if ready and len(swap["remain"]) == 5:
            from agents.battle_orders import _save_with_guest
            from agents.chat_notebook import note_used
            from agents.thoughts import note_thought as remember_use

            remember_use(f"灯灯记得你用过{swap['name']}")
            sentence, ok, roster = _save_with_guest(guided, swap["remain"], ready)
            if ok:
                note_used(session_id, ready["name"], ready.get("types") or [])
            spoken = _speak(sentence, ok)
            if ready["name"] not in spoken:
                spoken = sentence
            tell("done", "配队完成")
            return _pack(spoken, roster if ok else "", ok, evidence)
    replace_id = _team_id_from_text(text)
    sentence, ok, roster = _save_team(guided, names=names, replace_id=replace_id)
    extra = _gap_sentence(text, evidence) if verdict == "partial" or evidence.get("hot") else ""
    if extra and ok:
        sentence = sentence.rstrip() + extra
    spoken = _speak(sentence, ok)
    tell("done", "配队完成")
    return _pack(spoken, roster if ok else "", ok, evidence)


def _pack(answer: str, roster: str, ok: bool, evidence: dict) -> dict:
    return {
        "answer": answer,
        "roster": roster,
        "ok": ok,
        "rounds": evidence.get("rounds") or [],
        "sources": [],
    }


def search_preface(question: str) -> dict:
    """检索环的前几圈。胜负题改去模拟对战，名录里没有的名字直接结束。"""
    from knowledge_search import _bout_payload, _matchup_pair, _trial_view
    from pokemon_kb import _mentioned_names, _name_stem, load_pokemon

    text = str(question or "").strip()
    rounds = []
    pokemon = load_pokemon()
    known = _mentioned_names(text, pokemon)
    leftover = _leftover_name(text, pokemon)
    action = "lookup"
    trial = None
    answer = ""
    for index in range(1, MAX_ROUNDS + 1):
        if index == 1:
            rounds.append({"round": 1, "task": "拆开问句"})
            continue
        if index == 2 and _MATCHUP.search(text):
            pair = _matchup_pair(text)
            if pair:
                rounds.append({"round": 2, "task": "这是在问输赢"})
                action = "trial"
                battle = _bout_payload(*pair) or {}
                trial = _trial_view(battle) if battle.get("frames") else None
                if trial:
                    answer = trial["intro"]
                else:
                    action = "empty"
                    missing = leftover or "这场对战"
                    answer = f"灯灯没有翻到{missing}。"
                break
            if re.search(r"谁会赢|谁赢|打得过", text):
                rounds.append({"round": 2, "task": "这是在问输赢"})
                action = "empty"
                missing = leftover or "这只精灵"
                answer = f"灯灯没有翻到{missing}。"
                break
        if index == 2 and leftover and not known and "板块" not in text and _missing_name(text, leftover):
            rounds.append({"round": 2, "task": "名录里没有这个名字"})
            action = "empty"
            answer = f"灯灯没有翻到{leftover}。"
            break
        rounds.append({"round": index, "task": "改去本地资料"})
        action = "lookup"
        break
    note = ""
    if action == "lookup" and _HOT.search(text):
        note = "要是知道最热门的精灵是谁，灯灯还能说得更准。"
    return {"action": action, "answer": answer, "trial": trial, "note": note, "rounds": rounds, "known": known}


def _missing_name(question: str, leftover: str) -> bool:
    """只有像在点一只没见过的精灵时，才提前说没翻到。技能和机制题要继续查。"""
    if not leftover:
        return False
    from knowledge_search import _mentioned_skills
    from pokemon_kb import skill_catalog

    if leftover in skill_catalog() or _mentioned_skills(question):
        return False
    if re.search(r"伤害|技能|克制|抵抗|能量|血脉|道具|特性|为什么|怎么|如何|打不出|威力|公式", question or ""):
        return False
    return bool(re.search(r"种族值|是什么|介绍|这只|的资料|的信息", question or ""))


def _leftover_name(question: str, pokemon: list) -> str:
    from pokemon_kb import _name_stem

    text = question or ""
    for mon in sorted(pokemon, key=lambda item: len(item["name"]), reverse=True):
        text = text.replace(mon["name"], " ")
        stem = _name_stem(mon["name"])
        if stem:
            text = text.replace(stem, " ")
    text = re.sub(
        r"种族值|特性|技能池|技能|资料|信息|查询|帮我|一下|介绍|看看|是什么|有哪些|怎么样|板块|对战|谁会赢|谁赢|打得过|克制|抵抗|能量|聚能|血脉|道具|伤害|防御|天气|状态|印记|公式|怎么|如何|什么|哪些|回复|入场|上限|的|和|与|跟|请|告诉",
        " ",
        text,
    )
    parts = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    return parts[0] if parts else ""
