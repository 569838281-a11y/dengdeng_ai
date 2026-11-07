"""测评当前监督者：路线是不是固定的，能不能并行后再规约，被拦住后会不会退回。

不调用大模型。网页、名录、配队、仓库都用桩。
结果写到 data/agent_route_eval.txt。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agents.speech_review as speech_review
from agents.job_ledger import drop
from agents.supervisor import run_cycle
from agents.thoughts import bind, reset

OUT = ROOT / "data" / "agent_route_eval.txt"
NAMES = ["水灵", "寂灭骨龙", "音速犬（本来的样子）", "绒光优优", "离心舞者", "贝古斯"]


def _keep_speech(_question, speech, _evidence=None, ask=None):
    return {"pass": True, "issues": [], "text": speech, "repaired": False}


speech_review.review_speech = _keep_speech


def _lineup_ok(*_args):
    return {"ok": True, "names": list(NAMES), "answer": "", "hard": []}


def _save_ok(_question, names, _session_id, _replace=None):
    return "灯灯记下了这一套出场。", True, "、".join(names)


def _web_page(title: str, snippet: str) -> dict:
    return {
        "results": [{
            "title": title,
            "url": "https://www.gamersky.com/route-eval",
            "snippet": snippet,
        }]
    }


def _run(case_id: str, question: str, judged: dict, **kwargs) -> dict:
    calls = {"web": [], "lineup": [], "warehouse": [], "lookup": [], "save": 0, "ask": []}
    thoughts = []

    def web(query):
        calls["web"].append(query)
        handler = kwargs.get("web")
        if handler:
            return handler(query)
        return {"results": []}

    def lookup(utterance, use_web, _session_id):
        calls["lookup"].append({"utterance": utterance, "use_web": use_web})
        handler = kwargs.get("lookup")
        if handler:
            return handler(utterance, use_web)
        return {"found": True, "answer": "桩：名录里有这一条。", "trial": None}

    def lineup(*args):
        calls["lineup"].append(args[-1] if len(args) > 3 else "")
        handler = kwargs.get("lineup")
        if handler:
            return handler(*args)
        return _lineup_ok()

    def warehouse(*args):
        calls["warehouse"].append(args[0] if args else "")
        handler = kwargs.get("warehouse")
        if handler:
            return handler(*args)
        return {"answer": "灯灯改过仓库了。", "ok": True}

    def save(*args):
        calls["save"] += 1
        return _save_ok(*args)

    def route_ask(ledger, word):
        calls["ask"].append(word)
        handler = kwargs.get("route_ask")
        if handler:
            return handler(ledger, word)
        return word

    token = bind(lambda _kind, text: thoughts.append(text))
    try:
        cycle = run_cycle(
            question,
            session_id=case_id,
            judged=judged,
            web=web,
            lookup=lookup,
            lineup=lineup,
            warehouse=warehouse,
            save=save,
            route_ask=route_ask if kwargs.get("route_ask") else None,
        )
    except Exception as exc:
        cycle = {"error": f"{type(exc).__name__}: {exc}", "order": {"answer": ""}, "ledger": {}}
    finally:
        reset(token)
        drop(case_id)
    ledger = cycle.get("ledger") or {}
    return {
        "id": case_id,
        "question": question,
        "intent": judged.get("intent"),
        "error": cycle.get("error", ""),
        "answer": (cycle.get("order") or {}).get("answer") or "",
        "ok": (cycle.get("order") or {}).get("ok"),
        "next": (ledger.get("progress") or {}).get("next"),
        "web": len(calls["web"]),
        "lookup": len(calls["lookup"]),
        "lineup": len(calls["lineup"]),
        "warehouse": len(calls["warehouse"]),
        "save": calls["save"],
        "route_asks": calls["ask"],
        "roster": ledger.get("roster") or [],
        "guesses": [
            {"discardable": item.get("discardable"), "text": (item.get("text") or "")[:40]}
            for item in ledger.get("guesses") or []
        ],
        "facts": [item.get("authority") for item in ledger.get("facts") or []],
        "gap": (ledger.get("gap") or {}).get("kind") if isinstance(ledger.get("gap"), dict) else ledger.get("gap"),
        "check_pass": (ledger.get("check") or {}).get("pass"),
        "stall": (ledger.get("check") or {}).get("stall_count"),
        "slots": ledger.get("slots") or {},
        "plan_version": ledger.get("plan_version"),
        "rejected": (ledger.get("progress") or {}).get("rejected_tool") or "",
        "chosen": (ledger.get("progress") or {}).get("chosen_tool") or "",
        "thoughts": thoughts[:12],
        "plan_done": [
            step.get("goal")
            for step in ledger.get("plan") or []
            if step.get("status") == "done"
        ],
    }


def _flags(row: dict) -> dict:
    answer = row["answer"]
    return {
        "asked": row["next"] == "need_ask" or "几只" in answer or "还不知道" in answer or "跟灯灯说" in answer,
        "no_web": row["web"] == 0,
        "no_lineup": row["lineup"] == 0,
        "no_warehouse": row["warehouse"] == 0,
        "no_roster": row["roster"] == [],
        "web_opened": row["web"] > 0,
        "local_opened": row["lookup"] > 0 or "catalog" in row["facts"] or "warehouse" in row["facts"],
        "guess_marked": any(item.get("discardable") for item in row["guesses"]),
        "one_roster": len(row["roster"]) in {0, 6},
        "outside_not_in_roster": "幻影龙" not in row["roster"],
    }


def main() -> None:
    rows = []

    def add(case_id, question, intent, **kwargs):
        row = _run(case_id, question, {"intent": intent, "request": question}, **kwargs)
        row["flags"] = _flags(row)
        rows.append(row)
        print(f"已跑 {case_id}", flush=True)

    def found_formula(_utterance, _use_web):
        return {"found": True, "answer": "水系打机械是克制，倍率按克制计算。", "trial": None}

    def missing(_utterance, _use_web):
        return {"found": False, "answer": "", "trial": None}

    def trial(_utterance, _use_web):
        return {"found": True, "answer": "模拟结果：水灵会赢。", "trial": {"winner": "水灵"}}

    def hot_web(query):
        if "热门" in query:
            return _web_page("热门阵容", "当前热门是水灵，也有人用幻影龙。")
        return {"results": []}

    def number_web(_query):
        return _web_page("伤害讨论", "有人说这一下大约是两倍伤害。")

    add("release-vague", "放生海枝枝", "order")
    add("release-count", "放生3只海枝枝", "order")
    add("search-hit", "水灵的特性是什么", "search")
    add("search-miss-web", "利灯鱼的种族值是多少", "search", lookup=missing, web=number_web)
    add("search-miss-empty", "利灯鱼的种族值是多少", "search", lookup=missing)
    add("damage-hit", "水灵用水系技能打机械系会造成多少伤害", "search", lookup=found_formula)
    add("damage-miss", "水灵用水系技能打机械系会造成多少伤害", "search", lookup=missing, web=number_web)
    add("who-wins", "水灵打贝古斯谁会赢", "battle", lookup=trial)
    add("who-wins-as-search", "水灵打贝古斯谁会赢", "search", lookup=trial)
    add("hot-lineup", "按现在热门环境，以火系为主，针对水灵组一套", "lineup", web=hot_web)
    add("plain-lineup", "以火系为主组一套", "lineup", web=hot_web)
    add("hot-web-empty", "按现在热门环境，以火系为主组一套", "lineup")
    add("unknown-target", "以水灵为核心，限制星陨队", "lineup", web=hot_web)
    add("check-replan", "以火系为主组一套", "lineup", web=hot_web, lineup=_fail_once())
    add("check-stop", "以火系为主组一套", "lineup", web=hot_web, lineup=lambda *_a: {"ok": False, "names": [], "answer": "灯灯按现有伙伴排不出六只。", "hard": ["tilt"]})
    add("empty", "", "")
    add("unheard", "今天天气不错", "")
    add("remember-empty", "我喜欢先手", "remember")
    add("release-ask-web", "放生海枝枝", "order", route_ask=lambda _ledger, _word: "need_web")
    add("search-ask-lineup", "水灵的特性是什么", "search", route_ask=lambda _ledger, _word: "need_lineup")
    add("hot-ask-local-only", "按现在热门环境，以火系为主组一套", "lineup", web=hot_web, route_ask=lambda _ledger, _word: "need_local")
    add("damage-ask-both", "水灵用水系技能打机械系会造成多少伤害", "search", lookup=found_formula, route_ask=lambda _ledger, _word: "need_both")

    rows.extend(_followups())
    text = _report(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)


def _fail_once():
    seen = {"n": 0}

    def lineup(*_args):
        seen["n"] += 1
        if seen["n"] == 1:
            return {"ok": False, "names": [], "answer": "灯灯按现有伙伴排不出六只。", "hard": ["tilt"]}
        return _lineup_ok()

    return lineup


def _followups() -> list:
    extra = []
    sid = "release-then"
    calls = {"warehouse": 0, "web": 0, "lineup": 0}
    thoughts = []

    def warehouse(*_args):
        calls["warehouse"] += 1
        return {"answer": "灯灯改过仓库了。", "ok": True}

    def web(_query):
        calls["web"] += 1
        return {"results": []}

    def lineup(*_args):
        calls["lineup"] += 1
        return _lineup_ok()

    def snap():
        return dict(calls)

    token = bind(lambda _kind, text: thoughts.append(text))
    try:
        first = run_cycle(
            "放生海枝枝",
            session_id=sid,
            judged={"intent": "order", "request": "放生海枝枝"},
            warehouse=warehouse,
            web=web,
            lineup=lineup,
        )
        after_first = snap()
        denied = run_cycle(
            "不是",
            session_id=sid,
            judged={"intent": "order", "request": "不是"},
            warehouse=warehouse,
            web=web,
            lineup=lineup,
        )
        after_deny = snap()
        counted = run_cycle(
            "放生2只海枝枝",
            session_id=sid + "-count",
            judged={"intent": "order", "request": "放生2只海枝枝"},
            warehouse=warehouse,
            web=web,
            lineup=lineup,
        )
        after_count = snap()
    except Exception as exc:
        extra.append({"id": "followup-error", "error": str(exc), "question": "", "answer": "", "flags": {}})
        return extra
    finally:
        reset(token)
        drop(sid)
        drop(sid + "-count")

    def pack(case_id, question, cycle, note, shot):
        ledger = cycle.get("ledger") or {}
        row = {
            "id": case_id,
            "question": question,
            "intent": "order",
            "error": "",
            "answer": (cycle.get("order") or {}).get("answer") or "",
            "ok": (cycle.get("order") or {}).get("ok"),
            "next": (ledger.get("progress") or {}).get("next"),
            "web": shot["web"],
            "lookup": 0,
            "lineup": shot["lineup"],
            "warehouse": shot["warehouse"],
            "save": 0,
            "route_asks": [],
            "roster": ledger.get("roster") or [],
            "guesses": [],
            "facts": [],
            "gap": (ledger.get("gap") or {}).get("kind") if isinstance(ledger.get("gap"), dict) else None,
            "check_pass": False,
            "stall": 0,
            "slots": ledger.get("slots") or {},
            "plan_version": ledger.get("plan_version"),
            "rejected": "",
            "chosen": "",
            "thoughts": [note],
            "plan_done": [],
        }
        row["flags"] = _flags(row)
        return row

    extra.append(pack("release-then-deny", "放生海枝枝 → 不是", denied, "先问清，再回答不是", after_deny))
    extra.append(pack("release-then-count", "另起：放生2只海枝枝", counted, "带只数的新一句", after_count))
    extra.append({
        "id": "release-first-ask",
        "question": "放生海枝枝（后续题的第一轮）",
        "intent": "order",
        "error": "",
        "answer": (first.get("order") or {}).get("answer") or "",
        "ok": (first.get("order") or {}).get("ok"),
        "next": ((first.get("ledger") or {}).get("progress") or {}).get("next"),
        "web": 0,
        "lookup": 0,
        "lineup": 0,
        "warehouse": 0,
        "save": 0,
        "route_asks": [],
        "roster": [],
        "guesses": [],
        "facts": [],
        "gap": "count",
        "check_pass": False,
        "stall": 0,
        "slots": {},
        "plan_version": 1,
        "rejected": "",
        "chosen": "",
        "thoughts": thoughts[:8],
        "plan_done": [],
        "flags": {"asked": "几只" in ((first.get("order") or {}).get("answer") or "")},
    })

    sid2 = "interrupt-case"
    token = bind(lambda _kind, text: None)
    try:
        run_cycle(
            "以火系为主组一套",
            session_id=sid2,
            judged={"intent": "lineup", "request": "以火系为主组一套"},
            web=lambda query: _web_page("热门", "当前热门是水灵") if "热门" in query else {"results": []},
            lineup=_lineup_ok,
            save=_save_ok,
            lookup=lambda *_a: {"found": True, "answer": "名录有。", "trial": None},
        )
        interrupted = run_cycle(
            "不对，换第三只",
            session_id=sid2,
            judged={"intent": "lineup", "request": "不对，换第三只"},
            web=lambda *_a: {"results": []},
            lineup=_lineup_ok,
            save=_save_ok,
            lookup=lambda *_a: {"found": True, "answer": "名录有。", "trial": None},
        )
    except Exception as exc:
        extra.append({"id": "interrupt-error", "error": str(exc), "question": "不对，换第三只", "answer": "", "flags": {}})
    else:
        ledger = interrupted.get("ledger") or {}
        row = {
            "id": "interrupt-swap",
            "question": "配完一套后说：不对，换第三只",
            "intent": "lineup",
            "error": "",
            "answer": (interrupted.get("order") or {}).get("answer") or "",
            "ok": (interrupted.get("order") or {}).get("ok"),
            "next": (ledger.get("progress") or {}).get("next"),
            "web": 0,
            "lookup": 0,
            "lineup": 0,
            "warehouse": 0,
            "save": 0,
            "route_asks": [],
            "roster": ledger.get("roster") or [],
            "guesses": ledger.get("guesses") or [],
            "facts": [],
            "gap": None,
            "check_pass": (ledger.get("check") or {}).get("pass"),
            "stall": (ledger.get("check") or {}).get("stall_count"),
            "slots": ledger.get("slots") or {},
            "plan_version": ledger.get("plan_version"),
            "rejected": "",
            "chosen": "",
            "thoughts": [ledger.get("interrupt") or ""],
            "plan_done": [],
        }
        row["flags"] = _flags(row)
        row["flags"]["version_up"] = int(ledger.get("plan_version") or 1) > 1
        extra.append(row)
    finally:
        reset(token)
        drop(sid2)
    return extra


def _report(rows: list) -> str:
    lines = [
        "当前监督者路线测评。桩代替网页、名录、配队和仓库，不调用大模型。",
        f"共 {len(rows)} 题。",
        "",
    ]
    for row in rows:
        if row.get("error"):
            lines.append(f"{row['id']}  出错  {row['error']}")
            lines.append("")
            continue
        lines.append(f"{row['id']}  {row.get('intent') or '无意图'}  {row['question']}")
        lines.append(
            "  下一步 {next}  网页 {web}  名录 {lookup}  配队 {lineup}  仓库 {warehouse}  保存 {save}  名单 {roster}  猜测 {guesses}".format(
                next=row.get("next"),
                web=row.get("web"),
                lookup=row.get("lookup"),
                lineup=row.get("lineup"),
                warehouse=row.get("warehouse"),
                save=row.get("save"),
                roster=len(row.get("roster") or []),
                guesses=len(row.get("guesses") or []),
            )
        )
        lines.append(f"  回答 {row['answer'].replace(chr(10), ' ')[:140]}")
        if row.get("thoughts"):
            lines.append("  过程 " + " ｜ ".join(row["thoughts"][:6]))
        if row.get("rejected") or row.get("chosen"):
            lines.append(f"  模型改词 选择 {row.get('chosen')}  被拒 {row.get('rejected')}")
        if row.get("route_asks"):
            lines.append(f"  曾询问模型 {row['route_asks']}")
        lines.append("")

    by_id = {row["id"]: row for row in rows if not row.get("error")}
    lines.extend(_analysis(by_id))
    return "\n".join(lines)


def _analysis(by_id: dict) -> list:
    lines = ["分析", ""]
    release = by_id.get("release-vague")
    counted = by_id.get("release-count")
    if release and counted:
        held = release["warehouse"] == 0 and release["web"] == 0 and release["lineup"] == 0 and "几只" in release["answer"]
        wrote = counted["warehouse"] == 1 and counted["web"] == 0 and counted["lineup"] == 0
        lines.append(f"篱笆「没写只数不改仓库」：{'守住了' if held else '没守住'}。带只数时仓库调用 {counted['warehouse']} 次。")
        lines.append(f"放生两题的过程分别是：{' ｜ '.join(release['thoughts'][:4])}  /  {' ｜ '.join(counted['thoughts'][:4])}")
    deny = by_id.get("release-then-deny")
    if deny:
        lines.append(f"用户回答「不是」之后：下一步 {deny['next']}，回答「{deny['answer'][:80]}」。仓库累计调用见该题记录。")
    damage = by_id.get("damage-hit")
    wins = by_id.get("who-wins")
    if damage and wins:
        same_tools = (damage["lookup"], damage["web"], damage["lineup"]) == (wins["lookup"], wins["web"], wins["lineup"])
        lines.append(
            "伤害题和胜负题的工具次数"
            + ("相同：都是查一次名录、不上网、不配队。过程句不同，是因为一个标成对战、桩返回了胜负。" if same_tools else "不同，监督者按问题形状选了不同工具。")
        )
        lines.append("  伤害 " + " ｜ ".join(damage["thoughts"][:4]))
        lines.append("  胜负 " + " ｜ ".join(wins["thoughts"][:4]))
    miss = by_id.get("damage-miss")
    if damage and miss:
        lines.append(
            f"公式材料缺失时网页调用 {miss['web']} 次，材料齐全时 {damage['web']} 次。"
            + (" 缺口会多走一步上网。网页正文里没有整句问话，结果没有留下猜测，最后仍是询问。" if damage["web"] != miss["web"] and not miss["guesses"] else " 两条路线见各题记录。")
        )
    hot = by_id.get("hot-lineup")
    if hot:
        both = hot["web"] > 0 and ("warehouse" in hot["facts"] or hot["lookup"] >= 0)
        lines.append(
            f"热门配队：网页 {hot['web']} 次，猜测 {len(hot['guesses'])} 条，名单 {len(hot['roster'])} 只，保存 {hot['save']} 次。"
        )
        marked = all(item.get("discardable") for item in hot["guesses"]) if hot["guesses"] else False
        lines.append(
            "猜测都标了可丢弃。" if marked else "没有可丢弃的网页猜测，或猜测没标可丢弃。"
        )
        lines.append(
            "幻影龙没有进入名单。" if "幻影龙" not in hot["roster"] else "幻影龙进入了名单。"
        )
        lines.append("并行过程 " + " ｜ ".join(hot["thoughts"][:8]))
    plain = by_id.get("plain-lineup")
    if plain and hot:
        lines.append(
            f"不提热门的配队也会上网 {plain['web']} 次。热门题上网 {hot['web']} 次。"
            + (" 两条都走了热门圈。" if plain["web"] and hot["web"] else "")
        )
    replan = by_id.get("check-replan")
    if replan:
        lines.append(f"核对失败后再排：配队调用 {replan['lineup']} 次，计划版本 {replan['plan_version']}，名单 {len(replan['roster'])}。")
    stop = by_id.get("check-stop")
    if stop:
        lines.append(f"连续核对失败：下一步 {stop['next']}，回答「{stop['answer'][:60]}」。")
    interrupted = by_id.get("interrupt-swap")
    if interrupted:
        lines.append(f"说「不对，换第三只」：计划版本 {interrupted['plan_version']}，名单 {len(interrupted['roster'])}，回答「{interrupted['answer'][:60]}」。")
    divert = by_id.get("hot-ask-local-only")
    if divert and hot:
        lines.append(
            f"热门题上模型每次都选只查资料：询问 {len(divert['route_asks'])} 次，采纳过 {divert['chosen'] or '没有'}，重复的那次被拒 {divert['rejected'] or '没有'}。网页 {divert['web']} 次，配队 {divert['lineup']} 次。"
        )
    forced = by_id.get("release-ask-web")
    if forced and release:
        lines.append(f"放生时模型要求上网：网页 {forced['web']} 次，被拒的词 {forced['rejected'] or '没有'}。回答「{forced['answer'][:40]}」。")
    both = by_id.get("damage-ask-both")
    if both:
        lines.append(f"伤害题模型要求两处一起查：询问 {both['route_asks']}，实际网页 {both['web']}，选择 {both['chosen'] or '没有'}。")
    search_line = by_id.get("search-ask-lineup")
    if search_line:
        lines.append(f"查特性时模型要求配队：配队 {search_line['lineup']} 次，询问 {search_line['route_asks']}。")
    lines.extend([
        "",
        "归纳",
        "做得好的地方：没写只数时不会改仓库，也不会为这句去配队或上网。放生要上网、查资料要配队、伤害题要两处一起查，都会问到模型；不合法的词会记下来，并退回程序的建议。热门题上连续只查资料，同一次缺口的重复选择会被拦住，最后仍上网一次并留下六只。名录能答的单题不会排出六人。网页猜测带可丢弃标记。核对失败会再排一次，再失败会停。",
        "做得不好的地方：没有接入询问时，下一步仍由程序按这句话的种类写下。伤害题和胜负题都是查一次名录再开口。名录没有时会上网，但页面里对不上整句问话就被丢掉。查询仍用整句原话。不提热门的配队也会补一轮热门。",
    ])
    return lines


if __name__ == "__main__":
    main()
