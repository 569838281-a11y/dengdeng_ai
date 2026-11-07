"""联网读取的五类能力测评。

网页用写好的页面，不访问外网。重排用锚点重合，站点档、滤句、再检和停圈仍走正式代码。
成文审查原样放过。门口维持程序建议。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agents.speech_review as speech_review
import agents.web_read as web_read
from agents.job_ledger import drop
from agents.supervisor import run_cycle
from agents.thoughts import bind, reset
from agents.web_read import web_anchors

speech_review.review_speech = lambda _question, speech, _evidence=None, ask=None: {
    "pass": True,
    "issues": [],
    "text": speech,
    "repaired": False,
}


def _fast_rank(fact, texts):
    anchors = web_anchors(fact) or [fact]
    return [float(sum(anchor in (text or "") for anchor in anchors)) for text in texts]


web_read.scheme_c = _fast_rank

OUT = ROOT / "data" / "web_cycle_eval.txt"
NAMES = ["水灵", "寂灭骨龙", "音速犬（本来的样子）", "绒光优优", "离心舞者", "贝古斯"]


def _page(title, url, snippet, plays=None):
    row = {"title": title, "url": url, "snippet": snippet}
    if plays is not None:
        row["plays"] = plays
    return row


OFFICIAL = "https://rocom.qq.com/fish"
WIKI = "https://wiki.biligame.com/nrc/fish"
BILI = "https://www.bilibili.com/video/BV1fish"


def _fish_sources():
    return [
        _page("杂站", "https://www.gamersky.com/fish", "利灯鱼的种族值合计是1。"),
        _page("低播放", BILI + "low", "利灯鱼的种族值合计是2。", 200),
        _page("百科", WIKI, "利灯鱼的种族值合计是502。"),
        _page("官网", OFFICIAL, "利灯鱼的种族值合计是300。"),
        _page("高播放", BILI, "利灯鱼的种族值合计是999。", 9000),
    ]


def _run(case, search):
    thoughts = []
    token = bind(lambda kind, text: thoughts.append((kind, text)))
    try:
        cycle = run_cycle(
            case["question"],
            session_id=case["id"],
            judged={"intent": case["intent"], "request": case["question"]},
            web=search,
            lineup=case.get("lineup"),
            save=case.get("save"),
        )
    except Exception as exc:
        cycle = {"error": f"{type(exc).__name__}: {exc}", "order": {"answer": ""}, "ledger": {}}
    finally:
        reset(token)
    ledger = cycle.get("ledger") or {}
    progress = ledger.get("progress") or {}
    return {
        "id": case["id"],
        "title": case["title"],
        "question": case["question"],
        "intent": case["intent"],
        "error": cycle.get("error", ""),
        "answer": (cycle.get("order") or {}).get("answer") or "",
        "thoughts": thoughts,
        "queries": list(progress.get("web_queries") or []),
        "fact_queries": list(progress.get("fact_queries") or []),
        "next": progress.get("next") or "",
        "gap": ledger.get("gap"),
        "guesses": ledger.get("guesses") or [],
        "facts": ledger.get("facts") or [],
        "opened": [item.get("word") for item in (progress.get("opened") or []) if isinstance(item, dict)],
    }


def _checks(row, case):
    answer = row["answer"]
    notes = []
    ok = True
    for needle in case.get("has") or []:
        hit = needle in answer
        notes.append(("回答含有", needle, hit))
        ok = ok and hit
    for needle in case.get("lacks") or []:
        hit = needle not in answer
        notes.append(("回答不含", needle, hit))
        ok = ok and hit
    facts = row["fact_queries"]
    for needle in case.get("facts") or []:
        hit = any(needle in item for item in facts)
        notes.append(("事实", needle, hit))
        ok = ok and hit
    queries = row["queries"]
    expect_n = case.get("web_calls")
    if expect_n is not None:
        hit = len(queries) == expect_n
        notes.append(("上网次数", str(expect_n), hit))
        ok = ok and hit
    for needle in case.get("query_has") or []:
        hit = any(needle in item for item in queries)
        notes.append(("查询含有", needle, hit))
        ok = ok and hit
    if case.get("next"):
        hit = row["next"] == case["next"]
        notes.append(("收口", case["next"], hit))
        ok = ok and hit
    grades = [item.get("grade") for item in row["guesses"]]
    for grade in case.get("grades") or []:
        hit = grade in grades
        notes.append(("猜测", grade, hit))
        ok = ok and hit
    return ok, notes


def _render(rows):
    lines = [
        "灯灯联网读取测评",
        "网页是写好的页面，不访问外网。重排用锚点重合代替现场编码。",
        "站点档、原文锚点、查不到再检一次、矛盾时取高一档、两轮仍没有就停下，都走现在的读取。",
        "成文审查原样放过。门口维持程序建议。",
        f"共 {len(rows)} 题。",
        "",
    ]
    passed = 0
    for index, row in enumerate(rows, 1):
        ok, notes = row["ok"], row["notes"]
        passed += int(ok)
        lines.append("=" * 72)
        lines.append(f"{index}. {row['id']}  {row['title']}  {row['intent']}")
        lines.append(f"问题：{row['question']}")
        if row["error"]:
            lines.append(f"错误：{row['error']}")
        lines.append("")
        lines.append("思考")
        if row["thoughts"]:
            for nth, (kind, text) in enumerate(row["thoughts"], 1):
                lines.append(f"{nth}. [{kind}] {text}")
        else:
            lines.append("（没有）")
        lines.append("")
        lines.append("拆开的事实")
        if row["fact_queries"]:
            for item in row["fact_queries"]:
                lines.append(f"- {item}")
        else:
            lines.append("- （没有）")
        lines.append("网页查询")
        if row["queries"]:
            for item in row["queries"]:
                lines.append(f"- {item}")
        else:
            lines.append("- （没有上网）")
        lines.append(f"调度  {' → '.join(row['opened']) or '无'}  收口 {row['next'] or '无'}")
        gap = row["gap"] if isinstance(row["gap"], dict) else None
        if gap:
            lines.append(f"缺口 {gap.get('kind') or ''} {gap.get('label') or ''}".rstrip())
        if row["guesses"]:
            lines.append("猜测")
            for item in row["guesses"]:
                lines.append(f"- {item.get('grade') or ''}  {item.get('text') or ''}")
        lines.append("")
        lines.append("回答")
        lines.append(row["answer"] or "（没有回答）")
        lines.append("")
        lines.append("判定 " + ("通过" if ok else "未通过"))
        for name, detail, hit in notes:
            lines.append(f"- {name} {detail}：{'是' if hit else '否'}")
        lines.append("")
    lines.append("=" * 72)
    lines.append(f"合计：{passed}/{len(rows)} 题通过。")
    return "\n".join(lines)


def main():
    calls = {}

    def watch(case_id, rows_for):
        def search(query, limit=10):
            calls.setdefault(case_id, []).append(query)
            assert limit == 10
            return {"results": rows_for(query)}

        return search

    lineup = lambda *_args: {"ok": True, "names": list(NAMES), "answer": "", "hard": []}
    save = lambda *_args: ("灯灯记下了这一套出场。", True, "、".join(NAMES))

    cases = [
        {
            "id": "split-type",
            "title": "复杂问题拆成克制和抵抗",
            "question": "普通系技能打幻系，伤害倍率按多少算？",
            "intent": "search",
            "facts": ["普通系的克制", "幻系的抵抗"],
            "has": ["按 1", "克制：无", "抵抗：武、幻"],
            "web_calls": 0,
            "next": "stop",
            "rows": lambda _query: [],
        },
        {
            "id": "split-wave",
            "title": "首领化和技能能耗拆开查",
            "question": "水灵首领化之后，浪潮这个技能的能耗是多少？",
            "intent": "search",
            "facts": ["水灵首领化", "浪潮的能耗"],
            "has": ["圣水守护", "能耗-2"],
            "web_calls": 0,
            "next": "stop",
            "rows": lambda _query: [],
        },
        {
            "id": "split-names",
            "title": "两个专名各自对行",
            "question": "浸润和湿润印记有什么差别？",
            "intent": "search",
            "facts": ["浸润", "湿润印记"],
            "has": ["浸润", "湿润印记", "能耗"],
            "web_calls": 0,
            "next": "stop",
            "rows": lambda _query: [],
        },
        {
            "id": "split-switch",
            "title": "更换是否使用技能",
            "question": "战斗里更换精灵，算不算使用了一次技能？",
            "intent": "search",
            "facts": ["更换是否使用技能"],
            "has": ["更换等同于使用技能"],
            "lacks": ["不算使用技能"],
            "web_calls": 0,
            "next": "stop",
            "rows": lambda _query: [],
        },
        {
            "id": "split-then-web",
            "title": "一条在名录、一条要上网",
            "question": "利灯鱼的种族值和浪潮这个技能的能耗是多少？",
            "intent": "search",
            "facts": ["浪潮的能耗", "利灯鱼的种族值"],
            "has": ["能耗-2", "300"],
            "lacks": ["502", "999"],
            "query_has": ["利灯鱼的种族值"],
            "web_calls": 1,
            "next": "stop",
            "rows": lambda query: _fish_sources() if "利灯鱼" in query else [],
        },
        {
            "id": "pick-official",
            "title": "官网优先于百科和视频",
            "question": "利灯鱼的种族值是多少？",
            "intent": "search",
            "facts": ["利灯鱼的种族值"],
            "has": ["300"],
            "lacks": ["502", "999", "合计是1", "合计是2"],
            "grades": ["矛盾"],
            "web_calls": 1,
            "next": "stop",
            "rows": lambda _query: _fish_sources(),
        },
        {
            "id": "use-video-when-higher-empty",
            "title": "更高档没有时用达到播放量的视频",
            "question": "利灯鱼的种族值是多少？",
            "intent": "search",
            "has": ["300"],
            "lacks": ["合计是2"],
            "web_calls": 1,
            "next": "stop",
            "rows": lambda _query: [
                _page("低播放", BILI + "low", "利灯鱼的种族值合计是2。", 200),
                _page("高播放", BILI, "利灯鱼的种族值合计是300。", 8000),
            ],
        },
        {
            "id": "retry-hits",
            "title": "第一次没对上就换查询再检",
            "question": "利灯鱼的种族值是多少？",
            "intent": "search",
            "has": ["300"],
            "lacks": ["五百多个"],
            "web_calls": 2,
            "query_has": ["利灯鱼的种族值", "利灯鱼 种族值"],
            "next": "stop",
            "rows": lambda query: (
                [_page("总表", "https://wiki.biligame.com/nrc/all", "技能一共有五百多个分类。")]
                if "的种族值" in query
                else [_page("官网", OFFICIAL, "利灯鱼的种族值合计是300。")]
            ),
        },
        {
            "id": "retry-then-ask",
            "title": "两轮都没有有效句子就停下追问",
            "question": "利灯鱼的种族值是多少？",
            "intent": "search",
            "has": ["利灯鱼的种族值"],
            "lacks": ["300", "502", "双灯鱼"],
            "web_calls": 2,
            "next": "need_ask",
            "rows": lambda _query: [
                _page("总表", "https://wiki.biligame.com/nrc/all", "技能一共有五百多个分类。"),
                _page("站外", "https://www.gamersky.com/fish", "利灯鱼的种族值合计是300。"),
            ],
        },
        {
            "id": "same-tier-clash",
            "title": "同一档两个数字不选边",
            "question": "利灯鱼的种族值是多少？",
            "intent": "search",
            "has": ["说法不一致"],
            "lacks": ["合计是300", "合计是400"],
            "grades": ["矛盾"],
            "web_calls": 1,
            "next": "need_ask",
            "rows": lambda _query: [
                _page("甲", "https://wiki.biligame.com/nrc/a", "利灯鱼的种族值合计是300。"),
                _page("乙", "https://wiki.biligame.com/nrc/b", "利灯鱼的种族值合计是400。"),
            ],
        },
        {
            "id": "catalog-wins",
            "title": "名录里的种族值不被网页换掉",
            "question": "水灵的种族值是多少？",
            "intent": "search",
            "facts": ["水灵的种族值"],
            "has": ["125"],
            "lacks": ["合计是1"],
            "web_calls": 0,
            "next": "stop",
            "rows": lambda _query: [_page("假页", OFFICIAL, "水灵的种族值合计是1。")],
        },
        {
            "id": "star-unprovided",
            "title": "写着未提供就不再上网编数字",
            "question": "星陨造成的额外伤害具体是多少？",
            "intent": "search",
            "facts": ["星陨额外伤害"],
            "has": ["未提供"],
            "lacks": ["999"],
            "web_calls": 0,
            "next": "stop",
            "rows": lambda _query: [_page("假页", OFFICIAL, "星陨额外伤害是999。")],
        },
        {
            "id": "formula-stops",
            "title": "算不出的伤害数字两轮后停下",
            "question": "请按伤害公式算出普通系打幻系这一下的最终伤害数字。",
            "intent": "search",
            "facts": ["伤害公式", "这一下的最终伤害数字"],
            "has": ["伤害量", "还缺技能威力"],
            "lacks": ["999"],
            "web_calls": 2,
            "next": "need_ask",
            "rows": lambda _query: [_page("假页", OFFICIAL, "这一下的最终伤害数字是999。")],
        },
        {
            "id": "hot-stops",
            "title": "热门两轮都空就停下，不再继续查",
            "question": "以火系为主组一套",
            "intent": "lineup",
            "has": ["热门"],
            "web_calls": 2,
            "next": "need_ask",
            "lineup": lineup,
            "save": save,
            "rows": lambda _query: [],
        },
    ]
    rows = []
    for case in cases:
        print(f"已开始 {case['id']}", flush=True)
        row = _run(case, watch(case["id"], case["rows"]))
        ok, notes = _checks(row, case)
        row["ok"] = ok
        row["notes"] = notes
        row["title"] = case["title"]
        rows.append(row)
        print(f"已跑完 {case['id']}", flush=True)
    follow_calls = []

    def follow_search(query, limit=10):
        follow_calls.append(query)
        return {"results": []}

    print("已开始 retry-then-ask 的下一轮", flush=True)
    follow = _run(
        {
            "id": "retry-then-ask",
            "title": "追问之后玩家仍不知道，不再检索",
            "question": "不知道",
            "intent": "search",
        },
        follow_search,
    )
    follow["id"] = "stop-followup"
    follow["queries"] = list(follow_calls)
    ok = follow["next"] == "need_ask" and follow_calls == [] and "含糊" in follow["answer"]
    follow["ok"] = ok
    follow["notes"] = [
        ("收口", "need_ask", follow["next"] == "need_ask"),
        ("上网次数", "0", follow_calls == []),
        ("回答含有", "含糊", "含糊" in follow["answer"]),
    ]
    rows.append(follow)
    drop("retry-then-ask")
    drop("stop-followup")
    for case in cases:
        drop(case["id"])
    text = _render(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
