"""人设故事检索（Magentic/ReAct 独立技能：persona_story）。

只读 knowledge/stories/，不与精灵名录 BM25 串槽。
对齐：无检索必要时走 parametric/persona（Self-RAG on-demand retrieve）。
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STORY_DIR = _ROOT / "knowledge" / "stories"
_DENGDENG = _STORY_DIR / "灯灯.md"


def is_persona_story(question: str) -> bool:
    """你/灯灯 + 成长/故事/经历，或自我介绍类。"""
    body = (question or "").strip()
    if not body:
        return False
    selfish = any(word in body for word in ("你", "灯灯", "自己", "双灯鱼"))
    story = any(word in body for word in ("成长", "故事", "经历", "过去", "小时候"))
    intro = any(phrase in body for phrase in ("你是谁", "你叫什么", "介绍一下你", "你从哪来"))
    # 「海豹船长的故事」有明确精灵名 → 不是人设故事
    if "的故事" in body or "的成长" in body or "的经历" in body:
        try:
            from pokemon_kb import _mentioned_names, load_pokemon

            others = [name for name in _mentioned_names(body, load_pokemon()) if name not in {"双灯鱼"}]
            if others:
                return False
        except Exception:
            pass
    return intro or (selfish and story)


def read_dengdeng_story(question: str = "") -> dict:
    """读灯灯故事原文，收成可开口的一段。"""
    path = _DENGDENG
    if not path.is_file():
        return {
            "covered": False,
            "speech": "灯灯这会儿还没把自个儿的故事本翻出来。跟灯灯说一下。",
            "lines": [],
            "source": "",
        }
    raw = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]
    # 开口不宜整篇；取开篇立意 + 决定当小助手的段落
    kept = []
    for line in lines:
        if len("".join(kept)) > 360:
            break
        kept.append(line)
        if "战斗知识小助手" in line and len(kept) >= 4:
            break
    if not kept:
        kept = lines[:8]
    speech = (
        "噔噔！灯灯给小洛克讲自个儿的故事。"
        + "".join(kept[:6])
    )
    if len(speech) > 420:
        speech = speech[:400].rstrip("，,。；; ") + "……灯灯后来就决定当战斗知识小助手啦！"
    return {
        "covered": True,
        "speech": speech,
        "lines": kept,
        "source": str(path.relative_to(_ROOT)).replace("\\", "/"),
    }
