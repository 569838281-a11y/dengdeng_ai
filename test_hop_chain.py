"""多步问题先定步数，查完一步再写下一步。问你之后怎么接不在这里。"""
import agents.web_read as web_read
from agents.fact_read import chain_answer, classify_hops, next_fact, read_one
from agents.job_ledger import blank, drop
from agents.supervisor import _may_web, run_cycle
from agents.thoughts import bind, reset
from agents.web_read import web_anchors as page_anchors


def _fast_rank(fact, texts):
    anchors = page_anchors(fact) or [fact]
    return [float(sum(anchor in (text or "") for anchor in anchors)) for text in texts]


def test_single_question_stays_one_step():
    rated = classify_hops("水灵的种族值是多少？")
    assert rated == {"kind": "single", "limit": 1, "first": ""}
    named = classify_hops("水灵使用本系技能，哪个本系技能的威力更高？")
    assert named["kind"] == "chain"
    assert named["limit"] == 4
    assert named["first"] == "水灵的属性"


def test_appearance_chain_writes_the_next_fact_from_the_page():
    question = "出场率最高的精灵使用本系技能攻击聪明性格水灵，哪个本系技能的威力更高？"
    rated = classify_hops(question)
    assert rated["first"] == "出场率最高的精灵"
    steps = [{
        "fact": "出场率最高的精灵",
        "text": "出场率最高的精灵是霹雳迪迪。",
        "lines": ["出场率最高的精灵是霹雳迪迪。"],
        "names": ["霹雳迪迪"],
    }]
    called = {"n": 0}

    def ask(_question, _steps):
        called["n"] += 1
        return "利灯鱼的属性"

    result = next_fact(question, steps, ask=ask)
    assert called["n"] == 1
    assert result["action"] == "next"
    assert result["fact"] == "霹雳迪迪的属性"
    steps.append({"fact": result["fact"], "text": "属性：电、光。", "lines": ["属性：电、光。"], "names": ["霹雳迪迪"]})
    result = next_fact(question, steps, ask=ask)
    assert result["fact"] == "霹雳迪迪的本系技能和威力"
    one = read_one("霹雳迪迪的本系技能和威力")
    assert one["covered"]
    steps.append({"fact": result["fact"], "text": " ".join(one["lines"]), "lines": one["lines"], "names": ["霹雳迪迪"]})
    result = next_fact(question, steps, ask=ask)
    assert result["fact"] == "水灵的属性"
    steps.append({"fact": "水灵的属性", "text": "属性：水。", "lines": ["属性：水。"], "names": ["水灵"]})
    result = next_fact(question, steps, ask=ask)
    assert result["action"] == "done"
    assert "超导" in result["answer"]
    assert "克制倍率2" in result["answer"]
    assert "合起来是180" in result["answer"]
    assert "聪明性格没有写在威力规则里" in result["answer"]
    assert "这一比只看技能威力" in result["answer"]


def test_ungrounded_name_stops_without_a_new_fact():
    question = "出场率最高的精灵使用本系技能攻击聪明性格水灵，哪个本系技能的威力更高？"
    steps = [{
        "fact": "出场率最高的精灵",
        "text": "这一页没有写出精灵名字。",
        "lines": ["这一页没有写出精灵名字。"],
        "names": [],
    }]

    def ask(_question, _steps):
        return "利灯鱼的属性"

    result = next_fact(question, steps, ask=ask)
    assert result["action"] == "stop"
    assert result["fact"] == ""
    assert "利灯鱼" not in chain_answer(question, steps)


def test_named_attacker_finishes_from_the_catalog():
    question = "水灵使用本系技能，哪个本系技能的威力更高？"
    one = read_one("水灵的本系技能和威力")
    assert one["covered"]
    powers = []
    for line in one["lines"]:
        import re
        matched = re.search(r"威力\s*(\d+)", line)
        if matched:
            powers.append((int(matched.group(1)), line.split("｜", 1)[0]))
    best = max(powers)
    answer = _run(question, lambda _query: {"results": []})
    assert best[1] in answer["order"]["answer"]
    assert str(best[0]) in answer["order"]["answer"]
    assert answer["ledger"]["progress"].get("web_calls") in {None, 0}
    assert "水灵的本系技能和威力" in answer["ledger"]["progress"]["fact_queries"]


def test_missing_second_hop_does_not_search_the_third():
    """名录外的「幻影鱼」不能假 Hit；应停在出场率缺口，不要去查属性/技能第三跳。"""
    question = "出场率最高的精灵使用本系技能攻击聪明性格水灵，哪个本系技能的威力更高？"
    seen = []

    def web(query):
        seen.append(query)
        if "幻影鱼" in query:
            return {"results": []}
        if "出场率最高的精灵" in query and "官网" not in query:
            return {"results": [{
                "title": "出场率",
                "url": "https://rocom.qq.com/rate",
                "snippet": "出场率最高的精灵是幻影鱼。",
            }]}
        return {"results": []}

    answer = _run(question, web)
    assert not any("幻影鱼的属性" in query for query in seen)
    assert not any("本系技能" in query for query in seen)
    assert "幻影鱼" not in (answer["order"]["answer"] or "") or "跟灯灯说" in (answer["order"]["answer"] or "")
    assert answer["ledger"]["progress"]["next"] == "need_ask"


