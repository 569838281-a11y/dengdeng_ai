"""技能问句读这只精灵的三池。名录没有的登场率单独去联网。"""
import agents.web_read as web_read
from agents.fact_read import outside_query, read_facts, skill_pool_name
from agents.job_ledger import drop
from agents.speech_review import _accept
from agents.supervisor import run_cycle
from agents.thoughts import bind, reset
from agents.web_read import web_anchors as page_anchors
from knowledge_search import lookup_by_plan, plan_query


def _fast_rank(fact, texts):
    anchors = page_anchors(fact) or [fact]
    return [float(sum(anchor in (text or "") for anchor in anchors)) for text in texts]


def _cycle(*args, **kwargs):
    previous = web_read.scheme_c
    web_read.scheme_c = _fast_rank
    try:
        return run_cycle(*args, **kwargs)
    finally:
        web_read.scheme_c = previous


def test_skill_pool_comes_from_the_card():
    assert skill_pool_name("水灵有什么技能") == "水灵"
    assert skill_pool_name("闪耀大赛登场率最高的精灵使用其威力最大的技能攻击水灵") == ""
    read = read_facts("水灵有什么技能")
    assert read["queries"] == ["水灵的技能"]
    assert read["missing"] == []
    text = read["speech"]
    assert "天洪" in text and "甩水" in text
    assert "579" not in text
    plan = plan_query("水灵有什么技能", allow_model=False)
    assert plan["intent"] == "lookup_pool"
    assert plan["plates"] == []
    looked = lookup_by_plan("水灵有什么技能", plan)
    assert "天洪" in looked["answer"]
    assert "板块 G" not in looked["answer"]


def test_rate_question_searches_only_the_missing_fact():
    question = "闪耀大赛登场率最高的精灵使用其威力最大的技能攻击天真性格的水灵会造成多少伤害"
    assert outside_query(question) == "闪耀大赛登场率最高的精灵"
    seen = []
    called = {"lookup": 0}

    def lookup(*_args):
        called["lookup"] += 1
        return {"found": True, "answer": "水灵的特性是浸润。特性、战斗道具。", "trial": None}

    def web(query):
        seen.append(query)
        if "闪耀大赛登场率最高的精灵" in query:
            return {"results": [{
                "title": "闪耀大赛",
                "url": "https://rocom.qq.com/shine",
                "snippet": "闪耀大赛登场率最高的是霹雳迪迪。",
            }]}
        return {"results": []}

    cycle = _cycle(
        question,
        session_id="rate-web",
        judged={"intent": "battle", "request": question + "，谁会赢"},
        lookup=lookup,
        web=web,
        review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
    )
    answer = cycle["order"]["answer"]
    assert called["lookup"] == 0
    assert seen
    assert any("闪耀大赛登场率最高的精灵" in query for query in seen)
    assert all("对战细则" not in query for query in seen)
    assert "霹雳迪迪" in answer
    assert "579" not in answer
    drop("rate-web")


def test_closed_web_says_the_catalog_has_no_rate():
    question = "闪耀大赛登场率最高的精灵是谁"

    def web(_query):
        return {"reason": "off", "results": []}

    cycle = _cycle(
        question,
        session_id="rate-off",
        judged={"intent": "search", "request": question},
        web=web,
        review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
    )
    assert cycle["ledger"]["progress"]["next"] == "need_ask"
    assert "名录里没有闪耀大赛登场率最高的精灵" in cycle["order"]["answer"]
    assert "跟灯灯说一下这一处" in cycle["order"]["answer"]
    drop("rate-off")


def test_trace_says_the_catalog_miss_goes_outside():
    seen = []
    token = bind(lambda _kind, text: seen.append(text))

    def web(query):
        if "闪耀大赛" in query:
            return {"results": [{
                "title": "闪耀大赛",
                "url": "https://rocom.qq.com/shine",
                "snippet": "闪耀大赛登场率最高的是霹雳迪迪。",
            }]}
        return {"results": []}

    try:
        _cycle(
            "闪耀大赛登场率最高的精灵",
            session_id="rate-trace",
            judged={"intent": "search", "request": "闪耀大赛登场率最高的精灵"},
            web=web,
            review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
        )
    finally:
        reset(token)
        drop("rate-trace")
    assert "名录里没有这一处，灯灯到外面看" in seen


def test_simple_skill_question_does_not_open_the_catalog():
    def ask(_ledger, _word):
        return "need_ask"

    cycle = _cycle(
        "水灵有什么技能",
        session_id="skill-ask",
        judged={"intent": "search", "request": "水灵有什么技能"},
        route_ask=ask,
        review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
    )
    answer = cycle["order"]["answer"]
    assert cycle["ledger"]["progress"].get("adaptive") == "A"
    assert "没想起" in answer
    assert "天洪" not in answer
    assert cycle["ledger"]["progress"]["next"] != "need_ask"
    drop("skill-ask")


def test_review_cannot_drop_pool_names():
    assert _accept("水灵有什么技能", "自带：天洪、甩水。", "天洪和甩水都在。", {"keep": ["天洪", "甩水"]})
    assert not _accept("水灵有什么技能", "自带：天洪、甩水。", "灯灯去翻了总表。", {"keep": ["天洪", "甩水"]})


if __name__ == "__main__":
    test_skill_pool_comes_from_the_card()
    test_rate_question_searches_only_the_missing_fact()
    test_closed_web_says_the_catalog_has_no_rate()
    test_trace_says_the_catalog_miss_goes_outside()
    test_simple_skill_question_does_not_open_the_catalog()
    test_review_cannot_drop_pool_names()
    print("ok")
