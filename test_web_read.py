"""网页读取：站点分、C 重排的接口、CRAG 滤句。重排分数在这里用桩，避免每条规则都加载模型。"""
from agents.web_read import grade_sentence, read_web, scheme_c, web_anchors


def _search(rows):
    def search(query, limit=10):
        assert "洛克王国世界" in query
        assert limit == 10
        return {"results": rows}

    return search


def _rank(_fact, texts):
    return [float(index + 1) for index in range(len(texts))]


def test_tiers_put_official_before_wiki_before_video():
    rows = [
        {
            "title": "浪潮视频",
            "url": "https://www.bilibili.com/video/BV1wave",
            "snippet": "浪潮的能耗是使用水系技能后全技能能耗-2。",
            "plays": 8000,
        },
        {
            "title": "浪潮",
            "url": "https://wiki.biligame.com/nrc/wave",
            "snippet": "浪潮的能耗是使用水系技能后全技能能耗-2。",
        },
        {
            "title": "浪潮",
            "url": "https://rocom.qq.com/wave",
            "snippet": "浪潮的能耗是使用水系技能后全技能能耗-2。",
        },
    ]
    outcome = read_web("浪潮的能耗", search=_search(rows), rank=_rank)
    assert [item["tier"] for item in outcome["covered"]] == [0]
    assert outcome["conflicts"] == []
    assert outcome["text"].startswith("浪潮的能耗是使用水系技能后全技能能耗-2")
    assert outcome["covered"][0]["url"].startswith("https://rocom.qq.com/")


def test_outside_pages_are_read_and_official_still_wins():
    outside = read_web("浪潮的能耗", search=_search([
        {"title": "站外", "url": "https://www.gamersky.com/wave", "snippet": "浪潮的能耗是2。"},
    ]), rank=_rank)
    assert "能耗是2" in outside["text"]
    assert outside["covered"][0]["tier"] == 4
    low = read_web("浪潮的能耗", search=_search([
        {"title": "低播放", "url": "https://www.bilibili.com/video/BV1low", "snippet": "浪潮的能耗是2。", "plays": 800},
    ]), rank=_rank)
    assert low["covered"][0]["tier"] == 3
    mixed = read_web("浪潮的能耗", search=_search([
        {"title": "站外", "url": "https://www.gamersky.com/wave", "snippet": "浪潮的能耗是9。"},
        {"title": "浪潮", "url": "https://rocom.qq.com/wave", "snippet": "浪潮的能耗是使用水系技能后全技能能耗-2。"},
    ]), rank=_rank)
    assert mixed["covered"][0]["url"].startswith("https://rocom.qq.com/")
    assert "是9" not in mixed["text"]
    assert grade_sentence("闪耀大赛登场率最高的精灵", "闪耀大赛出场率最高的精灵是霹雳迪迪。") == "对得上"


def test_video_play_count_can_be_read_from_the_page_text():
    rows = [{
        "title": "浪潮视频",
        "url": "https://www.bilibili.com/video/BV1ok",
        "snippet": "播放量 1.2万。浪潮的能耗是使用后全技能能耗-2。",
    }]
    outcome = read_web("浪潮的能耗", search=_search(rows), rank=_rank)
    assert outcome["covered"][0]["plays"] == 12000
    assert outcome["covered"][0]["tier"] == 2


def test_crag_keeps_a_matching_sentence_and_holds_a_partial_one():
    rows = [{
        "title": "技能总表",
        "url": "https://wiki.biligame.com/nrc/skills",
        "snippet": "技能一共有五百多个分类。浪潮很常见于水系精灵。浪潮的能耗是使用后全技能能耗-2。",
    }]
    outcome = read_web("浪潮的能耗", search=_search(rows), rank=_rank)
    assert "五百多个" not in outcome["text"]
    assert "浪潮很常见" not in outcome["text"]
    assert "能耗-2" in outcome["text"]
    assert any("浪潮很常见于水系精灵" in item["text"] for item in outcome["ambiguous"])
    assert all(item["grade"] == "含糊" for item in outcome["ambiguous"])


def test_unprovided_counts_and_a_final_number_does_not():
    rows = [{
        "title": "星陨",
        "url": "https://rocom.qq.com/star",
        "snippet": "星陨造成的额外伤害数值未提供。",
    }]
    found = read_web("星陨额外伤害", search=_search(rows), rank=_rank)
    assert "未提供" in found["text"]
    missed = read_web("这一下的最终伤害数字", search=_search(rows), rank=_rank)
    assert missed["text"] == ""
    assert web_anchors("这一下的最终伤害数字") == []
    assert web_anchors("利灯鱼的种族值") == ["利灯鱼", "种族值"]