def test_full_chain_compares_the_named_sprite():
    question = "出场率最高的精灵使用本系技能攻击聪明性格水灵，哪个本系技能的威力更高？"
    seen = []
    thoughts = []

    def web(query):
        seen.append(query)
        if "出场率最高的精灵" in query and "官网" not in query:
            return {"results": [{
                "title": "出场率",
                "url": "https://rocom.qq.com/rate",
                "snippet": "出场率最高的精灵是霹雳迪迪。",
            }]}
        return {"results": []}

    token = bind(lambda kind, text: thoughts.append((kind, text)))
    try:
        answer = _run(question, web)
    finally:
        reset(token)
    text = answer["order"]["answer"]
    queries = answer["ledger"]["progress"]["fact_queries"]
    assert queries[0] == "出场率最高的精灵"
    assert queries[1:] == ["霹雳迪迪的属性", "霹雳迪迪的本系技能和威力", "水灵的属性"]
    assert "超导" in text
    assert "克制倍率2" in text
    assert "合起来是180" in text
    assert "虹光冲击的威力更高" not in text
    assert "聪明性格没有写在威力规则里" in text
    assert "属性：水" in text
    assert not any("本系技能" in query for query in seen)
    assert any(item[1] == "正在查第1步：出场率最高的精灵" for item in thoughts)
    assert any("正在查第4步：水灵的属性" in item[1] for item in thoughts)


def test_web_budget_is_per_fact_on_a_chain():
    book = blank("hop-budget", "出场率最高的精灵")
    book["progress"]["hop_kind"] = "chain"
    book["progress"]["web_calls"] = 1
    book["slots"]["tried"] = ["web:出场率最高的精灵"]
    assert _may_web(book, "幻影鱼的属性")
    book["progress"]["web_calls"] = 3
    assert not _may_web(book, "另一句")
    single = blank("single-budget", "水灵的种族值")
    single["slots"]["tried"] = ["web:水灵的种族值"]
    assert not _may_web(single, "水灵的特性")


def test_strongest_skill_reads_the_pool_then_each_power():
    named = "霹雳迪迪用威力最大的技能打天真性格的水灵能打出多少伤害"
    steps = [{
        "fact": "霹雳迪迪的属性",
        "text": "属性：电、光。",
        "lines": ["属性：电、光。"],
        "names": ["霹雳迪迪"],
    }]

    def ask_unknown(_question, _steps):
        return "霹雳迪迪的招式表"

    result = next_fact(named, steps, ask=ask_unknown)
    assert result["fact"] == "霹雳迪迪的技能和威力"

    def ask_power(_question, _steps):
        return "霹雳迪迪的技能及威力"

    accepted = next_fact(named, steps, ask=ask_power)
    assert accepted["fact"] == "霹雳迪迪的技能及威力"
    one = read_one(accepted["fact"])
    assert one["covered"]
    same = {line.split("｜", 1)[0] for line in read_one("霹雳迪迪的本系技能和威力")["lines"]}
    assert any(line.split("｜", 1)[0] not in same for line in one["lines"])

    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"

    def web(query):
        if "登场率" in query or "出场率" in query:
            return {"results": [{
                "title": "闪耀大赛",
                "url": "https://rocom.qq.com/rate",
                "snippet": "闪耀大赛出场率最高的精灵是霹雳迪迪。",
            }]}
        return {"results": []}

    answer = _run(question, web)
    text = answer["order"]["answer"]
    queries = answer["ledger"]["progress"]["fact_queries"]
    assert "霹雳迪迪的技能和威力" in queries
    assert "技能池里" in text
    assert "威力最大" in text
    assert "伤害量是" in text
    assert "天真性格没有写在威力规则里" in text


def _run(question, web):
    from agents.lived_memory import clear_memory

    previous = web_read.scheme_c
    web_read.scheme_c = _fast_rank
    sid = "hop-" + question[:8]
    drop(sid)
    clear_memory(sid)
    try:
        return run_cycle(
            question,
            session_id=sid,
            judged={"intent": "search", "request": question},
            web=web,
            review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
        )
    finally:
        web_read.scheme_c = previous
        drop(sid)
        clear_memory(sid)


if __name__ == "__main__":
    test_single_question_stays_one_step()
    test_appearance_chain_writes_the_next_fact_from_the_page()
    test_ungrounded_name_stops_without_a_new_fact()
    test_named_attacker_finishes_from_the_catalog()
    test_missing_second_hop_does_not_search_the_third()
    test_full_chain_compares_the_named_sprite()
    test_web_budget_is_per_fact_on_a_chain()
    test_strongest_skill_reads_the_pool_then_each_power()
    print("ok")
