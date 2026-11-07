"""监督者按调度词派工。资料空了才问，补充先准入，选人程序只在证据够了之后调用。"""
import tempfile
from pathlib import Path

import agents.chat_notebook as nb
import agents.speech_review as speech_review
from agents.fact_memory import admit_utterance
from agents.job_ledger import drop
from agents.supervisor import run_cycle


def _keep_speech(_question, speech, _evidence=None, ask=None):
    return {"pass": True, "issues": [], "text": speech, "repaired": False}


speech_review.review_speech = _keep_speech


def _names():
    return ["水灵", "寂灭骨龙", "音速犬（本来的样子）", "绒光优优", "离心舞者", "贝古斯"]


def _lineup(_question, _session_id, _types, _cut=""):
    return {"ok": True, "names": _names(), "answer": "", "hard": []}


def _save(_question, names, _session_id, _replace=None):
    assert names == _names()
    return "灯灯记下了这一套出场。", True, "、".join(names)


def _empty_web(_query):
    return {"results": []}


def test_release_asks_count_without_web_or_lineup():
    called = {"web": 0, "lineup": 0, "warehouse": 0}

    def web(_query):
        called["web"] += 1
        return {"results": []}

    def lineup(*_args):
        called["lineup"] += 1
        return {"ok": False, "names": [], "answer": "", "hard": []}

    def warehouse(*_args):
        called["warehouse"] += 1
        return {"answer": "不该写仓库", "ok": True}

    cycle = run_cycle(
        "放生海枝枝",
        session_id="release-case",
        judged={"intent": "order", "request": "放生海枝枝"},
        web=web,
        lineup=lineup,
        warehouse=warehouse,
    )
    assert "几只" in cycle["order"]["answer"]
    assert cycle["order"]["ok"] is False
    assert called == {"web": 0, "lineup": 0, "warehouse": 0}
    assert cycle["ledger"]["slots"]["web"] == "closed"
    drop("release-case")


def test_unknown_team_asks_before_lineup():
    called = {"lineup": 0}

    def lineup(*_args):
        called["lineup"] += 1
        return _lineup(*_args)

    cycle = run_cycle(
        "以水灵为核心，限制星陨队",
        session_id="star-case",
        judged={"intent": "lineup", "request": "以水灵为核心，限制星陨队"},
        web=_empty_web,
        lineup=lineup,
        save=_save,
    )
    assert "星陨队" in cycle["order"]["answer"]
    assert called["lineup"] == 0
    assert cycle["ledger"]["requests"]
    assert cycle["ledger"]["guesses"] == []
    goals = [step.get("goal") or "" for step in cycle["ledger"]["plan"]]
    assert any("查名录" in goal for goal in goals)
    assert any("再走同一圈" in goal or "热门" in goal for goal in goals)
    drop("star-case")


def test_vague_reply_is_not_admitted_and_concrete_one_is():
    original_path = nb._PATH
    original_books = dict(nb._BOOKS)
    nb._BOOKS.clear()
    nb._PATH = Path(tempfile.mkdtemp()) / "chat_notebooks.json"
    sid = "admit-case"
    try:
        first = run_cycle(
            "以水灵为核心，限制星陨队",
            session_id=sid,
            judged={"intent": "lineup", "request": "以水灵为核心，限制星陨队"},
            web=_empty_web,
            lineup=_lineup,
            save=_save,
        )
        assert "星陨队" in first["order"]["answer"]
        vague = run_cycle(
            "那支很强",
            session_id=sid,
            judged={"intent": "remember", "request": "那支很强"},
            web=_empty_web,
            lineup=_lineup,
            save=_save,
        )
        assert vague["ledger"]["admitted"] == []
        assert "含糊" in vague["order"]["answer"] or "还缺" in vague["order"]["answer"]
        calls = {"lineup": 0, "save": 0, "web": []}

        def web(query):
            calls["web"].append(query)
            if "热门" in query:
                return {"results": [{"title": "热门阵容", "url": "https://wiki.biligame.com/nrc/hot", "snippet": "当前热门常见的是水灵"}]}
            return {"results": []}

        def lineup(*_args):
            calls["lineup"] += 1
            return _lineup(*_args)

        def save(*args):
            calls["save"] += 1
            return _save(*args)

        done = run_cycle(
            "幻系加上龙息帕尔，靠叠印记",
            session_id=sid,
            judged={"intent": "remember", "request": "幻系加上龙息帕尔，靠叠印记"},
            web=web,
            lineup=lineup,
            save=save,
        )
        assert done["ledger"]["admitted"][0]["source"] == "玩家"
        assert calls["lineup"] == 2
        assert calls["save"] == 1
        words = [step.get("goal") or "" for step in done["ledger"]["plan"]]
        assert any("两槽" in goal or "同一圈" in goal for goal in words)
        assert done["order"]["ok"] is True
        assert "热门" in calls["web"][0]
        rows = nb.admitted_of(sid)
        assert rows and rows[0]["source"] == "玩家"
    finally:
        drop(sid)
        nb._PATH = original_path
        nb._BOOKS.clear()
        nb._BOOKS.update(original_books)


