"""对战员：谁会赢走模拟，比技能用威力乘克制，伤害数字用图鉴公式。"""
from agents.battle_agent import (
    catalog_damage,
    compare_speech,
    open_battle,
    type_multiplier,
)
from agents.fact_read import read_one
from agents.job_ledger import drop
from agents.supervisor import run_cycle


def test_chart_uses_the_five_catalog_rates():
    assert type_multiplier("电", ["水"]) == 2
    assert type_multiplier("光", ["水"]) == 1
    assert type_multiplier("电", ["水", "翼"]) == 3
    assert type_multiplier("电", ["水", "地"]) == 1
    assert type_multiplier("普通", ["幻"]) == 1


def test_compare_multiplies_power_by_type():
    question = "出场率最高的精灵使用本系技能攻击聪明性格水灵，哪个本系技能的威力更高？"
    one = read_one("霹雳迪迪的本系技能和威力")
    steps = [
        {"fact": "出场率最高的精灵", "text": "出场率最高的精灵是霹雳迪迪。", "lines": ["出场率最高的精灵是霹雳迪迪。"]},
        {"fact": "霹雳迪迪的属性", "text": "属性：电、光。", "lines": ["属性：电、光。"]},
        {"fact": "霹雳迪迪的本系技能和威力", "text": " ".join(one["lines"]), "lines": one["lines"]},
        {"fact": "水灵的属性", "text": "属性：水。", "lines": ["属性：水。"]},
    ]
    speech = compare_speech(question, steps)
    assert "超导" in speech
    assert "威力90" in speech
    assert "克制倍率2" in speech
    assert "合起来是180" in speech
    assert "虹光冲击的威力更高" not in speech
    assert "聪明性格没有写在威力规则里" in speech


def test_compare_without_a_defender_keeps_written_power():
    question = "水灵使用本系技能，哪个本系技能的威力更高？"
    one = read_one("水灵的本系技能和威力")
    steps = [
        {"fact": "水灵的属性", "text": "属性：水。", "lines": ["属性：水。"]},
        {"fact": "水灵的本系技能和威力", "text": " ".join(one["lines"]), "lines": one["lines"]},
    ]
    speech = compare_speech(question, steps)
    assert "天洪" in speech
    assert "150" in speech
    assert "克制倍率" not in speech


def test_page_power_must_match_the_catalog():
    question = "霹雳迪迪使用本系技能攻击水灵，哪个本系技能的威力更高？"
    one = read_one("霹雳迪迪的本系技能和威力")
    steps = [
        {"fact": "霹雳迪迪的属性", "text": "属性：电、光。", "lines": ["属性：电、光。"]},
        {"fact": "霹雳迪迪的本系技能和威力", "text": " ".join(one["lines"]), "lines": one["lines"]},
        {"fact": "水灵的属性", "text": "属性：水。", "lines": ["属性：水。"]},
    ]

    class Host:
        def __init__(self, page: str):
            self.page = page
            self.calls = []

        def call(self, tool, arguments, timeout=20):
            self.calls.append(tool)
            if tool == "browser_snapshot" and len(self.calls) == 2:
                return 'textbox "攻击方" [ref=e1]\ntextbox "防御方" [ref=e2]\ntextbox "技能" [ref=e3]'
            if tool == "browser_snapshot":
                return self.page
            return "ok"

    missed = compare_speech(question, steps, host=Host("伤害 999\n威力 1"))
    assert "合起来是180" in missed
    assert "伤害计算页读到" not in missed
    kept = compare_speech(question, steps, host=Host("伤害 180\n威力 90"))
    assert "合起来是180" in kept
    assert "伤害计算页读到：伤害 180 威力 90" in kept


def test_who_wins_is_a_simulated_bout():
    opened = open_battle("水灵和霹雳迪迪谁会赢")
    assert opened["kind"] == "simulate"
    assert opened["trial"]["frames"]
    assert opened["trial"]["intro"].startswith("灯灯来想一想")
    seen = []
    answer = run_cycle(
        "水灵和霹雳迪迪谁会赢",
        session_id="bout-agent",
        judged={"intent": "battle", "request": "水灵和霹雳迪迪谁会赢"},
        web=lambda query: seen.append(query) or {"results": []},
        review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
    )
    drop("bout-agent")
    assert not seen
    assert answer["order"]["trial"]["frames"]
    assert "灯灯来想一想" in answer["order"]["answer"]


def test_formula_without_stats_stays_with_the_archivist():
    assert open_battle("请按伤害公式算出普通系打幻系这一下的最终伤害数字。") is None


def test_named_strike_uses_the_catalog_formula():
    got = catalog_damage("霹雳迪迪", "水灵", "超导")
    attack = 139 * 1.2 + 50
    defense = 132 * 1.2 + 50
    expected = 90 * (attack / defense) * 1.25 * 2 * 37 / 41
    assert got["power"] == 90
    assert got["rate"] == 2
    assert got["stab"] == 1.25
    assert abs(got["amount"] - expected) < 1e-6
    opened = open_battle("霹雳迪迪用超导攻击水灵，这一下的最终伤害数字是多少？")
    assert opened["kind"] == "number"
    assert opened["ready"]
    assert "克制倍率是2" in opened["speech"]
    assert "伤害量是" + got["amount_text"] in opened["speech"]
    assert "伤害量 =" in opened["speech"]


if __name__ == "__main__":
    test_chart_uses_the_five_catalog_rates()
    test_compare_multiplies_power_by_type()
    test_compare_without_a_defender_keeps_written_power()
    test_page_power_must_match_the_catalog()
    test_who_wins_is_a_simulated_bout()
    test_formula_without_stats_stays_with_the_archivist()
    test_named_strike_uses_the_catalog_formula()
    print("ok")
