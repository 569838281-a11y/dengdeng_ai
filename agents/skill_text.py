"""读取 SKILL.md，并抽出其中的编号步骤。"""
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def load_skill(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"找不到技能文件: {path}")
    return path.read_text(encoding="utf-8")


def extract_steps(skill_markdown: str) -> list:
    """从技能正文里取出「1. ...」这种步骤。YAML 头里的内容不计入。"""
    body = skill_markdown
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    steps = []
    for line in body.splitlines():
        matched = re.match(r"^\d+\.\s+(.*\S)\s*$", line.strip())
        if matched:
            steps.append(matched.group(1))
    return steps
