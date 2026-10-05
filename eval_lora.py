"""对比基座、LoRA、teacher 的灯灯成文。数字只写实测，没有跑过的列标成未训练或未测。"""
import argparse
import json
import time
from pathlib import Path

from agents.dengdeng_persona import CRY_LINES, battle_keeps_log, is_cry_line, team_keeps_roster

ROOT = Path(__file__).resolve().parent
EVAL_PATH = ROOT / "data" / "lora" / "eval.jsonl"
REPORT_PATH = ROOT / "data" / "lora" / "eval_report.md"


def _load(path: Path) -> list:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _persona_ok(text: str) -> bool:
    body = text or ""
    return "灯灯" in body and "小洛克" in body and "##" not in body and not body.lstrip().startswith("#")


def _search_ok(text: str, row: dict) -> bool:
    meta = row.get("meta") or {}
    user = ""
    for message in row.get("messages") or []:
        if message.get("role") == "user":
            user = message.get("content") or ""
    body = text or ""
    if "##" in body or "```" in body or body.lstrip().startswith("#"):
        return False
    for name in meta.get("must_names") or []:
        if name not in body:
            return False
    for token in meta.get("must_tokens") or []:
        if token and token not in body:
            return False
    for phrase in ("更可能获胜", "不是模拟赛", "应对状态", "打断"):
        if phrase in user and phrase not in body:
            return False
    return True


def _score_one(text: str, row: dict) -> dict:
    task = (row.get("meta") or {}).get("task")
    user = ""
    for message in row.get("messages") or []:
        if message.get("role") == "user":
            user = message.get("content") or ""
    if task == "nodata":
        return {
            "facts": is_cry_line(text) or any(line[:8] in (text or "") for line in CRY_LINES),
            "persona": _persona_ok(text) or is_cry_line(text),
            "hash": "##" in (text or ""),
            "roster": None,
            "cry": is_cry_line(text) or any(piece in (text or "") for piece in ("知识量还不够", "太难了", "可爱的双灯鱼")),
        }
    if task == "team":
        if "程序给出的队伍：" in user:
            roster = user.split("程序给出的队伍：", 1)[-1]
        elif "队伍配置为" in user:
            roster = "队伍配置为" + user.split("队伍配置为", 1)[-1]
        else:
            roster = user
        return {
            "facts": team_keeps_roster(text, roster),
            "persona": _persona_ok(text),
            "hash": "##" in (text or ""),
            "roster": team_keeps_roster(text, roster),
            "cry": False,
        }
    if task == "battle":
        if "对战日志：" in user:
            log = user.split("对战日志：", 1)[-1].strip().splitlines()
        else:
            log = user.split("赛场上灯灯看见：", 1)[-1].strip().splitlines()
        return {
            "facts": battle_keeps_log(text, log),
            "persona": _persona_ok(text),
            "hash": "##" in (text or ""),
            "roster": None,
            "cry": False,
        }
    return {
        "facts": _search_ok(text, row),
        "persona": _persona_ok(text),
        "hash": "##" in (text or ""),
        "roster": None,
        "cry": False,
    }


def _saved_teacher(row: dict) -> str:
    for message in row.get("messages") or []:
        if message.get("role") == "assistant":
            return message.get("content") or ""
    return ""


def _generate_local(bundle, messages: list) -> str:
    model, tokenizer = bundle
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    encoded = tokenizer(prompt, return_tensors="pt")
    encoded = {key: value.to(model.device) for key, value in encoded.items()}
    input_len = encoded["input_ids"].shape[-1]
    output = model.generate(**encoded, max_new_tokens=512, do_sample=False)
    return tokenizer.decode(output[0][input_len:], skip_special_tokens=True).strip()


def _load_base(base: str, adapter: str = ""):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(adapter or base, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(base, torch_dtype=dtype, trust_remote_code=True)
    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter)
    if torch.cuda.is_available():
        model = model.to("cuda")
    model.eval()
    return model, tokenizer