def test_same_tier_follows_the_rerank_score():
    rows = [{
        "title": "两条",
        "url": "https://wiki.biligame.com/nrc/two",
        "snippet": "浪潮的能耗先说一遍。浪潮的能耗再说一遍并且更具体。",
    }]

    def rank(_fact, texts):
        return [0.2, 0.9][:len(texts)]

    outcome = read_web("浪潮的能耗", search=_search(rows), rank=rank)
    assert outcome["covered"][0]["text"].endswith("更具体")


def test_grade_labels():
    assert grade_sentence("浪潮的能耗", "浪潮的能耗是2") == "对得上"
    assert grade_sentence("浪潮的能耗", "浪潮很常见") == "含糊"
    assert grade_sentence("浪潮的能耗", "技能一共有五百多个") == "对不上"


def test_miss_then_second_query_finds_the_sentence():
    seen = []

    def search(query, limit=10):
        seen.append(query)
        if "的种族值" in query:
            return {"results": [{"title": "总表", "url": "https://wiki.biligame.com/nrc/all", "snippet": "技能一共有五百多个分类。"}]}
        return {"results": [{"title": "官网", "url": "https://rocom.qq.com/fish", "snippet": "利灯鱼的种族值合计是300。"}]}

    outcome = read_web("利灯鱼的种族值", search=search, rank=_rank)
    assert len(seen) == 2
    assert "300" in outcome["text"]
    assert outcome["queries"] == seen


def test_official_number_wins_and_same_tier_conflict_stops():
    rows = [
        {"title": "视频", "url": "https://www.bilibili.com/video/BV1ok", "plays": 9000, "snippet": "利灯鱼的种族值合计是999。"},
        {"title": "百科", "url": "https://wiki.biligame.com/nrc/fish", "snippet": "利灯鱼的种族值合计是502。"},
        {"title": "官网", "url": "https://rocom.qq.com/fish", "snippet": "利灯鱼的种族值合计是300。"},
    ]
    outcome = read_web("利灯鱼的种族值", search=_search(rows), rank=_rank)
    assert "300" in outcome["text"]
    assert "502" not in outcome["text"]
    assert "999" not in outcome["text"]
    assert len(outcome["conflicts"]) == 2
    clash = [
        {"title": "甲", "url": "https://wiki.biligame.com/nrc/a", "snippet": "利灯鱼的种族值合计是300。"},
        {"title": "乙", "url": "https://wiki.biligame.com/nrc/b", "snippet": "利灯鱼的种族值合计是400。"},
    ]
    preferred = read_web("利灯鱼的种族值", search=_search(clash), rank=_rank)
    assert preferred["unsettled"] is False
    assert preferred["text"]
    # 同一档打架时采信一条，另一条进冲突，不再整段放弃。
    assert preferred["conflicts"]
    assert ("300" in preferred["text"]) or ("400" in preferred["text"])


def test_scheme_c_scores_a_related_sentence_higher():
    scores = scheme_c("浪潮的能耗", ["今天天气不错", "浪潮的能耗是使用后全技能能耗-2"])
    assert len(scores) == 2
    assert scores[1] > scores[0]


def test_rate_page_can_match_one_key_and_a_name():
    assert grade_sentence("闪耀大赛登场率最高的精灵", "最高的是霹雳迪迪。", "闪耀大赛出场率") == "对得上"
    assert grade_sentence("闪耀大赛登场率最高的精灵", "今天天气不错") == "对不上"
    wiki = {
        "title": "闪耀大赛出场率",
        "url": "https://wiki.biligame.com/nrc/rate",
        "snippet": "这一季最高的是霹雳迪迪。",
    }
    video = {
        "title": "统计",
        "url": "https://www.bilibili.com/video/BV1rate",
        "plays": 5000,
        "snippet": "闪耀大赛登场率榜首霹雳迪迪。",
    }
    agreed = read_web("闪耀大赛登场率最高的精灵", search=_search([wiki, video]), rank=_rank)
    assert "霹雳迪迪" in agreed["text"]
    assert agreed["final_information"]
    assert "No helpful information found" not in agreed["final_information"]
    clash = read_web("闪耀大赛登场率最高的精灵", search=_search([
        {"title": "甲", "url": "https://wiki.biligame.com/nrc/a", "snippet": "闪耀大赛出场率最高的是霹雳迪迪。"},
        {"title": "乙", "url": "https://wiki.biligame.com/nrc/b", "snippet": "闪耀大赛出场率最高的是水灵。"},
    ]), rank=_rank)
    assert clash["unsettled"] is False
    assert clash["text"]
    assert ("霹雳迪迪" in clash["text"]) or ("水灵" in clash["text"])
    assert clash["conflicts"]
    alone = read_web("闪耀大赛登场率最高的精灵", search=_search([video]), rank=_rank)
    # B 站是优先站，一页相关摘录即可留下，不再要求两页互证。
    assert "霹雳迪迪" in alone["text"]
    assert alone["final_information"]
    assert "No helpful information found" not in alone["final_information"]


