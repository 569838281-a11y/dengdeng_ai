"""出场率 Hit / Bridge / Miss：阵容文先桥接；成员页不得升格为冠军（CRAG Ambiguous）。"""
from agents.job_ledger import drop
from agents.lived_memory import clear_memory
from agents.supervisor import run_cycle


def test_rate_bridge_then_member_page_asks_not_promotes():
    """IRCoT/CRAG：桥跳成员只填 lineup_members，禁止写成出场率冠军。"""
    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"
    sid = "bridge-rate"
    drop(sid)
    clear_memory(sid)
    calls = {"n": 0}

    def web(query, limit=10, **_kwargs):
        calls["n"] += 1
        q = query or ""
        if "出场精灵" in q or "成员" in q:
            return {
                "results": [{
                    "title": "毒队成员",
                    "url": "https://wiki.biligame.com/nrc/du",
                    "snippet": "这套毒队常用霹雳迪迪、水灵。",
                }]
            }
        return {
            "results": [{
                "title": "s2闪耀大赛全国前十分别在用什么阵容？",
                "url": "https://mp.weixin.qq.com/s/bridge",
                "snippet": "前十阵容大揭秘，榜九的毒队很强。",
            }]
        }

    try:
        first = run_cycle(
            question,
            session_id=sid,
            judged={"intent": "search", "request": question},
            web=web,
            review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
        )
    finally:
        drop(sid)

    book = first["ledger"]
    hops = (book.get("progress") or {}).get("hops") or []
    answer = first["order"].get("answer") or ""
    blob = answer + " ".join(item.get("text") or "" for item in (book.get("guesses") or []))
    assert "出场率最高的精灵是霹雳迪迪" not in blob
    assert not any("毒队的属性" in (item.get("fact") or "") for item in hops)
    assert calls["n"] >= 2
    assert book["progress"].get("next") == "need_ask"
    assert "不敢认定" in answer or "阵容里看到" in answer
    members = book["progress"].get("lineup_members") or []
    assert not members or "霹雳迪迪" in members or "水灵" in members


def test_bridge_weibo_title_does_not_become_champion():
    question = "闪耀大赛出场率最高的精灵用它威力最大的技能打天真性格的水灵能打出多少伤害"
    sid = "bridge-weibo-fake"
    drop(sid)
    clear_memory(sid)

    def web(query, limit=10, **_kwargs):
        q = query or ""
        if "出场精灵" in q or "成员" in q:
            return {
                "results": [{
                    "title": "是小小贰哦",
                    "url": "https://m.weibo.cn/status/5286872948673247",
                    "snippet": "转发微博",
                }]
            }
        return {
            "results": [{
                "title": "s2闪耀大赛全国前十分别在用什么阵容？",
                "url": "https://mp.weixin.qq.com/s/bridge",
                "snippet": "前十阵容大揭秘，榜九的毒队很强。",
            }]
        }

    try:
        first = run_cycle(
            question,
            session_id=sid,
            judged={"intent": "search", "request": question},
            web=web,
            review=lambda _question, speech, _evidence=None: {"pass": True, "text": speech},
        )
    finally:
        drop(sid)

    book = first["ledger"]
    blob = " ".join(
        [
            first["order"].get("answer") or "",
            " ".join(item.get("text") or "" for item in (book.get("guesses") or [])),
            " ".join(item.get("text") or "" for item in ((book.get("progress") or {}).get("hops") or [])),
        ]
    )
    assert "小小贰哦" not in blob
    assert "小小贰哦的属性" not in blob


if __name__ == "__main__":
    test_rate_bridge_then_member_page_asks_not_promotes()
    test_bridge_weibo_title_does_not_become_champion()
    print("ok")