def _summarize(scored: list) -> dict:
    def rate(key, rows):
        picked = [item for item in rows if item.get(key) is not None]
        if not picked:
            return "无样本"
        hit = sum(1 for item in picked if item[key])
        return f"{hit}/{len(picked)}"

    groups = {
        "全部": scored,
        "检索": [item for item in scored if item["task"] == "search"],
        "配队": [item for item in scored if item["task"] == "team"],
        "对战": [item for item in scored if item["task"] == "battle"],
        "无资料": [item for item in scored if item["task"] == "nodata"],
    }
    summary = {}
    for name, rows in groups.items():
        if not rows:
            summary[name] = "无样本"
            continue
        delays = [item["seconds"] for item in rows if item.get("seconds") is not None]
        delay = f"{sum(delays) / len(delays):.2f}s" if delays else "未测"
        summary[name] = {
            "n": len(rows),
            "facts": rate("facts", rows),
            "persona": rate("persona", rows),
            "hash": rate("hash", rows),
            "roster": rate("roster", [item for item in rows if item["task"] == "team"]),
            "cry": rate("cry", [item for item in rows if item["task"] == "nodata"]),
            "delay": delay,
        }
    return summary


def _markdown(columns: dict) -> str:
    lines = [
        "# 灯灯成文评测",
        "",
        "比例都是本表实测的「通过条数/样本条数」。没有跑过的列不会写成百分比。",
        "",
        "| 列 | 范围 | 事实保留 | 灯灯且称呼小洛克 | 出现 ## | 配队名单 | 无资料哭腔 | 平均延迟 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, summary in columns.items():
        if isinstance(summary, str):
            lines.append(f"| {name} | {summary} |  |  |  |  |  |  |")
            continue
        for scope, item in summary.items():
            if item == "无样本":
                continue
            lines.append(
                f"| {name} | {scope}（{item['n']}） | {item['facts']} | {item['persona']} | {item['hash']} | {item['roster']} | {item['cry']} | {item['delay']} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="评测灯灯成文")
    parser.add_argument("--columns", default="teacher", help="逗号分隔：teacher,base,lora")
    parser.add_argument("--base", default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--adapter", default="data/lora/adapter")
    args = parser.parse_args()
    rows = _load(EVAL_PATH)
    wanted = [item.strip() for item in args.columns.split(",") if item.strip()]
    columns = {}
    if "lora" in wanted and not (Path(args.adapter) / "adapter_config.json").is_file():
        columns["LoRA"] = "未训练"

    for name in wanted:
        if name == "lora" and "LoRA" in columns:
            continue
        bundle = None
        if name == "base":
            bundle = _load_base(args.base)
        elif name == "lora":
            bundle = _load_base(args.base, args.adapter)
        scored = []
        for row in rows:
            task = (row.get("meta") or {}).get("task")
            messages = [item for item in (row.get("messages") or []) if item.get("role") != "assistant"]
            started = time.time()
            if task == "nodata":
                user_text = next((item.get("content") for item in messages if item.get("role") == "user"), "")
                if name == "teacher":
                    from agents.dengdeng_reply import _teacher

                    text = _teacher(user_text)
                else:
                    text = _generate_local(bundle, messages)
                seconds = round(time.time() - started, 2)
            elif name == "teacher":
                text = _saved_teacher(row)
                seconds = (row.get("meta") or {}).get("seconds")
            else:
                text = _generate_local(bundle, messages)
                seconds = round(time.time() - started, 2)
            item = _score_one(text, row)
            item["task"] = task
            item["seconds"] = seconds
            scored.append(item)
        label = {"teacher": "teacher", "base": "基座", "lora": "LoRA"}[name]
        columns[label] = _summarize(scored)
        print(label, columns[label], flush=True)
        if bundle is not None:
            import gc

            del bundle
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    if "lora" not in wanted and "LoRA" not in columns:
        columns["LoRA"] = "未训练"
    REPORT_PATH.write_text(_markdown(columns), encoding="utf-8")
    print(f"写入 {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
