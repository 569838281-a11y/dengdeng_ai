"""三种核对共用同一句按威力写成的错答案。"""
from agents.answer_verify import format_report, review_draft
from agents.battle_agent import compare_speech
from agents.fact_read import _compare_answer, read_one

QUESTION = "出场率最高的精灵使用本系技能攻击聪明性格水灵，哪个本系技能的威力更高？"


def _steps():
    one = read_one("霹雳迪迪的本系技能和威力")
    return [
        {"fact": "出场率最高的精灵", "text": "出场率最高的精灵是霹雳迪迪。", "lines": ["出场率最高的精灵是霹雳迪迪。"]},
        {"fact": "霹雳迪迪的属性", "text": "属性：电、光。", "lines": ["属性：电、光。"]},
        {"fact": "霹雳迪迪的本系技能和威力", "text": " ".join(one["lines"]), "lines": one["lines"]},
        {"fact": "水灵的属性", "text": "属性：水。", "lines": ["属性：水。"]},
    ], one


def test_three_checks_share_one_wrong_sentence():
    steps, skill = _steps()
    skill_step = steps[2]
    draft = _compare_answer(QUESTION, steps, skill_step) + "SENTINEL"
    report = review_draft(QUESTION, steps, skill_step, draft)
    print(format_report(report))
    assert report["draft"] == "本系攻击技能里，虹光冲击的威力更高，是100。"
    assert "SENTINEL" not in report["draft"]
    cove = report["cove"]
    edited = report["verify_edit"]
    rag = report["self_rag"]
    blob = str(cove["answers"]) + edited["edited_step"] + edited["revised"] + str(rag["claims"])
    assert "SENTINEL" not in blob
    assert cove["draft_given_to_answers"] is False
    assert [item["question"] for item in cove["answers"][:2]] == ["电打水的倍率", "光打水的倍率"]
    assert cove["answers"][0]["answer"] == "2"
    assert cove["answers"][1]["answer"] == "1"
    assert "超导的威力是90" in cove["answers"][2]["answer"]
    assert "虹光冲击的威力是100" in cove["answers"][2]["answer"]
    assert cove["skill"] == "超导"
    assert cove["score"] == "180"
    assert cove["power_only_answer"] == "虹光冲击，100"
    assert cove["power_only_revised"] == report["draft"]
    assert edited["uncertain"] is True
    assert edited["question"] == "电打水和光打水各是几倍"
    assert "电打水的倍率是2" in edited["edited_step"]
    assert "光打水的倍率是1" in edited["edited_step"]
    assert edited["skill"] == "超导"
    assert rag["claims"][0]["grade"] == "对得上"
    assert rag["claims"][1]["grade"] == "对不上"
    assert rag["adopt"] is False
    assert rag["revised"] == ""
    assert rag["search_again"] is False
    assert "180" not in str(rag)
    assert report["spoken"] == cove["revised"] == edited["revised"]
    assert "超导" in report["spoken"]
    speech = compare_speech(QUESTION, steps)
    assert "合起来是180" in speech
    assert "虹光冲击的威力更高" not in speech
    assert "聪明性格没有写在威力规则里" in speech


if __name__ == "__main__":
    test_three_checks_share_one_wrong_sentence()
    print("ok")
