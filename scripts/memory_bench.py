"""灯灯上下文记忆评测。

能力轴来自 LoCoMo（Maharana 等人，arXiv:2402.17753）和
LongMemEval（Wu 等人，arXiv:2410.10813）。
题目是灯灯自己的前后句，不是这两套英文长闲聊题库。
LoCoMo 的 token F1 在中文上改为字重叠；LongMemEval 的裁判分改为程序判定对错。
"""
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agents.chat_notebook as nb
from agents.fact_memory import list_facts
from agents.turn_memory import carry_subject, close_turn, remember_exchange
from agents.work_cycle import prepare_turn


def _tokens(text: str) -> list:
    chars = []
    for char in (text or "").lower():
        if char.isspace() or char in "，。！？、,.!?;；:：\"'“”":
            continue
        chars.append(char)
    return chars


def f1_score(prediction: str, gold: str) -> float:
    """与 LoCoMo evaluation.py 同一公式：重叠词数算精确率、召回率，再算 F1。"""
    pred = _tokens(prediction)
    truth = _tokens(gold)
    if not pred and not truth:
        return 1.0
    if not pred or not truth:
        return 0.0
    common = Counter(pred)
    overlap = 0
    for char in truth:
        if common[char]:
            overlap += 1
            common[char] -= 1
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(truth)
    return 2 * precision * recall / (precision + recall)


def _catalog_trait(name: str) -> str:
    from pokemon_kb import load_pokemon

    for item in load_pokemon():
        if item.get("name") == name:
            return str(item.get("trait") or "").split("。")[0]
    return ""


class Bench:
    def __init__(self):
        self.rows = []
        self._root = Path(tempfile.mkdtemp())
        nb._BOOKS.clear()
        nb._PATH = self._root / "chat_notebooks.json"

    def reset(self):
        nb._BOOKS.clear()
        folder = self._root / str(len(self.rows))
        folder.mkdir()
        nb._PATH = folder / "chat_notebooks.json"

    def add(self, benchmark, ability, case_id, question, gold, prediction, note):
        score = f1_score(prediction, gold)
        exact = prediction == gold
        self.rows.append({
            "benchmark": benchmark,
            "ability": ability,
            "id": case_id,
            "question": question,
            "gold": gold,
            "prediction": prediction,
            "f1": round(score, 4),
            "exact": exact,
            "note": note,
        })


def _name_of(result: dict, expected: str) -> str:
    query = result.get("query") or ""
    if result.get("carried") and expected in query:
        return expected
    return "未接上"


def _refuse(result: dict, original: str) -> str:
    return "不接" if result.get("query") == original and not result.get("carried") else result.get("query") or ""


