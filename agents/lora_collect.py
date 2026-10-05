"""采集灯灯 teacher 成文。检索、配队、对战都先走现有程序，再让 teacher 只改口吻。

默认不联网。核对通过的进 train/eval，失败进 rejected。无资料题只进 eval，不进训练。
"""
import argparse
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "lora"
QUESTIONS = OUT / "questions.jsonl"
PASSED = OUT / "passed.jsonl"
REJECTED = OUT / "rejected.jsonl"
TRAIN = OUT / "train.jsonl"
EVAL = OUT / "eval.jsonl"

NODATA = [
    "银河火车站的站长精灵叫什么",
    "并不存在的星星龙是什么系",
    "火星兔的种族值是多少",
    "洛克王国里的股票怎么开户",
    "昨天食堂的菜谱和精灵克制有什么关系",
    "请告诉我一只资料库里没有的龙头精灵的技能",
    "虚空台灯鱼会不会首领化",
    "第 9999 号精灵的特性是什么",
    "如何用并不存在的道具让对面永久封印",
    "小洛克的作业本第 3 页写了哪只精灵",
]


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def build_questions() -> list:
    from pokemon_kb import load_pokemon

    mons = load_pokemon()
    names = [mon["name"] for mon in mons]
    rows = []
    for name in names:
        rows.append({"task": "search", "question": f"{name}是什么系的"})
        rows.append({"task": "search", "question": f"介绍一下{name}的特性和技能"})
    for skill in ("截拳", "水泡盾", "甩水", "魔法增效", "聚能", "愿力冲击"):
        rows.append({"task": "search", "question": f"{skill}这个技能是什么效果"})
    for plate in ("伤害怎么计算", "能量和聚能是什么规则", "战斗道具愿力强化怎么用", "属性克制怎么看"):
        rows.append({"task": "search", "question": plate})
    for left, right in zip(names, names[1:] + names[:1]):
        if left != right:
            rows.append({"task": "search", "question": f"{left}对战{right}，谁最可能获胜"})
    prompts = [
        "来一套能打的队伍",
        "我想要偏输出的队伍",
        "帮我配联防多一点的队伍",
        "来一套有倾斜的队伍",
        "水属性多一些的队伍",
        "电属性输出队伍",
        "火系进攻队伍",
        "草系联防队伍",
        "带充能的队伍",
        "六只都能上场的均衡队伍",
        "想让双灯鱼出场的水系电系队伍",
        "输出和联防都要有的队伍",
        "再来一套不同的输出队",
        "偏防御、也能补能量的队伍",
        "光系相关的队伍",
        "地系耐打的队伍",
        "冰系进攻队伍",
        "毒系消耗队伍",
        "机械系输出队伍",
        "翼系速度队伍",
        "龙系进攻队伍",
        "普通系稳健队伍",
        "再配一套联防为主的队伍",
        "给我一套六人队伍，输出不要太多",
        "再配一支带双灯鱼的输出队",
        "帮我组一支充能多的队伍",
        "来一支速度很快的队伍",
        "六人里要有联防",
        "给我换一支水系队伍",
        "魔攻高一些的队伍",
        "物攻高一些的队伍",
        "新手也能用的六人队",
        "再来一支电系队伍",
        "光系输出再配上联防",
        "幽系队伍怎么组",
        "武系进攻的六人",
        "萌系也要能打的队伍",
        "幻系六人队伍",
        "虫系队伍",
        "恶系进攻队伍",
        "机械和电一起的队伍",
        "再给我一套均衡队",
        "联防为主、输出为辅的队伍",
        "充能和输出都要有的队伍",
    ]
    for text in prompts:
        rows.append({"task": "team", "question": text})
    seen_pairs = set()
    for shift in (0, 5):
        rotated = names[shift:] + names[:shift]
        for left, right in zip(names, reversed(rotated)):
            if left == right or (left, right) in seen_pairs:
                continue
            seen_pairs.add((left, right))
            rows.append({"task": "battle", "question": f"{left}对{right}"})
    for text in NODATA:
        rows.append({"task": "nodata", "question": text})
    return rows


def _sample(task: str, question: str, user_text: str, answer: str, meta: dict) -> dict:
    from agents.dengdeng_persona import SYSTEM

    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": answer},
        ],
        "meta": {"task": task, "question": question, **meta},
    }


def _collect_search(question: str) -> dict:
    from agents.dengdeng_persona import build_search_user
    from agents.dengdeng_reply import _teacher
    from knowledge_search import _search_accept, search_knowledge

    structured = search_knowledge(question)
    hits = structured.get("hits") or []
    if not hits:
        return {"ok": False, "reason": "没有命中", "question": question}
    user_text = build_search_user(
        question, hits, None, structured.get("must_names"), structured.get("must_tokens")
    )
    answer = _teacher(user_text)
    ok = _search_accept(answer, structured)
    row = _sample("search", question, user_text, answer, {
        "must_names": structured.get("must_names") or [],
        "must_tokens": structured.get("must_tokens") or [],
        "reason": "ok" if ok else "未保留资料",
    })
    return {"ok": ok, "row": row}


def _collect_team(question: str) -> dict:
    from agents.dengdeng_persona import build_team_user, team_keeps_roster, team_member_names
    from agents.dengdeng_reply import _teacher
    from pokemon_kb import complete_team_answer, propose_team_line

    raw = propose_team_line(question)
    draft = complete_team_answer(raw, question)
    names = team_member_names(draft)
    if len(names) < 6:
        return {"ok": False, "reason": "程序没凑满 6 人", "question": question}
    user_text = build_team_user(question, draft)
    answer = _teacher(user_text)
    ok = team_keeps_roster(answer, draft)
    row = _sample("team", question, user_text, answer, {
        "must_names": names,
        "must_tokens": [],
        "reason": "ok" if ok else "名单或技能没留全",
    })
    return {"ok": ok, "row": row}