def test_preferred_sites_keep_related_snippets_without_a_catalog_name():
    wiki = {
        "title": "狂欢怪谈赛季冲刺",
        "url": "https://wiki.biligame.com/nrc/s2",
        "snippet": "S2赛季奇遇新精灵包含猴麦仔家族、烟花团家族、加油海葵家族。",
    }
    open_web = {
        "title": "杂文",
        "url": "https://example.com/other",
        "snippet": "今天天气不错。",
    }
    outcome = read_web("s2赛季的奇遇精灵", search=_search([wiki, open_web]), rank=_rank)
    assert outcome["unsettled"] is False
    assert "猴麦仔" in outcome["text"] or "奇遇" in outcome["text"]
    assert "今天天气不错" not in outcome["text"]


def test_rate_lineup_chatter_without_a_name_does_not_fill():
    wechat = {
        "title": "s2闪耀大赛全国前十分别在用什么阵容？",
        "url": "https://mp.weixin.qq.com/s/demo",
        "snippet": "前十阵容大揭秘，抄作业指南来了！本篇只谈阵容搭配思路。",
    }
    outcome = read_web("闪耀大赛登场率最高的精灵", search=_search([wechat]), rank=_rank)
    assert outcome["text"] == ""
    assert outcome.get("fill") == "bridge"
    assert "前十" in (outcome.get("bridge") or "") or "阵容" in (outcome.get("bridge") or "")
    assert "霹雳迪迪" not in (outcome.get("final_information") or "")


def test_rate_rejects_descriptive_false_champion():
    """标题「第一稳稳克制凡鹰」不能假 Hit 成「稳稳克制凡鹰」。"""
    from agents.web_read import _rate_champion_name

    title = "《洛克王国：世界》S2精灵登场率TO10,独角兽狼王未上榜，第一稳稳克制凡鹰。"
    assert _rate_champion_name(title) == ""
    outcome = read_web(
        "闪耀大赛登场率最高的精灵",
        search=_search([{
            "title": title,
            "url": "https://mp.weixin.qq.com/s/fake-rate",
            "snippet": title,
        }]),
        rank=_rank,
    )
    assert outcome.get("name") in {"", None}
    assert outcome.get("fill") in {"bridge", "miss"}
    assert "稳稳克制凡鹰" not in (outcome.get("text") or "")


def test_bridge_rejects_weibo_nick_as_sprite():
    """桥跳成员页标题「是小小贰哦」不能当成出场精灵。"""
    from agents.fact_read import _name_from_appearance, names_in

    assert names_in("榜九的毒队出场精灵", "是小小贰哦") == []
    assert (
        _name_from_appearance([{
            "fact": "出场率最高的精灵",
            "text": "是小小贰哦",
            "names": [],
        }])
        == ""
    )
    assert _name_from_appearance([{
        "fact": "出场率最高的精灵",
        "text": "出场率最高的精灵是霹雳迪迪。",
        "names": [],
    }]) == "霹雳迪迪"


def test_rate_does_not_treat_lineup_member_as_champion():
    wechat = {
        "title": "s2闪耀大赛全国前十分别在用什么阵容？",
        "url": "https://mp.weixin.qq.com/s/hai",
        "snippet": "前十阵容大揭秘。榜九常用海枝枝（翠绿纶布），还有水灵。",
    }
    outcome = read_web("闪耀大赛登场率最高的精灵", search=_search([wechat]), rank=_rank)
    assert outcome.get("fill") == "bridge"
    assert outcome.get("name") in {"", None}
    assert "海枝枝" not in (outcome.get("text") or "")
    hit = read_web(
        "闪耀大赛登场率最高的精灵",
        search=_search([{
            "title": "出场率",
            "url": "https://wiki.biligame.com/nrc/rate",
            "snippet": "闪耀大赛出场率最高的精灵是霹雳迪迪。",
        }]),
        rank=_rank,
    )
    assert hit.get("fill") == "hit"
    assert hit.get("name") == "霹雳迪迪"