def run() -> Bench:
    bench = Bench()
    locomo = "LoCoMo"
    longmem = "LongMemEval"

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    followed = "那它的技能呢"
    carried = carry_subject(followed, "s")
    bench.add(locomo, "单跳", "L1", followed, "水灵", _name_of(carried, "水灵"), "上一问的全名补进这一句")

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    second = carry_subject("那它的技能呢", "s")
    close_turn("s", second["query"], "search")
    third = "那威力呢"
    hopped = carry_subject(third, "s")
    bench.add(locomo, "多跳", "L2", third, "水灵", _name_of(hopped, "水灵"), "连着两句之后仍指回第一只")

    bench.reset()
    nb.learn("s", "水灵是草系的")
    nb.learn("s", "水灵是水系的")
    close_turn("s", "水灵的属性", "remember")
    asked = carry_subject("它的属性呢", "s")
    bench.add(locomo, "时间", "L3", "它的属性呢", "水灵", _name_of(asked, "水灵"), "后一句仍指向水灵")

    bench.reset()
    nb.learn("s", "更喜欢输出")
    close_turn("s", "水灵的特性", "search")
    card = nb.turn_of("s") or {}
    trait = _catalog_trait("水灵")
    leaked = "输出" in (card.get("field") or "") or any("输出" in name for name in card.get("names") or [])
    bench.add(
        locomo, "开放知识", "L4", "水灵的特性", trait,
        "记忆盖过名录" if leaked else trait,
        "偏好留在记事本，特性仍读图鉴",
    )

    bench.reset()
    close_turn("s", "霹雳迪迪和水灵谁速度高", "battle")
    raw = "它的特性呢"
    bench.add(locomo, "故意无答案", "L5", raw, "不接", _refuse(carry_subject(raw, "s"), raw), "两只时不猜它是谁")

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    raw = "另外问火灵的特性"
    bench.add(locomo, "故意无答案", "L6", raw, "不接", _refuse(carry_subject(raw, "s"), raw), "另起一句不继承上一只")

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    card = nb.turn_of("s") or {}
    blob = json.dumps(card, ensure_ascii=False)
    digits = any(char.isdigit() for char in blob)
    pred = "水灵/特性" if card.get("names") == ["水灵"] and card.get("field") == "特性" and not digits else blob
    bench.add(longmem, "信息抽出", "E1", "水灵的特性", "水灵/特性", pred, "卡片只有全名和栏目")

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    close_turn("s", carry_subject("那它的技能呢", "s")["query"], "search")
    later = carry_subject("这个呢", "s")
    bench.add(longmem, "会话内多步", "E2", "这个呢", "水灵", _name_of(later, "水灵"), "第三句仍用第一只，不新造对象")

    bench.reset()
    close_turn("a", "水灵的特性", "search")
    raw = "它的技能呢"
    bench.add(longmem, "会话隔离", "E3", raw, "不接", _refuse(carry_subject(raw, "b"), raw), "另一段对话不带走上一只")

    bench.reset()
    nb.learn("s", "水灵是草系的")
    nb.learn("s", "水灵是水系的")
    facts = [item for item in list_facts("s") if item["entity"] == "水灵" and item["field"] == "属性"]
    value = facts[0]["value"] if facts else ""
    close_turn("s", "水灵的属性", "remember")
    card_text = json.dumps(nb.turn_of("s") or {}, ensure_ascii=False)
    pred = value if "草" not in card_text else "卡片仍留着旧属性"
    bench.add(longmem, "知识更新", "E4", "水灵的属性", "水", pred, "同一栏后一次盖过前一次，卡片不保存旧值")

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    skill_query = carry_subject("那它的技能呢", "s")["query"]
    close_turn("s", skill_query, "search")
    field = (nb.turn_of("s") or {}).get("field") or ""
    bench.add(longmem, "时间推理", "E5", "那它的技能呢", "技能", field, "后一问的栏目盖过特性")

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    raw = "放生海枝枝"
    bench.add(longmem, "拒答", "E6", raw, "不接", _refuse(carry_subject(raw, "s"), raw), "放生保持原句，不把水灵拼进去")

    bench.reset()
    raw = "它的技能呢"
    bench.add(longmem, "拒答", "E7", raw, "不接", _refuse(carry_subject(raw, "s"), raw), "还没有上一问时不猜")

    bench.reset()
    close_turn("search", "水灵的特性", "search")
    close_turn("team", "水灵的特性", "search")
    search_log = []
    team_log = []

    def extend(bucket):
        def write(_sid, messages):
            bucket.extend(messages)
        return write

    remember_exchange("search", "水灵的特性", "浸润", extend(search_log))
    remember_exchange("team", "水灵的特性", "浸润", extend(team_log))
    search_follow = carry_subject("那它的技能呢", "search")
    team_follow = carry_subject("那它的技能呢", "team")
    both = (
        len(search_log) == 2 and len(team_log) == 2
        and search_log[0]["role"] == "user" and team_log[1]["role"] == "assistant"
        and "水灵" in search_follow["query"] and "水灵" in team_follow["query"]
    )
    bench.add(longmem, "两条入口", "E8", "那它的技能呢", "两条都能接上", "两条都能接上" if both else "有一条没写上或没接上", "检索和配队都留下原文，下一句都能补上水灵")

    bench.reset()
    close_turn("s", "水灵的特性", "search")
    anchored = prepare_turn(
        "那水灵的技能呢",
        [{"role": "user", "content": "水灵的特性"}],
        invoke=lambda _prompt: "技能呢",
        anchor="水灵",
    )
    kept = "水灵" in (anchored.get("query") or "")
    bench.add(locomo, "单跳", "L7", "技能呢", "水灵", "水灵" if kept else anchored.get("query") or "", "改写丢掉全名时退回带全名的句子")

    bench.reset()
    close_turn("s", "霹雳迪迪用超导打水灵", "battle")
    from agents.battle_agent import catalog_damage

    number = catalog_damage("霹雳迪迪", "水灵", "超导")
    card_text = json.dumps(nb.turn_of("s") or {}, ensure_ascii=False)
    if not number:
        pred = "名录算不出"
        gold = "名录数字"
    else:
        gold = f"{number['skill']}/{number['power']}"
        leaked_number = str(number["power"]) in card_text or str(int(number["amount"])) in card_text
        pred = "数字写进了卡片" if leaked_number else gold
    bench.add(longmem, "知识更新", "E9", "霹雳迪迪用超导打水灵", gold, pred, "伤害数字当场向名录重算，不从卡片读")
    return bench


def render(bench: Bench) -> str:
    lines = [
        "灯灯上下文记忆评测",
        "LoCoMo：Maharana 等人，ACL 2024，arXiv:2402.17753。问答 F1 用字重叠，公式与 task_eval/evaluation.py 的 token F1 相同。",
        "LongMemEval：Wu 等人，ICLR 2025，arXiv:2410.10813。五类能力用程序判定对错，对应官方 evaluate_qa.py 的 autoeval_label，不调用裁判模型。",
        "官方英文题库没有执行。下面每一题都是灯灯会话里的前后句。",
        "",
    ]
    for row in bench.rows:
        lines.append(f"[{row['benchmark']}] {row['ability']} {row['id']}")
        lines.append(f"问句：{row['question']}")
        lines.append(f"标准：{row['gold']}")
        lines.append(f"灯灯：{row['prediction']}")
        lines.append(f"F1：{row['f1']}")
        lines.append(f"对错：{'对' if row['exact'] else '错'}")
        lines.append(f"说明：{row['note']}")
        lines.append("")
    lines.append("分类汇总")
    groups = {}
    for row in bench.rows:
        key = (row["benchmark"], row["ability"])
        groups.setdefault(key, []).append(row)
    for key in groups:
        rows = groups[key]
        correct = sum(1 for row in rows if row["exact"])
        average = sum(row["f1"] for row in rows) / len(rows)
        lines.append(f"{key[0]} / {key[1]}：{correct}/{len(rows)}，平均 F1 {average:.4f}")
    for benchmark in ( "LoCoMo", "LongMemEval"):
        rows = [row for row in bench.rows if row["benchmark"] == benchmark]
        correct = sum(1 for row in rows if row["exact"])
        average = sum(row["f1"] for row in rows) / len(rows)
        lines.append(f"{benchmark} 合计：{correct}/{len(rows)}，平均 F1 {average:.4f}")
    correct = sum(1 for row in bench.rows if row["exact"])
    average = sum(row["f1"] for row in bench.rows) / len(bench.rows)
    lines.append(f"全部：{correct}/{len(bench.rows)}，平均 F1 {average:.4f}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    report = render(run())
    out = Path(__file__).resolve().parents[1] / "data" / "memory_bench.txt"
    out.write_text(report, encoding="utf-8")
    print(report, end="")
