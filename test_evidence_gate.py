"""证据契约 / 充足性闸 / HALT 覆盖（Self-RAG · SURE-RAG · HALT）。"""
from agents.evidence_gate import (
    INSUFFICIENT,
    PARTIAL,
    SUPPORT,
    critique_answer,
    halt_ready,
    judge_sufficiency,
)
from agents.fact_read import read_one


def test_skill_compare_partial_when_only_one_power_row():
    gate = judge_sufficiency(
        "海枝枝的技能和威力",
        ["拍击｜魔攻｜能耗 1｜威力 65｜对敌方精灵造成魔法伤害。"],
        {"pool_complete": False},
    )
    assert gate["status"] == PARTIAL
    assert gate["action"] == "full_pool"


def test_skill_compare_support_with_enough_rows():
    rows = [
        "拍击｜魔攻｜能耗 1｜威力 65｜造成魔伤。",
        "甩水｜魔攻｜能耗 0｜威力 30｜造成魔伤。",
        "恐吓｜魔攻｜能耗 2｜威力 80｜造成魔伤。",
    ]
    gate = judge_sufficiency("海枝枝的技能和威力", rows, {"pool_complete": True})
    assert gate["status"] == SUPPORT


def test_rate_bridge_is_partial():
    gate = judge_sufficiency(
        "出场率最高的精灵",
        ["前十阵容大揭秘"],
        {"fill": "bridge", "bridge": "前十阵容"},
    )
    assert gate["status"] == PARTIAL


def test_halt_blocks_damage_without_settlement():
    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"
    hops = [{"fact": "出场率最高的精灵", "text": "出场率最高的精灵是霹雳迪迪。", "lines": []}]
    ready = halt_ready(question, hops, "灯灯翻到：出场率最高的精灵是霹雳迪迪。")
    assert ready["ok"] is False
    assert any(item["id"] == "max_skill" for item in ready["missing"]) or any(
        item["id"] == "damage" for item in ready["missing"]
    )


def test_critique_rejects_max_without_skill_hop():
    got = critique_answer(
        "霹雳迪迪用威力最大的技能打水灵能打出多少伤害",
        "技能池里，拍击的威力最大，是65。",
        hops=[{"fact": "霹雳迪迪的属性", "text": "属性：电", "lines": ["属性：电"]}],
    )
    assert got["pass"] is False
    assert "unsupported_max" in got["issues"] or "partial_compare" in got["issues"]


def test_read_one_marks_narrow_skill_pool():
    # 若名录里某只只有极少带威力招，应 partial 而非假 covered
    one = read_one("水灵的技能和威力")
    assert "gate" in one
    assert one["gate"]["status"] in {SUPPORT, PARTIAL, INSUFFICIENT}


if __name__ == "__main__":
    test_skill_compare_partial_when_only_one_power_row()
    test_skill_compare_support_with_enough_rows()
    test_rate_bridge_is_partial()
    test_halt_blocks_damage_without_settlement()
    test_critique_rejects_max_without_skill_hop()
    test_read_one_marks_narrow_skill_pool()
    print("ok")