def test_search_does_not_pick_a_roster():
    called = {"lineup": 0, "web": 0}

    def lookup(_question, use_web, _session_id):
        assert use_web is False
        return {"found": True, "answer": "水灵的特性是浸润。", "trial": None}

    def lineup(*_args):
        called["lineup"] += 1
        return _lineup(*_args)

    def web(_query):
        called["web"] += 1
        return {"results": []}

    cycle = run_cycle(
        "水灵的特性",
        session_id="search-case",
        judged={"intent": "search", "request": "水灵的特性"},
        lookup=lookup,
        lineup=lineup,
        web=web,
    )
    assert "浸润" in cycle["order"]["answer"]
    assert called == {"lineup": 0, "web": 0}
    assert cycle["ledger"]["roster"] == []
    drop("search-case")


def test_failed_check_uses_another_cut():
    seen = []

    def lineup(*args):
        seen.append(args[-1] if len(args) > 3 else "")
        if len(seen) == 1:
            return {"ok": False, "names": [], "answer": "灯灯按现有伙伴排不出六只。", "hard": ["tilt"]}
        return _lineup(*args)

    def web(query):
        if "热门" in query:
            return {"results": [{"title": "热门阵容", "url": "https://wiki.biligame.com/nrc/hot", "snippet": "当前热门常见的是水灵"}]}
        return {"results": []}

    cycle = run_cycle(
        "以火系为主组一套",
        session_id="cut-case",
        judged={"intent": "lineup", "request": "以火系为主组一套"},
        web=web,
        lineup=lineup,
        save=_save,
    )
    assert seen[0] == ""
    assert seen[1] == "alternate"
    assert cycle["order"]["ok"] is True
    drop("cut-case")


def test_followup_changes_the_previous_team():
    from agents.battle_orders import _roster_unbounded

    assert _roster_unbounded("该队伍不需要拘泥于仓库现有精灵")
    saved = []

    def web(query):
        if "星陨" in query:
            return {"results": [{"title": "洛克王国世界星陨队", "url": "https://wiki.biligame.com/nrc/star", "snippet": "星陨队是幻系加上龙息帕尔，靠叠印记"}]}
        if "热门" in query:
            return {"results": [
                {"title": "今日热榜", "url": "https://rebang.today", "snippet": "热门播客"},
                {"title": "洛克王国世界热门阵容", "url": "https://wiki.biligame.com/nrc/hot", "snippet": "当前热门是水灵"},
            ]}
        return {"results": []}

    def save(*args):
        saved.append(args[-1] if len(args) > 3 else None)
        return "灯灯记下了第 19 套出场。", True, "队伍配置为\n选取的理由是已记下。"

    sid = "carry-case"
    first = run_cycle(
        "组建一只以火神为主力的队伍，并且该队伍能有效针对星陨队",
        session_id=sid,
        judged={"intent": "lineup", "request": "组建一只以火神为主力的队伍，并且该队伍能有效针对星陨队"},
        web=web,
        lineup=_lineup,
        save=save,
    )
    assert first["order"]["ok"] is True
    assert "火神" in first["order"]["answer"]
    assert "https://rebang.today" not in first["order"]["answer"]
    second = run_cycle(
        "该队伍不需要拘泥于仓库现有精灵",
        session_id=sid,
        judged={"intent": "lineup", "request": "该队伍不需要拘泥于仓库现有精灵"},
        web=web,
        lineup=_lineup,
        save=save,
    )
    assert "星陨队" in second["ledger"]["check"].get("answer", "") or "星陨队" in second["order"]["answer"] or "火神" in second["order"]["answer"]
    assert "不扣仓库" in second["order"]["answer"]
    assert saved[0] is None
    assert saved[-1] == 19
    assert len(saved) == 2
    drop(sid)


def test_outside_ace_is_read_and_kept_on_followup():
    from agents.battle_orders import _save_with_guest
    from agents.rag_agent import _types_from_label
    from knowledge_search import _ace_label
    import agents.battle_orders as orders

    assert _ace_label("组建以魔力猫为主力，能针对地武队的队伍") == "魔力猫"
    assert _ace_label("组建一只以火神为主力的队伍") == "火神"
    assert _types_from_label("地武队") == ["地", "武"]
    assert _types_from_label("星陨队") == []
    card = "精灵：魔力猫\n属性：草\n自带：棘突、光能聚集、叶绿光束、藤绞"
    saved = []

    def web(query):
        if "魔力猫" in query:
            return {"results": [{
                "title": "洛克王国世界图鉴·魔力猫",
                "url": "https://wiki.biligame.com/nrc/cat",
                "snippet": card,
            }]}
        if "热门" in query:
            return {"results": [{
                "title": "洛克王国世界热门阵容",
                "url": "https://wiki.biligame.com/nrc/hot",
                "snippet": "当前热门是水灵",
            }]}
        return {"results": []}

    def guest_save(_question, companions, guest, replace_id=None):
        saved.append(replace_id)
        assert guest["name"] == "魔力猫"
        assert len(companions) == 5
        return "灯灯记下了第 19 套出场。", True, "队伍配置为\n选取的理由是已记下。"

    orders._save_with_guest = guest_save
    sid = "magic-cat"
    try:
        first = run_cycle(
            "组建以魔力猫为主力，能针对地武队的队伍",
            session_id=sid,
            judged={"intent": "lineup", "request": "组建以魔力猫为主力，能针对地武队的队伍"},
            web=web,
            lineup=_lineup,
            save=_save,
        )
        assert first["order"]["ok"] is True
        assert "魔力猫" in first["order"]["answer"]
        assert "按现有伙伴排不出六只" not in first["order"]["answer"]
        assert "https://wiki.biligame.com/nrc/cat" in first["order"]["answer"]
        second = run_cycle(
            "该魔力猫队伍中精灵不局限于仓库精灵",
            session_id=sid,
            judged={"intent": "remember", "request": "该魔力猫队伍中精灵不局限于仓库精灵"},
            web=web,
            lineup=_lineup,
            save=_save,
        )
        assert "魔力猫" in second["order"]["answer"]
        assert "不扣仓库" in second["order"]["answer"]
        assert saved[0] is None
        assert saved[-1] == 19
        assert len(saved) == 2
    finally:
        orders._save_with_guest = _save_with_guest
        drop(sid)


