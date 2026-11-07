"""意图只负责听要求。改仓库不能被模型补上数量。听不清就交给原来的规则。"""
from agents.intent_judge import judge_intent, next_question, parse_intent


def test_parse_and_keep_original_order():
    parsed = parse_intent('{"intent":"search","request":"介绍一下水灵"}')
    assert parsed["intent"] == "search"
    assert next_question("水灵怎么样", parsed) == "介绍一下水灵"
    heard = judge_intent("把海枝枝放了吧", ask=lambda text: '{"intent":"order","request":"放生一只海枝枝"}')
    assert heard["request"] == "把海枝枝放了吧"
    assert next_question("把海枝枝放了吧", heard) == "把海枝枝放了吧"


def test_battle_rewrite_and_failure():
    heard = judge_intent("火神和水灵谁更厉害", ask=lambda text: '{"intent":"battle","request":"火神和水灵"}')
    assert next_question("火神和水灵谁更厉害", heard).endswith("谁会赢")
    missed = judge_intent("随便说说", ask=lambda text: "不是 json")
    assert missed["intent"] == ""
    assert next_question("随便说说", missed) == "随便说说"


def test_damage_rate_question_stays_search():
    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"
    heard = judge_intent(question, ask=lambda text: '{"intent":"lineup","request":"组一套闪耀大赛阵容"}')
    assert heard["intent"] == "search"
    assert heard["request"] == question


if __name__ == "__main__":
    test_parse_and_keep_original_order()
    test_battle_rewrite_and_failure()
    test_damage_rate_question_stays_search()
    print("ok")
