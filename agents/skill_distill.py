"""把撰写员的技能和已通过核对的轨迹，收成 LoRA 训练样本。

学生模型要学会两件事：从 SKILL.md 抽出步骤，再按这些步骤复现回答。
检索仍然由知识库完成，样本里会带上检索片段。

导出命令：python -m agents.skill_distill
"""
import json
from pathlib import Path
from typing import Dict, List

from agents.pipeline import TRACE_DIR, format_snippets
from agents.skill_text import extract_steps, load_skill

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "lora" / "train.jsonl"


def build_user_message(skill_text: str, question: str, snippets: List[Dict]) -> str:
    snippet_text = format_snippets(snippets) if snippets else "（没有检索到片段）"
    return (
        "下面是上一个智能体的技能说明。请先抽出它的执行步骤，再按这些步骤完成问题。\n\n"
        f"【技能】\n{skill_text.strip()}\n\n"
        f"【检索片段】\n{snippet_text}\n\n"
        f"【问题】\n{question.strip()}"
    )


def build_assistant_message(skill_text: str, answer: str) -> str:
    steps = extract_steps(skill_text)
    step_lines = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
    if not step_lines:
        step_lines = "1. 技能正文里没有编号步骤，按正文约束作答。"
    return f"【抽出的技能步骤】\n{step_lines}\n\n【复现结果】\n{answer.strip()}"


def example_from_trace(trace: Dict) -> Dict:
    skill_name = str(trace.get("skill_name") or "")
    skill_text = str(trace.get("skill_text") or "")
    if not skill_text:
        if not skill_name or skill_name == "writer":
            return {}
        skill_text = load_skill(skill_name)
    return {
        "messages": [
            {
                "role": "system",
                "content": "你是经过技能蒸馏的本地模型。先抽出给定智能体技能的步骤，再只根据检索片段复现该技能的任务。",
            },
            {
                "role": "user",
                "content": build_user_message(skill_text, trace["question"], trace.get("snippets") or []),
            },
            {
                "role": "assistant",
                "content": build_assistant_message(skill_text, trace.get("answer") or ""),
            },
        ]
    }


def export_dataset(trace_dir: Path = TRACE_DIR, output_path: Path = DATASET_PATH) -> Dict:
    """只收录核对通过的轨迹。没有通过的回答不拿来教学生模型。"""
    files = sorted(trace_dir.glob("*.json")) if trace_dir.exists() else []
    examples = []
    skipped = 0
    for path in files:
        trace = json.loads(path.read_text(encoding="utf-8"))
        if not trace.get("passed") or not str(trace.get("answer") or "").strip():
            skipped += 1
            continue
        example = example_from_trace(trace)
        if not example:
            skipped += 1
            continue
        examples.append(example)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")
    return {"count": len(examples), "skipped": skipped, "path": str(output_path)}


def main() -> int:
    result = export_dataset()
    print(f"写入 {result['count']} 条训练样本，跳过 {result['skipped']} 条未通过核对的轨迹")
    print(result["path"])
    return 0 if result["count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
