"""A/B/C 类级验收：CRAG 槽、出场率 archival、人设故事路由。"""
from agents.evidence_slots import AMBIGUOUS, CORRECT, INCORRECT, crag_rate_champion
from agents.fact_read import _name_from_appearance, names_in
from agents.job_ledger import drop
from agents.lived_memory import absorb_exchange, clear_memory, extract_facts, recall_answer
from agents.story_read import is_persona_story, read_dengdeng_story
from agents.supervisor import run_cycle
from agents.web_read import _rate_champion_name, read_web


def _search(items):
    def search(_query, limit=10, **_kwargs):
        return {"results": list(items)[:limit]}

    return search


def _rank(_fact, texts):
    return [1.0] * len(texts)


# ----- A: 假冠军类 -----
def test_a_descriptive_title_incorrect():
    title = "《洛克王国：世界》S2精灵登场率TO10,独角兽狼王未上榜，第一稳稳克制凡鹰。"
    assert _rate_champion_name(title) == ""
    judged = crag_rate_champion(title)
    assert judged["status"] in {INCORRECT, AMBIGUOUS}
    assert not judged.get("champion")


def test_a_weibo_nick_not_entity():
    assert names_in("榜九的毒队出场精灵", "是小小贰哦") == []
    assert _name_from_appearance([{
        "fact": "出场率最高的精灵",
        "text": "是小小贰哦",
        "names": [],
    }]) == ""


def test_a_lineup_page_ambiguous_not_champion():
    """阵容成员页有名录名 → Ambiguous，不得 Correct Hit。"""
    pool = "这套毒队常用霹雳迪迪、水灵、海豹船长。"
    judged = crag_rate_champion(pool, fill="bridge", bridge="榜九的毒队")
    assert judged["status"] == AMBIGUOUS
    assert not judged.get("champion")
    assert "霹雳迪迪" in (judged.get("members") or []) or "海豹船长" in (judged.get("members") or [])


def test_a_true_champion_sentence_correct():
    judged = crag_rate_champion("闪耀大赛出场率最高的精灵是霹雳迪迪。")
    assert judged["status"] == CORRECT
    assert judged["champion"] == "霹雳迪迪"


def test_a_bridge_cycle_does_not_promote_member():
    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"
    sid = "abc-bridge-no-promote"
    drop(sid)
    clear_memory(sid)

    def web(query, limit=10, **_kwargs):
        q = query or ""
        if "出场精灵" in q or "成员" in q:
            return {"results": [{
                "title": "毒队成员",
                "url": "https://wiki.biligame.com/nrc/du",
                "snippet": "这套毒队常用霹雳迪迪、海豹船长、水灵。",
            }]}
        return {"results": [{
            "title": "s2闪耀大赛全国前十分别在用什么阵容？",
            "url": "https://mp.weixin.qq.com/s/bridge",
            "snippet": "前十阵容大揭秘，榜九的毒队很强。",
        }]}

    try:
        first = run_cycle(
            question,
            session_id=sid,
            judged={"intent": "search", "request": question},
            web=web,
            review=lambda _q, speech, _e=None: {"pass": True, "text": speech},
        )
    finally:
        drop(sid)
    answer = first["order"].get("answer") or ""
    blob = answer + " ".join(item.get("text") or "" for item in (first["ledger"].get("guesses") or []))
    assert "海豹船长" not in blob or "不敢认定" in answer
    assert "出场率最高的精灵是海豹船长" not in blob
    assert "出场率最高的精灵是霹雳迪迪" not in blob
    assert first["ledger"]["progress"].get("next") == "need_ask" or "不敢认定" in answer


# ----- B: 出场率 archival -----
def test_b_extract_and_recall_rate_predicate():
    sid = "abc-rate-mem"
    drop(sid)
    clear_memory(sid)
    try:
        facts = extract_facts(
            "闪耀大赛出场率最高的是谁",
            "灯灯翻到：出场率最高的精灵是霹雳迪迪。",
        )
        assert any(item.get("relation") == "appearance_rate_top1" for item in facts)
        absorb_exchange(sid, "闪耀大赛出场率最高的精灵能打出多少伤害", "出场率最高的精灵是霹雳迪迪。属性：电。")
        recalled = recall_answer(sid, "闪耀大赛出场率最高的是谁")
        assert "霹雳迪迪" in recalled
        assert recall_answer(sid, "你能讲讲你成长的故事吗") == ""
    finally:
        drop(sid)


def test_b_followup_uses_memory_not_web():
    sid = "abc-rate-follow"
    drop(sid)
    clear_memory(sid)
    calls = {"n": 0}

    def web(query, limit=10, **_kwargs):
        calls["n"] += 1
        return {"results": [{
            "title": "出场率",
            "url": "https://rocom.qq.com/rate",
            "snippet": "闪耀大赛出场率最高的精灵是霹雳迪迪。",
        }]}

    try:
        absorb_exchange(sid, "出场率最高的精灵", "出场率最高的精灵是霹雳迪迪。")
        second = run_cycle(
            "闪耀大赛出场率最高的是谁",
            session_id=sid,
            judged={"intent": "search", "request": "闪耀大赛出场率最高的是谁"},
            web=web,
            review=lambda _q, speech, _e=None: {"pass": True, "text": speech},
        )
        assert "霹雳迪迪" in (second["order"].get("answer") or "")
        assert calls["n"] == 0
    finally:
        drop(sid)


# ----- C: 人设故事 -----
def test_c_persona_story_detect_and_read():
    assert is_persona_story("你能讲讲你成长的故事吗")
    assert is_persona_story("灯灯，介绍一下你自己的经历")
    assert not is_persona_story("海豹船长的故事是什么")
    story = read_dengdeng_story("你能讲讲你成长的故事吗")
    assert story["covered"]
    assert "灯灯" in story["speech"]
    assert "海豹船长" not in story["speech"]


def test_c_story_cycle_ignores_prior_sprite():
    sid = "abc-story"
    drop(sid)
    clear_memory(sid)
    absorb_exchange(sid, "出场率", "出场率最高的精灵是海豹船长。属性：武、水。")
    try:
        out = run_cycle(
            "你能讲讲你成长的故事吗",
            session_id=sid,
            judged={"intent": "persona_story", "request": "你能讲讲你成长的故事吗"},
            web=lambda *_a, **_k: {"results": []},
            review=lambda _q, speech, _e=None: {"pass": True, "text": speech},
        )
        answer = out["order"].get("answer") or ""
        assert "海豹船长" not in answer
        assert "灯灯" in answer or "噔噔" in answer
    finally:
        drop(sid)


if __name__ == "__main__":
    test_a_descriptive_title_incorrect()
    test_a_weibo_nick_not_entity()
    test_a_lineup_page_ambiguous_not_champion()
    test_a_true_champion_sentence_correct()
    test_a_bridge_cycle_does_not_promote_member()
    test_b_extract_and_recall_rate_predicate()
    test_b_followup_uses_memory_not_web()
    test_c_persona_story_detect_and_read()
    test_c_story_cycle_ignores_prior_sprite()
    print("ok")