def test_speech_review_rewrites_before_the_player_hears_it():
    from agents.thoughts import bind, reset

    seen = []

    def review(_question, _speech, evidence=None, ask=None):
        names = "、".join((evidence or {}).get("names") or [])
        return {
            "pass": False,
            "issues": ["core"],
            "text": f"灯灯记下了这一套。六只是{names}。这句话已经看过。",
            "repaired": True,
        }

    token = bind(lambda _kind, text: seen.append(text))
    try:
        def web(query):
            if "热门" in query:
                return {"results": [{"title": "热门", "url": "https://wiki.biligame.com/nrc/hot", "snippet": "当前热门是水灵"}]}
            return {"results": []}

        cycle = run_cycle(
            "以水灵为核心组一套",
            session_id="review-case",
            judged={"intent": "lineup", "request": "以水灵为核心组一套"},
            web=web,
            lineup=_lineup,
            save=_save,
            review=review,
        )
    finally:
        reset(token)
        drop("review-case")
    assert "这句话已经看过" in cycle["order"]["answer"]
    assert "水灵" in cycle["order"]["answer"]
    assert cycle["ledger"]["speech_review"]["issues"] == ["core"]
    assert any("答没答上核心" in text for text in seen)
    assert any("还没答上你问的核心" in text for text in seen)
    assert any("没说稳的地方收掉了" in text for text in seen)


def test_search_thought_names_the_question():
    from agents.thoughts import bind, reset

    seen = []
    token = bind(lambda kind, text: seen.append((kind, text)))

    def lookup(*_args):
        return {"found": True, "answer": "水灵是水系。"}

    try:
        run_cycle(
            "水灵是什么系的",
            session_id="type-case",
            judged={"intent": "search", "request": "水灵是什么系的"},
            lookup=lookup,
            web=_empty_web,
            lineup=_lineup,
            save=_save,
        )
    finally:
        reset(token)
        drop("type-case")
    joined = "\n".join(text for _kind, text in seen)
    assert "拆成查水灵" in joined
    assert "水灵是什么系的" in joined
    assert ("read", "正在看水灵") in seen
    assert "仓库" not in joined
    assert "出场规则" not in joined


def test_steps_name_the_split_and_the_page():
    from agents.thoughts import bind, reset

    seen = []
    token = bind(lambda kind, text: seen.append((kind, text)))
    try:
        def web(_query):
            return {"results": [{"title": "星陨队打法", "url": "https://wiki.biligame.com/nrc/star", "snippet": "星陨队的常见打法"}]}

        run_cycle(
            "以水灵为核心，限制星陨队",
            session_id="trace-case",
            judged={"intent": "lineup", "request": "以水灵为核心，限制星陨队"},
            web=web,
            lineup=_lineup,
            save=_save,
        )
    finally:
        reset(token)
        drop("trace-case")
    assert any(text.startswith("灯灯先把这件事拆成") and "看星陨队" in text for _kind, text in seen)
    assert ("read", "正在名录里找星陨队") in seen
    assert ("read", "正在阅读星陨队打法（https://wiki.biligame.com/nrc/star）") in seen


def test_rewrite_of_catalog_is_rejected():
    rejected = admit_utterance("nobody", "水灵的特性是其他精灵", {"kind": "composition", "label": "星陨队"})
    assert rejected["keep"] is False


if __name__ == "__main__":
    test_release_asks_count_without_web_or_lineup()
    test_unknown_team_asks_before_lineup()
    test_vague_reply_is_not_admitted_and_concrete_one_is()
    test_search_does_not_pick_a_roster()
    test_failed_check_uses_another_cut()
    test_followup_changes_the_previous_team()
    test_outside_ace_is_read_and_kept_on_followup()
    test_speech_review_rewrites_before_the_player_hears_it()
    test_search_thought_names_the_question()
    test_steps_name_the_split_and_the_page()
    test_rewrite_of_catalog_is_rejected()
    print("ok")