def _fighter(mon: dict) -> dict:
    from pokemon_kb import elf_skill_options

    names = []
    for option in elf_skill_options(mon):
        if option.get("source") == "血脉":
            continue
        if option.get("name") in names:
            continue
        names.append(option["name"])
        if len(names) == 4:
            break
    return {
        "name": mon["name"],
        "skills": names,
        "blood": "初始血脉",
        "item": "光合治愈",
    }


def _collect_battle(question: str) -> dict:
    from agents.dengdeng_persona import battle_keeps_log, build_battle_user
    from agents.dengdeng_reply import _teacher
    from battle import play_move, start_battle
    from pokemon_kb import load_pokemon

    left_name, _, right_name = question.partition("对")
    catalog = {mon["name"]: mon for mon in load_pokemon()}
    left = catalog.get(left_name)
    right = catalog.get(right_name)
    if not left or not right:
        return {"ok": False, "reason": "对战双方不在图鉴", "question": question}
    started = start_battle(_fighter(left), _fighter(right))
    if not started.get("ok"):
        return {"ok": False, "reason": "无法开战", "question": question}
    battle_id = started["battle"]["battle_id"]
    lines = []
    winner = ""
    skills = [skill["name"] for skill in started["battle"]["player"]["skills"]]
    for index in range(4):
        moved = play_move(battle_id, skills[index % len(skills)], "skill", "")
        if not moved.get("ok"):
            break
        lines.extend(moved.get("lines") or [])
        winner = (moved.get("battle") or {}).get("winner") or winner
        if (moved.get("battle") or {}).get("over"):
            break
    if not lines:
        return {"ok": False, "reason": "没有对战日志", "question": question}
    user_text = build_battle_user(lines, winner)
    answer = _teacher(user_text)
    ok = battle_keeps_log(answer, lines)
    row = _sample("battle", question, user_text, answer, {
        "must_names": [left_name, right_name],
        "must_tokens": [],
        "reason": "ok" if ok else "日志关键词或数字丢失",
    })
    return {"ok": ok, "row": row}


def collect(limit: int) -> None:
    done = {row["meta"]["question"] for row in _load(PASSED) if row.get("meta")}
    questions = build_questions()
    _write_jsonl(QUESTIONS, questions)
    trainable = [row for row in questions if row["task"] != "nodata" and row["question"] not in done]
    if limit:
        trainable = trainable[:limit]
    handlers = {"search": _collect_search, "team": _collect_team, "battle": _collect_battle}
    for index, item in enumerate(trainable, start=1):
        started = time.time()
        try:
            result = handlers[item["task"]](item["question"])
        except Exception as exc:
            result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "question": item["question"]}
        elapsed = round(time.time() - started, 2)
        if result.get("row"):
            result["row"]["meta"]["seconds"] = elapsed
            _append(PASSED if result["ok"] else REJECTED, result["row"])
            mark = "通过" if result["ok"] else "拒绝"
        else:
            _append(REJECTED, {"messages": [], "meta": {
                "task": item["task"], "question": item["question"], "reason": result.get("reason"), "seconds": elapsed,
            }})
            mark = "拒绝"
        print(f"[{index}/{len(trainable)}] {mark} {item['task']} {item['question']} {elapsed}s", flush=True)


def split_sets() -> None:
    passed = [row for row in _load(PASSED) if row.get("messages")]
    rng = random.Random(20261004)
    rng.shuffle(passed)
    by_task = {"search": [], "team": [], "battle": []}
    for row in passed:
        by_task.setdefault(row["meta"]["task"], []).append(row)
    eval_rows = []
    for task, count in (("search", 18), ("team", 6), ("battle", 6)):
        eval_rows.extend(by_task.get(task, [])[:count])
    eval_keys = {row["meta"]["question"] for row in eval_rows}
    train_rows = [row for row in passed if row["meta"]["question"] not in eval_keys]
    if len(eval_rows) < 30:
        for row in passed:
            if row["meta"]["question"] in eval_keys:
                continue
            eval_rows.append(row)
            eval_keys.add(row["meta"]["question"])
            if len(eval_rows) >= 30:
                break
        train_rows = [row for row in passed if row["meta"]["question"] not in eval_keys]
    from agents.dengdeng_persona import build_search_user

    for question in NODATA:
        user_text = build_search_user(question, [], None, [], [])
        row = _sample("nodata", question, user_text, "", {
            "must_names": [],
            "must_tokens": [],
            "reason": "只测哭腔，不进训练",
        })
        row["messages"] = [item for item in row["messages"] if item["role"] != "assistant"]
        eval_rows.append(row)
    _write_jsonl(TRAIN, train_rows)
    _write_jsonl(EVAL, eval_rows)
    print(f"通过 {len(passed)}，训练 {len(train_rows)}，评测 {len(eval_rows)}（含 10 条无资料）")


def main() -> int:
    parser = argparse.ArgumentParser(description="采集灯灯 teacher 成文")
    parser.add_argument("--limit", type=int, default=0, help="0 表示问题表里的全部可训练题")
    parser.add_argument("--split-only", action="store_true")
    args = parser.parse_args()
    if not args.split_only:
        collect(args.limit)
    split_sets()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
