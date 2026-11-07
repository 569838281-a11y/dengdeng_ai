"""缺的一格停着等。后一句抄出名字，写回原问，接着同一串步骤。"""
import agents.web_read as web_read
from agents.followup import copied_name, same_task, standalone_question
from agents.job_ledger import drop
from agents.supervisor import run_cycle
from agents.web_read import web_anchors as page_anchors


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


def test_rewrite_and_copy_keep_one_name():
    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"
    assert copied_name("闪耀大赛出场率最高的精灵是霹雳迪迪") == "霹雳迪迪"
    assert copied_name("霹雳迪迪和水灵") == ""
    assert copied_name("水灵的特性是什么") == ""
    assert same_task(question, "另外，水灵的特性是什么") is False
    rewritten = standalone_question(question, "闪耀大赛登场率最高的精灵", "霹雳迪迪")
    assert rewritten.startswith("霹雳迪迪用威力最大的技能打")
    assert "水灵" in rewritten
    assert "出场率" not in rewritten


def test_missing_rate_waits_and_the_next_sentence_continues():
    from agents.lived_memory import clear_memory

    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"
    sid = "slot-fill"
    drop(sid)
    clear_memory(sid)

    def web(_query):
        return {"results": []}

    try:
        first = _cycle(
            question,
            session_id=sid,
            judged={"intent": "search", "request": question},
            web=web,
            review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
        )
        assert first["ledger"]["progress"]["next"] == "need_ask"
        assert "没翻到" in first["order"]["answer"]
        second = _cycle(
            "闪耀大赛出场率最高的精灵是霹雳迪迪",
            session_id=sid,
            judged={"intent": "search", "request": "闪耀大赛出场率最高的精灵是霹雳迪迪"},
            web=web,
            review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
        )
    finally:
        drop(sid)
    text = second["order"]["answer"]
    assert "霹雳迪迪" in text
    assert "不一致" not in text
    assert "天真性格没有写在威力规则里" in text
    assert second["ledger"]["progress"]["next"] == "stop"
    assert second["ledger"]["roster"] == []
    assert any(item.get("source") == "玩家" for item in second["ledger"]["admitted"])


if __name__ == "__main__":
    test_rewrite_and_copy_keep_one_name()
    test_missing_rate_waits_and_the_next_sentence_continues()
    print("ok")
