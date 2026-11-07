"""用裁判模型给已训练的 LoRA 口吻打分。事实仍用程序核对，裁判不能改判。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage, SystemMessage

from eval_lora import _generate_local, _load, _load_base, _score_one

EVAL_PATH = ROOT / "data" / "lora" / "eval.jsonl"
TRAIN_PATH = ROOT / "data" / "lora" / "train.jsonl"
OUT_PATH = ROOT / "data" / "lora" / "voice_judge.txt"

JUDGE = """你只给口吻打分，不判断事实、数字和名单对不对。只输出一个 JSON，不要解释。
格式：{"self_name":1到5,"not_assistant":1到5,"sprite_not_coach":1到5,"not_script":1到5,"note":"一句中文"}
self_name：自称灯灯，并称呼对方小洛克。缺一个就低于 3。
not_assistant：不像客服或语言模型。出现「根据您的问题」「作为语言模型」「我是人工智能」「AI助手」必须是 1。
sprite_not_coach：像一只精灵在聊天，不是教练在布置「你上场」。
not_script：没有井号标题，没有代码围栏，不像在念表格。可以俏皮。
5 是完全像灯灯，1 是完全不像。"""


def _user_key(row: dict) -> str:
    for message in row.get("messages") or []:
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _pick(rows: list) -> list:
    grouped = {}
    for index, row in enumerate(rows):
        grouped.setdefault((row.get("meta") or {}).get("task") or "", []).append(index)
    chosen = []
    for task in ("search", "team", "battle", "nodata"):
        indexes = grouped.get(task) or []
        if not indexes:
            continue
        chosen.append(indexes[0])
        if len(indexes) > 1:
            chosen.append(indexes[len(indexes) // 2])
    return chosen


def _judge(question: str, speech: str) -> dict:
    from agents.prompt_function_calling import first_json
    from llm_provider import OPENAI_MODEL, get_team_invoke

    invoke = get_team_invoke(60)
    result = invoke([
        SystemMessage(content=JUDGE),
        HumanMessage(content=f"小洛克的问题：{question}\n\n灯灯说：\n{(speech or '')[:900]}"),
    ])
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    data = first_json(str(content or ""))
    scores = {}
    if isinstance(data, dict):
        for key in ("self_name", "not_assistant", "sprite_not_coach", "not_script"):
            try:
                scores[key] = int(data.get(key))
            except (TypeError, ValueError):
                scores[key] = 0
        scores["note"] = str(data.get("note") or "").strip()
    else:
        scores = {"self_name": 0, "not_assistant": 0, "sprite_not_coach": 0, "not_script": 0, "note": "裁判没有返回可解析的分数"}
    scores["model"] = OPENAI_MODEL
    values = [scores[key] for key in ("self_name", "not_assistant", "sprite_not_coach", "not_script")]
    scores["pass"] = all(value >= 4 for value in values)
    scores["low"] = min(values) if values else 0
    return scores


def main() -> None:
    rows = _load(EVAL_PATH)
    train_keys = set()
    if TRAIN_PATH.is_file():
        train_keys = {_user_key(row) for row in _load(TRAIN_PATH)}
    overlap = sum(1 for row in rows if _user_key(row) in train_keys)
    picked = _pick(rows)
    print(f"评测题 {len(rows)}，其中训练题 {overlap}。口吻抽样 {len(picked)}。", flush=True)
    bundle = _load_base("Qwen/Qwen2.5-1.5B-Instruct", str(ROOT / "data" / "lora" / "adapter"))
    lines = [
        "灯灯 LoRA 口吻裁判",
        "裁判只看口吻。合格线：自称称呼、不像助手、精灵不是教练、不像念稿，四项都至少 4 分。",
        f"评测题 {len(rows)} 条，与 train.jsonl 相同的有 {overlap} 条。下面 {len(picked)} 条是各类的抽样，由 data/lora/adapter 当场生成。",
        "线上成文员现在不加载这份权重。",
        "",
    ]
    passed = 0
    lows = []
    for number, index in enumerate(picked, 1):
        row = rows[index]
        task = (row.get("meta") or {}).get("task") or ""
        question = (row.get("meta") or {}).get("question") or task
        messages = [item for item in (row.get("messages") or []) if item.get("role") != "assistant"]
        print(f"生成 {number}/{len(picked)} {task} {question}", flush=True)
        speech = _generate_local(bundle, messages)
        program = _score_one(speech, row)
        print(f"裁判 {number}/{len(picked)}", flush=True)
        judged = _judge(question, speech)
        if judged["pass"]:
            passed += 1
        lows.append(judged["low"])
        lines.append(f"{number}. [{task}] {question}")
        lines.append(f"口吻分：自称 {judged['self_name']}，不像助手 {judged['not_assistant']}，精灵不是教练 {judged['sprite_not_coach']}，不像念稿 {judged['not_script']}")
        lines.append(f"口吻：{'合格' if judged['pass'] else '不合格'}。{judged['note']}")
        lines.append(f"程序事实：{'保留' if program.get('facts') else '没保留'}。灯灯且称呼小洛克：{'是' if program.get('persona') else '否'}。")
        lines.append("开口：" + " ".join((speech or "").split())[:180])
        lines.append("")
    mean_low = sum(lows) / len(lows) if lows else 0
    lines.append(f"抽样口吻合格：{passed}/{len(picked)}。四项最低分的平均：{mean_low:.2f}。")
    lines.append("整份微调仍不合格：2026-10-05 的 40 题里，事实保留 17/40，配队名单 1/6。口吻分不能把这些改成通过。")
    lines.append(f"裁判模型：{judged['model'] if picked else '未调用'}。")
    text = "\n".join(lines) + "\n"
    OUT_PATH.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
