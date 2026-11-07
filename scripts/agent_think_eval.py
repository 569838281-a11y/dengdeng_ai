"""看灯灯面对知识库复杂问题时，每一步留下的过程。

记录过程句、实际查询句、缺口、计划版本，以及有没有退回上一状态。
知识题先按事实核对原文。网页用空结果。成文审查原样放过。
核对走不通的那一题用配队桩，强迫第一套失败。门口维持程序建议。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agents.speech_review as speech_review
from agents.job_ledger import drop
from agents.supervisor import run_cycle
from agents.thoughts import bind, reset

speech_review.review_speech = lambda _question, speech, _evidence=None, ask=None: {
    "pass": True,
    "issues": [],
    "text": speech,
    "repaired": False,
}

OUT = ROOT / "data" / "agent_think_eval.txt"
NAMES = ["水灵", "寂灭骨龙", "音速犬（本来的样子）", "绒光优优", "离心舞者", "贝古斯"]

CASES = [
    {
        "id": "type-chart",
        "question": "普通系技能打幻系，伤害倍率按多少算？",
        "intent": "search",
        "pieces": ["普通", "幻", "按 1"],
    },
    {
        "id": "boss-wave",
        "question": "水灵首领化之后，浪潮这个技能的能耗是多少？",
        "intent": "search",
        "pieces": ["首领", "浪潮"],
    },
    {
        "id": "switch-skill",
        "question": "战斗里更换精灵，算不算使用了一次技能？",
        "intent": "search",
        "pieces": ["更换", "技能"],
    },
    {
        "id": "two-names",
        "question": "浸润和湿润印记有什么差别？",
        "intent": "search",
        "pieces": ["浸润", "湿润印记"],
    },
    {
        "id": "missing-number",
        "question": "星陨造成的额外伤害具体是多少？",
        "intent": "search",
        "pieces": ["星陨", "额外伤害"],
    },
    {
        "id": "missing-race",
        "question": "利灯鱼的种族值是多少？",
        "intent": "search",
        "pieces": ["利灯鱼", "种族值"],
    },
    {
        "id": "formula-total",
        "question": "请按伤害公式算出普通系打幻系这一下的最终伤害数字。",
        "intent": "search",
        "pieces": ["公式", "普通", "幻"],
    },
    {
        "id": "plan-fails",
        "question": "以火系为主组一套",
        "intent": "lineup",
        "pieces": ["火系", "六只"],
        "fail_once": True,
    },
]


def _lineup_fail_once():
    seen = {"n": 0}

    def lineup(*_args):
        seen["n"] += 1
        if seen["n"] == 1:
            return {"ok": False, "names": [], "answer": "灯灯按现有伙伴排不出六只。", "hard": ["tilt"]}
        return {"ok": True, "names": list(NAMES), "answer": "", "hard": []}

    return lineup


def _run(case: dict) -> dict:
    thoughts = []
    queries = []
    webs = []

    def web(query):
        webs.append(query)
        return {"results": []}

    def save(*_args):
        return "灯灯记下了这一套出场。", True, "、".join(NAMES)

    token = bind(lambda kind, text: thoughts.append((kind, text)))
    try:
        cycle = run_cycle(
            case["question"],
            session_id=case["id"],
            judged={"intent": case["intent"], "request": case["question"]},
            web=web,
            lineup=_lineup_fail_once() if case.get("fail_once") else None,
            save=save if case.get("fail_once") else None,
        )
    except Exception as exc:
        cycle = {"error": f"{type(exc).__name__}: {exc}", "order": {"answer": ""}, "ledger": {}}
    finally:
        reset(token)
        drop(case["id"])
    ledger = cycle.get("ledger") or {}
    progress = ledger.get("progress") or {}
    return {
        "id": case["id"],
        "question": case["question"],
        "intent": case["intent"],
        "pieces": case["pieces"],
        "error": cycle.get("error", ""),
        "answer": (cycle.get("order") or {}).get("answer") or "",
        "thoughts": thoughts,
        "queries": list((progress.get("fact_queries") or [])) or queries,
        "webs": webs,
        "plan_version": ledger.get("plan_version"),
        "plan": ledger.get("plan") or [],
        "gap": ledger.get("gap"),
        "requests": ledger.get("requests") or [],
        "facts": ledger.get("facts") or [],
        "progress": progress,
        "check": ledger.get("check") or {},
        "slots": ledger.get("slots") or {},
    }


def _split_verdict(row: dict) -> str:
    question = row["question"].strip()
    queries = [item.strip() for item in row["queries"] if str(item).strip()]
    distinct = list(dict.fromkeys(queries))
    shorter = [item for item in distinct if item != question]
    hit = [piece for piece in row["pieces"] if any(piece in item for item in shorter)]
    if len(distinct) >= 2 and shorter:
        return f"有。查询被拆成 {len(distinct)} 句，其中单独出现的片段：{'、'.join(hit) or '无'}。"
    if shorter and hit:
        return f"有。没有用整句，改查了：{'、'.join(shorter)}。"
    shown = "；".join(distinct) if distinct else "没有发出查询"
    return f"没有。实际查询是：{shown}。"


def _did_split(row: dict) -> bool:
    question = row["question"].strip()
    distinct = list(dict.fromkeys(item.strip() for item in row["queries"] if str(item).strip()))
    shorter = [item for item in distinct if item != question]
    hit = [piece for piece in row["pieces"] if any(piece in item for item in shorter)]
    return bool((len(distinct) >= 2 and shorter) or (shorter and hit))


def _plan_verdict(row: dict) -> str:
    progress = row["progress"]
    version = int(row["plan_version"] or 1)
    reason = progress.get("revision_reason") or ""
    opened = [item.get("word") or "" for item in (progress.get("opened") or []) if isinstance(item, dict)]
    gap = row["gap"] if isinstance(row["gap"], dict) else None
    goals = [step.get("goal") or "" for step in row["plan"]]
    moved = "need_web" in opened or "need_ask" in opened or "replan" in opened or bool(gap) or bool(row["requests"])
    if version > 1 or reason not in {"", "监督者改了下一步"}:
        return (
            f"有。计划版本 {version}，原因「{reason or '无'}」。"
            f"派出顺序：{' → '.join(opened) or '无'}。"
        )
    if moved:
        return (
            f"沿开局清单往下走，没有另写一轮。计划版本 {version}。"
            f"派出顺序：{' → '.join(opened) or '无'}。"
            f"清单：{'；'.join(goals) or '无'}。"
        )
    return f"没有。计划版本 {version}。清单：{'；'.join(goals) or '无'}。"


def _rollback_verdict(row: dict) -> str:
    progress = row["progress"]
    if progress.get("reverted"):
        return "有。这一步被退回，并标了 reverted。"
    version = int(row["plan_version"] or 1)
    if version > 1:
        return f"没有退回上一版账本。计划版本加到了 {version}，走的是清空后再排。"
    return "没有。reverted 没有被置上。"


def _render(rows: list) -> str:
    lines = [
        "灯灯复杂知识题的过程测评",
        "知识题先收成最多三条事实，原文对上才开口。网页固定返回空结果。成文审查原样放过。",
        "门口这次维持程序建议。过程句就是界面上的思考链。",
        f"共 {len(rows)} 题。",
        "",
    ]
    for index, row in enumerate(rows, 1):
        progress = row["progress"]
        opened = [item.get("word") or "" for item in (progress.get("opened") or []) if isinstance(item, dict)]
        gap = row["gap"] if isinstance(row["gap"], dict) else None
        lines.append("=" * 72)
        lines.append(f"{index}. {row['id']}  {row['intent']}")
        lines.append(f"问题：{row['question']}")
        if row["error"]:
            lines.append(f"错误：{row['error']}")
        lines.append("")
        lines.append("思考")
        if row["thoughts"]:
            for step, (kind, text) in enumerate(row["thoughts"], 1):
                lines.append(f"{step}. [{kind}] {text}")
        else:
            lines.append("（没有过程句）")
        lines.append("")
        lines.append("查询句")
        if row["queries"]:
            for query in row["queries"]:
                lines.append(f"- {query}")
        else:
            lines.append("- （没有查名录）")
        lines.append("网页查询")
        if row["webs"]:
            for query in row["webs"]:
                lines.append(f"- {query}")
        else:
            lines.append("- （没有上网）")
        lines.append("")
        lines.append(
            "调度  "
            f"派出 {' → '.join(opened) or '无'}  "
            f"采纳 {progress.get('chosen_tool') or '无'}  "
            f"拒绝 {progress.get('rejected_tool') or '无'}  "
            f"原因 {progress.get('reject_reason') or '无'}"
        )
        lines.append(
            f"计划版本 {row['plan_version']}  "
            f"缺口 {((gap or {}).get('kind') or '无')} {((gap or {}).get('label') or '')}".rstrip()
            + f"  退回 {'是' if progress.get('reverted') else '否'}"
        )
        lines.append("计划清单")
        if row["plan"]:
            for step in row["plan"]:
                lines.append(f"- {step.get('status') or ''}  {step.get('assignee') or ''}  {step.get('goal') or ''}")
        else:
            lines.append("- （没有）")
        if row["requests"]:
            lines.append("缺项记录 " + "；".join(
                f"{item.get('missing')}:{item.get('label')}" for item in row["requests"]
            ))
        lines.append("")
        lines.append("回答")
        lines.append(row["answer"] or "（没有回答）")
        lines.append("")
        lines.append("三项判定")
        lines.append(f"拆成子问题：{_split_verdict(row)}")
        lines.append(f"发现缺项后另起一轮计划：{_plan_verdict(row)}")
        lines.append(f"走不通后回到上一状态再计划：{_rollback_verdict(row)}")
        lines.append("")
    lines.append("=" * 72)
    lines.append("总览")
    lines.append("")
    for row in rows:
        progress = row["progress"]
        split = "拆开" if _did_split(row) else "整句"
        version = int(row["plan_version"] or 1)
        reason = progress.get("revision_reason") or ""
        replanned = "另起计划" if version > 1 or reason not in {"", "监督者改了下一步"} else "沿原清单"
        rolled = "退回" if progress.get("reverted") else "未退回"
        lines.append(f"{row['id']}  {split}  {replanned}  {rolled}  版本 {version}")
    split_n = sum(1 for row in rows if _did_split(row))
    replan_n = sum(
        1 for row in rows
        if int(row["plan_version"] or 1) > 1
        or (row["progress"].get("revision_reason") or "") not in {"", "监督者改了下一步"}
    )
    roll_n = sum(1 for row in rows if row["progress"].get("reverted"))
    lines.append("")
    lines.append(
        f"三项合计：{split_n}/{len(rows)} 题把查询收成了不同于整句的事实；"
        f"{replan_n}/{len(rows)} 题另起了一轮计划；"
        f"{roll_n}/{len(rows)} 题退回了上一状态。"
    )
    return "\n".join(lines)


def main() -> None:
    rows = []
    for case in CASES:
        print(f"已开始 {case['id']}", flush=True)
        row = _run(case)
        rows.append(row)
        print(f"已跑完 {case['id']}", flush=True)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(_render(rows), encoding="utf-8")
    text = _render(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