def test_team_cannot_be_a_sprite_column():
    from agents.fact_read import _fact_grounded, _known_column, bridge_followup

    assert _known_column("借用的榜九的毒队的属性") is False
    assert _known_column("毒队的技能和威力") is False
    assert _known_column("霹雳迪迪的属性") is True
    assert _fact_grounded("毒队的属性", "出场率最高的精灵", [{"fact": "出场率最高的精灵", "text": "毒队很强"}]) is False
    assert bridge_followup("榜九的毒队") == "榜九的毒队出场精灵"


def test_tavily_waves_keep_domains_on_the_named_rounds():
    from web_search import tavily_payload, wave_plan

    plan = wave_plan("闪耀大赛出场率最高的精灵")
    assert [item["name"] for item in plan] == ["官网", "维基", "视频", "全网"]
    official = tavily_payload("q", "k", 10, plan[0]["depth"], plan[0]["include_domains"], plan[0]["domains_mode"])
    assert official["include_domains"] == ["rocom.qq.com"]
    assert official["include_domains_mode"] == "restrict"
    assert official["search_depth"] == "advanced"
    assert official["chunks_per_source"] == 3
    assert official["language"] == "zh-cn"
    assert official["include_answer"] is False
    open_web = tavily_payload("q", "k", 10, plan[3]["depth"], plan[3]["include_domains"], plan[3]["domains_mode"])
    assert "include_domains" not in open_web
    assert "include_domains_mode" not in open_web
    assert "wikipedia.org" in open_web["exclude_domains"]


def test_deepseek_query_puts_site_and_language():
    from web_search import deepseek_query, wave_plan

    plan = wave_plan("闪耀大赛出场率最高的精灵")
    official = deepseek_query(plan[0]["query"], plan[0]["include_domains"])
    assert "site:rocom.qq.com" in official
    assert "lang:zh" in official
    assert len(official) <= 128
    wiki = deepseek_query(plan[1]["query"], plan[1]["include_domains"])
    assert "site:wiki.biligame.com" in wiki
    assert "site:wiki.biligame.com/nrc" not in wiki
    open_web = deepseek_query(plan[3]["query"], plan[3]["include_domains"])
    assert "lang:zh" in open_web
    assert "site:" not in open_web


def test_proper_name_in_the_question_must_stay_in_the_sentence():
    assert grade_sentence("霹雳迪迪的种族值", "水灵的种族值合计是300。") == "对不上"
    assert grade_sentence("霹雳迪迪的种族值", "霹雳迪迪的种族值合计是300。") == "对得上"
    assert grade_sentence("闪耀大赛登场率最高的精灵", "闪耀大赛出场率最高的精灵是霹雳迪迪。") == "对得上"


def test_reason_keeps_the_page_sentence_without_a_model():
    from agents.web_read import parse_final_information, reason_in_documents

    assert parse_final_information("**Final Information**\n\n出场率最高的精灵是霹雳迪迪。") == "出场率最高的精灵是霹雳迪迪。"
    assert reason_in_documents("闪耀大赛登场率最高的精灵", "出场率最高的精灵是霹雳迪迪。") == "出场率最高的精灵是霹雳迪迪。"


if __name__ == "__main__":
    test_tiers_put_official_before_wiki_before_video()
    test_outside_pages_are_read_and_official_still_wins()
    test_video_play_count_can_be_read_from_the_page_text()
    test_crag_keeps_a_matching_sentence_and_holds_a_partial_one()
    test_unprovided_counts_and_a_final_number_does_not()
    test_same_tier_follows_the_rerank_score()
    test_grade_labels()
    test_miss_then_second_query_finds_the_sentence()
    test_official_number_wins_and_same_tier_conflict_stops()
    test_scheme_c_scores_a_related_sentence_higher()
    test_rate_page_can_match_one_key_and_a_name()
    test_preferred_sites_keep_related_snippets_without_a_catalog_name()
    test_rate_lineup_chatter_without_a_name_does_not_fill()
    test_rate_does_not_treat_lineup_member_as_champion()
    test_team_cannot_be_a_sprite_column()
    test_tavily_waves_keep_domains_on_the_named_rounds()
    test_deepseek_query_puts_site_and_language()
    test_proper_name_in_the_question_must_stay_in_the_sentence()
    test_reason_keeps_the_page_sentence_without_a_model()
    print("ok")
