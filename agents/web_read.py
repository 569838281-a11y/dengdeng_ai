"""探查员的一条读取：分档、BGE-M3 三项分、再综合多页说法。

一条事实是一个子问题。网页都读。优先站是洛克王国世界官网、洛克王国世界 Wiki、
B 站（含播放量不足的）。全网与其它站点排在后面。
优先站上只要和问题沾边，就不整页丢掉；有矛盾时采信档位更高的优先站，
无矛盾时把各页说法并成缺口信息交给后续 agent。
出场率类问法仍尽量抽出名录精灵名；抽不出名字时，优先站的相关摘录也会留下。
"""
import inspect
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_POOL = 20
_SEARCH_LIMIT = 10
_SHORT_PAGE = 800
_PLAY_MIN = 1000
_PREFERRED_TIER = 2  # 0 官网、1 维基、2/3 B 站都算优先站
_OFFICIAL = "rocom.qq.com"
_WIKI_HOST = "wiki.biligame.com"
_VIDEO_HOSTS = ("bilibili.com", "b23.tv")
_DROP_HOSTS = (
    "youtube.com", "youtu.be", "4399.com", "7k7k.com", "51wan.com",
    "wikipedia.org", "rebang.today", "tophub.today", "wandoujia.com",
)
_DROP_WORDS = ("宝可梦", "神奇宝贝", "口袋妖怪", "52poke", "bulbapedia", "pokemon", "pokémon", "阴阳师")
_PLAY = re.compile(
    r"(?:播放量|播放)\D{0,6}(\d+(?:\.\d+)?)(万|亿)?"
    r"|(\d+(?:\.\d+)?)(万|亿)?\s*播放"
    r"|\"view\"\s*:\s*(\d+)",
    re.I,
)
_RERANKER = None


def read_web(fact: str, search=None, open_page=None, rank=None, video_text=None) -> dict:
    """按一条事实读网页。返回 covered、ambiguous 和拼好的 text。"""
    label = (fact or "").strip()
    empty = {
        "reason": "empty",
        "fact": label,
        "covered": [],
        "ambiguous": [],
        "conflicts": [],
        "unsettled": False,
        "queries": [],
        "text": "",
        "detail": "没有查到网页",
    }
    if not label:
        return empty
    live = search is None
    search = search or _live_search
    if open_page is None and live:
        from web_search import read_page
        open_page = read_page
    query = label if "洛克王国" in label else f"洛克王国世界 {label}".strip()
    if live:
        return _read_live(label, query, open_page, rank, video_text, empty)
    try:
        payload = _call_search(search, query, _SEARCH_LIMIT)
    except Exception as exc:
        logger.warning("联网未完成：%s", type(exc).__name__)
        empty["reason"] = "error"
        empty["detail"] = type(exc).__name__
        return empty
    if isinstance(payload, dict) and payload.get("reason") in {"no_key", "off"}:
        empty["reason"] = payload.get("reason")
        empty["detail"] = "未配置密钥" if payload.get("reason") == "no_key" else "未开启联网"
        return empty
    queries = [query]
    found = _collect(label, _items(payload), open_page, rank, video_text=video_text)
    settled = _decide(label, found)
    if not settled["text"] and not settled["unsettled"]:
        alt = _next_query(label, query)
        if alt:
            queries.append(alt)
            try:
                again = _call_search(search, alt, _SEARCH_LIMIT)
            except Exception as exc:
                logger.warning("联网未完成：%s", type(exc).__name__)
                again = {}
            found = _collect(label, _items(again), open_page, rank, found["ambiguous"], video_text)
            settled = _decide(label, found)
    settled = _reason_agreed(label, settled)
    return _finish(label, found, settled, queries)


def _preferred(item: dict) -> bool:
    return int(item.get("tier") or 99) <= _PREFERRED_TIER


def _collect(fact: str, items: list, open_page, rank, prior_ambiguous: list = None, video_text=None) -> dict:
    grouped = {tier: [] for tier in range(6)}
    for page in _pages(items, open_page, video_text):
        grouped[page["tier"]].extend(_strips(fact, page))
    covered = []
    soft = []
    ambiguous = list(prior_ambiguous or [])
    for tier in range(6):
        matched = [item for item in grouped[tier] if item["grade"] == "对得上"]
        vague = [item for item in grouped[tier] if item["grade"] == "含糊"]
        covered.extend(_rank_tier(fact, matched, rank))
        ranked_vague = _rank_tier(fact, vague, rank)
        # 优先站含糊单独留下，硬结论缺席时再并成缺口；有硬结论时不掺进去。
        if tier <= _PREFERRED_TIER:
            soft.extend(ranked_vague)
        ambiguous.extend(ranked_vague)
    return {"covered": covered, "soft": soft, "ambiguous": ambiguous[:4]}


def _finish(fact: str, found: dict, settled: dict, queries: list) -> dict:
    text = settled["text"]
    detail = "没有查到网页"
    fill = settled.get("fill") or ""
    bridge = settled.get("bridge") or ""
    if fill == "bridge" and bridge:
        detail = f"读到阵容桥：{bridge}，再查成员"
    elif text:
        titles = [item["title"][:18] for item in settled["covered"][:3] if item.get("title")]
        detail = "读了 " + "、".join(titles) if titles else "读了优先站上的相关摘录"
    elif settled["unsettled"]:
        detail = "这几页说法不一致"
    elif found["ambiguous"]:
        detail = "网页没对上这一条"
    reason = "ok" if text or found["ambiguous"] or settled["unsettled"] or fill == "bridge" else "empty"
    from agents.fact_read import _rate_fact

    final = ""
    if _rate_fact(fact):
        if fill == "bridge":
            final = f"bridge:{bridge}" if bridge else "No helpful information found."
        else:
            final = text or "No helpful information found."
    return {
        "reason": reason,
        "fact": fact,
        "covered": settled["covered"],
        "ambiguous": found["ambiguous"],
        "conflicts": settled["conflicts"],
        "unsettled": settled["unsettled"],
        "text": text,
        "name": settled.get("name") or "",
        "bridge": bridge,
        "fill": fill,
        "queries": queries,
        "detail": detail,
        "final_information": final,
    }


def _pick_preferred(items: list) -> dict:
    """同一档说法打架时，留下分数更高的那一条，其余进冲突。"""
    ordered = sorted(
        items,
        key=lambda item: (
            int(item.get("tier") or 99),
            -float(item.get("score") or 0),
            -(1 if _preferred(item) else 0),
            item.get("text") or "",
        ),
    )
    chosen = ordered[0]
    conflicts = [item for item in items if item is not chosen]
    return {"chosen": chosen, "conflicts": conflicts}


def _settle(covered: list) -> dict:
    """高一档的说法留下。同一档数字打架时，采信优先站里分数更高的一条。"""
    if not covered:
        return {"covered": [], "conflicts": [], "unsettled": False, "text": ""}
    numbered = [item for item in covered if _signature(item.get("text") or "")]
    if not numbered:
        preferred = [item for item in covered if _preferred(item)] or list(covered)
        return {"covered": preferred, "conflicts": [], "unsettled": False, "text": _join(preferred)}
    best = min(item["tier"] for item in numbered)
    winners = [item for item in numbered if item["tier"] == best]
    marks = {_signature(item.get("text") or "") for item in winners}
    if len(marks) > 1:
        picked = _pick_preferred(winners)
        chosen = picked["chosen"]
        mark = _signature(chosen.get("text") or "")
        kept = [chosen]
        conflicts = list(picked["conflicts"])
        for item in covered:
            sign = _signature(item.get("text") or "")
            if item is chosen:
                continue
            if sign and sign != mark and item not in conflicts:
                conflicts.append(item)
        return {
            "covered": kept,
            "conflicts": conflicts,
            "unsettled": False,
            "text": _join(kept),
        }
    mark = next(iter(marks))
    kept = []
    conflicts = []
    for item in covered:
        sign = _signature(item.get("text") or "")
        if item["tier"] == best and sign == mark:
            kept.append(item)
        elif sign and sign != mark:
            conflicts.append(item)
    return {"covered": kept, "conflicts": conflicts, "unsettled": False, "text": _join(kept)}


def _signature(text: str):
    if "未提供" in (text or ""):
        return ("未提供",)
    nums = tuple(re.findall(r"\d+", text or ""))
    return nums or None


def _next_query(fact: str, previous: str) -> str:
    anchors = [item for item in web_anchors(fact) if item and item != fact]
    if len(anchors) >= 2:
        alt = "洛克王国世界 " + " ".join(anchors)
    else:
        alt = f"洛克王国世界 {_bare(fact)} 官网"
    alt = re.sub(r"\s+", " ", alt).strip()
    if not alt or alt == (previous or "").strip():
        return ""
    return alt


def web_anchors(fact: str) -> list:
    """这条事实在网页句子里要同时出现的词。最终伤害数字没有锚点，不能被网页句写成已答。"""
    text = _bare(fact)
    if not text or text == "这一下的最终伤害数字":
        return []
    from agents.fact_read import _anchors

    found = [item for item in _anchors(text) if item]
    if "的" in text:
        head = text.split("的", 1)[0].strip()
        if 1 < len(head) <= 12 and head not in found:
            found.insert(0, head)
    if not found:
        found = [text]
    seen = []
    for item in found:
        if item and item not in seen:
            seen.append(item)
    return seen


def _contains(anchor: str, text: str) -> bool:
    body = text or ""
    token = anchor or ""
    if not token:
        return False
    if token in body:
        return True
    if "登场率" in token and token.replace("登场率", "出场率") in body:
        return True
    if "出场率" in token and token.replace("出场率", "登场率") in body:
        return True
    return False


_PROPER_NAMES = None


def _catalog_proper() -> list:
    global _PROPER_NAMES
    if _PROPER_NAMES is not None:
        return _PROPER_NAMES
    from pokemon_kb import load_pokemon, skill_catalog

    names = [str(item.get("name") or "") for item in load_pokemon()]
    names.extend(str(name) for name in skill_catalog())
    found = []
    for name in names:
        if len(name) >= 2 and name not in found:
            found.append(name)
    _PROPER_NAMES = sorted(found, key=len, reverse=True)
    return _PROPER_NAMES


def _proper_names(text: str) -> list:
    """问句里按全名出现的精灵或技能。先取长名，避免短名从长名里再截一段。"""
    blob = text or ""
    found = []
    for name in _catalog_proper():
        if name and name in blob:
            found.append(name)
            blob = blob.replace(name, " ")
    return found


def _proper_holds(fact: str, sentence: str, title: str) -> bool:
    blob = f"{title or ''} {sentence or ''}"
    return all(name in blob for name in _proper_names(fact))


def grade_sentence(fact: str, sentence: str, title: str = "") -> str:
    """对得上要句子里同时有这些锚点。标题对上、句子只对上一部分，算含糊。

    出场率、登场率、使用率只要命中其中一个关键信息，并且同一处写着名录里的精灵，也算对得上。
    问句里的名录全名必须原样出现在句子或标题里。
    """
    text = (sentence or "").strip()
    anchors = web_anchors(fact)
    if not text or not anchors:
        return "对不上"
    if not _proper_holds(fact, text, title or ""):
        return "对不上"
    in_sentence = [item for item in anchors if _contains(item, text)]
    in_title = [item for item in anchors if _contains(item, title or "")]
    if len(in_sentence) == len(anchors):
        return "对得上"
    if _rate_supports(fact, text, title or ""):
        return "对得上"
    # 桥跳「某队出场精灵」：句子里有名录精灵即可，便于从阵容文收回成员名。
    if ("出场精灵" in (fact or "") or str(fact).endswith("成员")) and _catalog_names(f"{text} {title or ''}"):
        return "对得上"
    if in_sentence or in_title:
        return "含糊"
    return "对不上"


def _distinctive(fact: str) -> list:
    found = []
    for item in web_anchors(fact):
        if any(word in item for word in ("出场率", "登场率", "使用率", "闪耀大赛")) and item not in found:
            found.append(item)
    return found


def _rate_supports(fact: str, text: str, title: str) -> bool:
    from agents.fact_read import _rate_fact

    if not _rate_fact(fact):
        return False
    blob = f"{text} {title}".strip()
    if not any(_contains(item, blob) for item in _distinctive(fact)):
        return False
    # 必须写明最高/榜首是谁；阵容文里捎带的名录名不算对得上。
    return bool(_rate_champion_name(blob))


def _catalog_names(text: str) -> list:
    from pokemon_kb import _mentioned_names, load_pokemon

    return _mentioned_names(text or "", load_pokemon())


def _lineup_chatter(text: str) -> bool:
    body = text or ""
    return any(word in body for word in ("阵容", "前十", "抄作业", "搭配思路", "全国前十", "分别在用"))


def _looks_like_sprite_name(token: str) -> bool:
    """像不像一只精灵名（还不是「真有」）。假描述串在这里拦掉。"""
    body = (token or "").strip()
    if not (2 <= len(body) <= 6):
        return False
    if any(
        word in body
        for word in (
            "克制", "稳稳", "最高", "出场", "登场", "使用率", "阵容", "前十",
            "技能", "威力", "伤害", "未上榜", "榜首", "第一",
        )
    ):
        return False
    return True


def _ground_sprite_name(token: str, *, allow_unknown: bool = False) -> str:
    """出场率 Hit 的名字闸。

    1) 名录整段命中 → 可靠 Hit（本地核查「有这只」）
    2) 显式「是 X」且像精灵名 → 暂认，交给后续 Wiki/名录读卡；读不到再 ask
    3) 标题体「第一XXXX」无「是」→ 只认名录，禁止「第一稳稳克制凡鹰」
    """
    from agents.fact_read import _team_like

    body = (token or "").strip()
    if not body or _team_like(body):
        return ""
    if any(
        word in body
        for word in (
            "克制", "稳稳", "最高", "出场", "登场", "使用率", "阵容", "前十",
            "技能", "威力", "伤害", "未上榜",
        )
    ):
        return ""
    for stop in ("的", "在", "出", "登", "最", "未", "，", ",", "。", "！", "!", "（", "(", "：", ":"):
        if stop in body:
            body = body.split(stop, 1)[0].strip()
    if not body or _team_like(body):
        return ""
    names = _catalog_names(body)
    for name in sorted(names, key=len, reverse=True):
        if body == name:
            return name
    if allow_unknown and _looks_like_sprite_name(body):
        return body
    return ""


def _rate_champion_name(text: str) -> str:
    """写明「最高/榜首/第一是谁」才可能 Hit；描述性假名与无「是」的标题乱切一律空。"""
    body = text or ""
    explicit = (
        r"(?:出场率|登场率|使用率)最高的?(?:精灵)?是([\u4e00-\u9fff]{2,12})",
        r"最高的(?:精灵)?是([\u4e00-\u9fff]{2,12})",
        r"榜首[的是：:\s]*([\u4e00-\u9fff]{2,12})",
        r"第一[的是：:\s]+([\u4e00-\u9fff]{2,12})",
    )
    for pattern in explicit:
        matched = re.search(pattern, body)
        if not matched:
            continue
        # 出场率 Hit 一律名录核对；名录外（含微博昵称）不能假 Hit。
        name = _ground_sprite_name(matched.group(1), allow_unknown=False)
        if name:
            return name
    # 标题「第一霹雳迪迪」：无系词时只认名录，避免「第一稳稳克制凡鹰」
    matched = re.search(r"第一([\u4e00-\u9fff]{2,12})", body)
    if matched:
        return _ground_sprite_name(matched.group(1), allow_unknown=False)
    return ""


def _decide(fact: str, found: dict) -> dict:
    from agents.evidence_slots import CORRECT, crag_rate_champion
    from agents.fact_read import _bridge_entity, _rate_fact

    if not _rate_fact(fact):
        settled = _settle(found["covered"])
        if settled["text"]:
            return settled
        return _compose_gap(found)
    agreed = _agree_rate(found["covered"])
    if agreed is not None:
        if agreed.get("unsettled"):
            return agreed
        text = agreed.get("text") or ""
        name = agreed.get("name") or _rate_champion_name(text)
        judged = crag_rate_champion(text, fill="hit" if name else "", name=name or "")
        if judged.get("status") == CORRECT and judged.get("champion"):
            agreed = dict(agreed)
            agreed["name"] = judged["champion"]
            agreed["fill"] = "hit"
            agreed["crag"] = judged
            if fact not in text:
                agreed["text"] = f"{fact}是{judged['champion']}。"
            return agreed
    soft = _compose_gap(found)
    blob = soft.get("text") or ""
    titles = " ".join(item.get("title") or "" for item in (soft.get("covered") or []))
    pool = f"{blob} {titles}".strip()
    judged = crag_rate_champion(pool)
    # Correct：冠军句 + 名录实体 → Hit（Self-RAG support）
    if judged.get("status") == CORRECT and judged.get("champion"):
        return {
            "covered": soft.get("covered") or [],
            "conflicts": [],
            "unsettled": False,
            "text": f"{fact}是{judged['champion']}。",
            "name": judged["champion"],
            "fill": "hit",
            "bridge": "",
            "crag": judged,
        }
    # Ambiguous：阵容/前十 → Bridge，只填成员槽，不写冠军
    bridge = _bridge_entity(pool)
    names = _catalog_names(pool)
    if bridge or _lineup_chatter(pool) or len(names) >= 2 or judged.get("action") == "bridge_or_ask":
        return {
            "covered": soft.get("covered") or [],
            "conflicts": [],
            "unsettled": False,
            "text": "",
            "name": "",
            "fill": "bridge",
            "bridge": bridge or "前十阵容",
            "crag": judged,
            "members": list(judged.get("members") or names),
        }
    return {
        "covered": [],
        "conflicts": [],
        "unsettled": False,
        "text": "",
        "name": "",
        "fill": "miss",
        "bridge": "",
        "crag": judged,
    }


def _compose_gap(found: dict) -> dict:
    """没有唯一硬结论时，把优先站相关摘录并成缺口信息。"""
    rows = []
    for item in list(found.get("soft") or []) + list(found.get("covered") or []) + list(found.get("ambiguous") or []):
        if item not in rows:
            rows.append(item)
    preferred = [item for item in rows if _preferred(item)]
    kept = preferred or rows
    kept = sorted(
        kept,
        key=lambda item: (int(item.get("tier") or 99), -float(item.get("score") or 0), item.get("text") or ""),
    )[:6]
    if not kept:
        return {"covered": [], "conflicts": [], "unsettled": False, "text": "", "name": ""}
    return {
        "covered": kept,
        "conflicts": [],
        "unsettled": False,
        "text": _join(kept),
        "name": "",
    }


def _agree_rate(covered: list) -> dict:
    """抽出精灵名；高一档压过低一档。同一档两个名字时，采信优先站分数更高的那个。"""
    groups = {}
    seasons = []
    for item in covered or []:
        season = _season(item.get("text") or "")
        if season is not None:
            seasons.append(season)
        for name in _names_of(item):
            groups.setdefault(name, []).append(item)
    if not groups:
        return None
    if seasons:
        latest = max(seasons)
        narrowed = {}
        for name, items in groups.items():
            kept = [item for item in items if _season(item.get("text") or "") in {None, latest}]
            if kept:
                narrowed[name] = kept
        groups = narrowed
    eligible = {}
    for name, items in groups.items():
        tier = min(item["tier"] for item in items)
        urls = {item.get("url") or "" for item in items if item.get("url")}
        # 优先站（官网/维基/B 站）一页即可；其余站点仍要两页互证。
        if tier <= _PREFERRED_TIER or len(urls) >= 2:
            eligible[name] = items
    if not eligible:
        return {"covered": [], "conflicts": [], "unsettled": False, "text": "", "name": ""}
    best = min(min(item["tier"] for item in items) for items in eligible.values())
    winners = {
        name: items
        for name, items in eligible.items()
        if min(item["tier"] for item in items) == best
    }
    if len(winners) > 1:
        ranked = []
        for name, items in winners.items():
            top = sorted(
                items,
                key=lambda item: (-float(item.get("score") or 0), item.get("text") or ""),
            )[0]
            ranked.append((name, items, top))
        ranked.sort(
            key=lambda row: (
                int(row[2].get("tier") or 99),
                -float(row[2].get("score") or 0),
                -(1 if _preferred(row[2]) else 0),
                row[0],
            )
        )
        name, items, top = ranked[0]
        conflicts = []
        for other, other_items, _top in ranked[1:]:
            conflicts.extend(other_items)
        for other, other_items in groups.items():
            if other != name:
                for item in other_items:
                    if item not in conflicts and item not in items:
                        conflicts.append(item)
        text = _quote(top, name)
        return {
            "covered": [top],
            "conflicts": conflicts,
            "unsettled": False,
            "text": text,
            "name": name,
        }
    name, items = next(iter(winners.items()))
    kept = [item for item in items if item["tier"] == best]
    kept.sort(key=lambda item: (-float(item.get("score") or 0), item.get("text") or ""))
    chosen = kept[:1]
    conflicts = []
    for other, other_items in groups.items():
        if other != name:
            conflicts.extend(other_items)
    text = _quote(chosen[0], name) if chosen else ""
    return {"covered": chosen, "conflicts": conflicts, "unsettled": False, "text": text, "name": name}


def _names_of(item: dict) -> list:
    blob = f"{item.get('text') or ''} {item.get('title') or ''}"
    names = _catalog_names(blob)
    if names:
        return names
    if item.get("soft"):
        return []
    stated = _stated_name(item.get("text") or "")
    return [stated] if stated else []


def _stated_name(text: str) -> str:
    matched = re.search(r"是([\u4e00-\u9fff]{2,8})", text or "")
    if not matched:
        return ""
    token = matched.group(1)
    for stop in ("的", "在", "出", "登", "最"):
        if stop in token:
            token = token.split(stop, 1)[0]
    token = token.strip()
    if len(token) < 2:
        return ""
    names = _catalog_names(token)
    return names[0] if names else token


def _quote(item: dict, name: str) -> str:
    text = (item.get("text") or "").strip()
    title = (item.get("title") or "").strip()
    if name and name not in text and name in title:
        return f"{title}。{text}".strip("。")
    return text


def _season(text: str):
    matched = re.search(r"第\s*(\d+)\s*赛季|S(\d+)", text or "", re.I)
    if not matched:
        return None
    return int(matched.group(1) or matched.group(2))


def _reason_agreed(fact: str, settled: dict) -> dict:
    text = settled.get("text") or ""
    name = settled.get("name") or ""
    if not text or not name:
        return settled
    refined = reason_in_documents(fact, text)
    if refined and name in refined and "No helpful information found" not in refined:
        copied = dict(settled)
        copied["text"] = refined
        return copied
    return settled


def get_webpage_to_reasonchain_instruction(prev_reasoning: str, search_query: str, document: str) -> str:
    """Search-o1 的 Reason-in-Documents 提示。输出以 Final Information 开头。"""
    return f"""**Task Instruction:**

You are tasked with reading and analyzing web pages based on the following inputs: **Previous Reasoning Steps**, **Current Search Query**, and **Searched Web Pages**. Your objective is to extract relevant and helpful information for **Current Search Query** from the **Searched Web Pages** and seamlessly integrate this information into the **Previous Reasoning Steps** to continue reasoning for the original question.

**Guidelines:**

1. **Analyze the Searched Web Pages:**
- Carefully review the content of each searched web page.
- Identify factual information that is relevant to the **Current Search Query** and can aid in the reasoning process for the original question.

2. **Extract Relevant Information:**
- Select the information from the Searched Web Pages that directly contributes to advancing the **Previous Reasoning Steps**.
- Ensure that the extracted information is accurate and relevant.

3. **Output Format:**
- **If the web pages provide helpful information for current search query:** Present the information beginning with `**Final Information**` as shown below.
**Final Information**

[Helpful information]

- **If the web pages do not provide any helpful information for current search query:** Output the following text.

**Final Information**

No helpful information found.

**Inputs:**
- **Previous Reasoning Steps:**
{prev_reasoning}

- **Current Search Query:**
{search_query}

- **Searched Web Pages:**
{document}

Now you should analyze each web page and find helpful information based on the current search query "{search_query}" and previous reasoning steps.
"""


def parse_final_information(text: str) -> str:
    marker = "**Final Information**"
    if marker not in (text or ""):
        return ""
    return (text or "").split(marker, 1)[1].strip()


def reason_in_documents(query: str, document: str, prev: str = "", ask=None) -> str:
    """有模型时按 Search-o1 读页面并抽出 Final Information。没有模型时保留已经对上的原文。"""
    body = (document or "").strip()
    if not body:
        return "No helpful information found."
    caller = ask
    if caller is None:
        from agents.react_stream import streaming

        if not streaming():
            return body
        try:
            from llm_provider import get_team_invoke

            caller = get_team_invoke(12)
        except Exception:
            return body
    try:
        raw = caller(get_webpage_to_reasonchain_instruction(prev, query, body))
    except Exception as exc:
        logger.warning("网页提炼未完成：%s", type(exc).__name__)
        return body
    text = str(getattr(raw, "content", None) or raw or "")
    info = parse_final_information(text)
    if not info:
        return body
    return info


def scheme_c(fact: str, texts: list) -> list:
    """稠密、稀疏、ColBERT 三项分。模型不可用时这些句子保持原顺序。"""
    if not texts:
        return []
    try:
        return _scheme_c(fact, list(texts))
    except Exception as exc:
        logger.warning("网页重排未完成：%s", type(exc).__name__)
        return [0.0 for _item in texts]


def _scheme_c(fact: str, texts: list) -> list:
    reranker = _reranker()
    scores = reranker.hybrid_all(fact, list(texts))
    return [None if item is None else float(item) for item in scores]


def _reranker():
    global _RERANKER
    if _RERANKER is None:
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "scripts" / "ab_rerank.py"
        spec = importlib.util.spec_from_file_location("ab_rerank_web", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RERANKER = module.MultiVectorReranker()
    return _RERANKER


def _rank_tier(fact: str, strips: list, rank) -> list:
    if not strips:
        return []
    scorer = rank or scheme_c
    scores = list(scorer(fact, [item["text"] for item in strips]))
    kept = []
    for item, score in zip(strips, scores):
        if score is None:
            continue
        copied = dict(item)
        copied["score"] = float(score)
        kept.append(copied)
    kept.sort(key=lambda item: (-item["score"], -_stamp(item.get("published_date")), item["text"]))
    return kept


def _stamp(value: str) -> int:
    from email.utils import parsedate_to_datetime

    text = (value or "").strip()
    if not text:
        return 0
    try:
        return int(parsedate_to_datetime(text).timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


def _loose_hit(fact: str, text: str, title: str = "") -> bool:
    """优先站放宽：问句里的关键片段出现在标题或正文即可留下。"""
    blob = f"{title or ''} {text or ''}"
    if not blob.strip():
        return False
    for anchor in web_anchors(fact):
        if _contains(anchor, blob):
            return True
    for part in re.findall(r"[\u4e00-\u9fff]{2,}|[Ss]\d+", fact or ""):
        if len(part) < 2:
            continue
        if part.lower() in blob.lower():
            return True
    return False


def _strips(fact: str, page: dict) -> list:
    title = page.get("title") or ""
    body = page.get("text") or ""
    anchors = web_anchors(fact)
    title_hit = bool(anchors) and all(item in title for item in anchors)
    pieces = [body.strip()] if title_hit and body.strip() and len(body) <= _SHORT_PAGE else _sentences(body)
    if not pieces and title_hit:
        pieces = [title]
    from agents.fact_read import _rate_fact

    if _rate_fact(fact):
        pieces = _windows(pieces)
    preferred = int(page.get("tier") or 99) <= _PREFERRED_TIER
    found = []
    for piece in pieces:
        shown_title = title if (_rate_fact(fact) or title_hit or preferred) else ""
        grade = grade_sentence(fact, piece, shown_title)
        if grade == "对不上" and preferred and _loose_hit(fact, piece, title):
            grade = "含糊"
        if grade == "对不上":
            continue
        all_in = bool(anchors) and all(_contains(item, piece) for item in anchors)
        found.append({
            "text": piece,
            "title": title,
            "url": page.get("url") or "",
            "tier": page["tier"],
            "plays": page.get("plays"),
            "grade": grade,
            "soft": grade != "对得上" or not all_in,
            "score": 0.0,
            "published_date": page.get("published_date") or "",
        })
    return found


def _windows(pieces: list) -> list:
    found = []
    for piece in pieces:
        if piece and piece not in found:
            found.append(piece)
    for index in range(len(pieces) - 1):
        joined = f"{pieces[index]}。{pieces[index + 1]}"
        if joined not in found:
            found.append(joined)
    return found


def _pages(items: list, open_page, video_text=None) -> list:
    found = []
    seen = set()
    heard = 0
    for item in items:
        url = str(item.get("url") or item.get("link") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url or url in seen:
            continue
        snippet = str(item.get("snippet") or "")
        text = str(item.get("text") or item.get("extract") or snippet).strip()
        plays = _plays(item, f"{title} {text}")
        tier = _tier(url)
        if open_page is not None and (tier <= 1 or len(text) < 40 or (tier == 2 and plays is None)):
            opened = _open_text(open_page, url, 6000 if tier <= 1 else 1600)
            if opened:
                text = opened
                if plays is None:
                    plays = _plays(item, f"{title} {opened}")
        if _dropped(title, url, snippet):
            tier = 5
        elif tier == 2 and (plays is None or plays < _PLAY_MIN):
            tier = 3
        if tier == 2 and video_text is not None and heard < 2:
            heard += 1
            spoken = video_text(url) or ""
            if spoken:
                text = f"{text}\n{spoken}".strip()
        if not text and not title:
            continue
        seen.add(url)
        found.append({
            "title": title or url,
            "url": url,
            "text": text or title,
            "tier": tier,
            "plays": plays,
            "published_date": str(item.get("published_date") or ""),
        })
        if len(found) >= 8:
            break
    return found


def _tier(url: str) -> int:
    host = _host(url)
    path = urlparse(url or "").path or ""
    if host == _OFFICIAL or host.endswith("." + _OFFICIAL):
        return 0
    if host == _WIKI_HOST and "/nrc/" in path:
        return 1
    if any(name in host for name in _VIDEO_HOSTS):
        return 2
    return 4


def _dropped(title: str, url: str, snippet: str) -> bool:
    blob = f"{title} {url} {snippet}".lower()
    host = _host(url)
    if any(name in host for name in _DROP_HOSTS):
        return True
    return any(word.lower() in blob for word in _DROP_WORDS)


def _plays(item: dict, blob: str):
    raw = item.get("plays")
    if isinstance(raw, bool) or raw is None:
        number = None
    else:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            number = _parse_plays(str(raw))
    if number is not None:
        return number
    return _parse_plays(blob)


def _parse_plays(blob: str):
    matched = _PLAY.search(blob or "")
    if not matched:
        return None
    view = matched.group(5)
    if view:
        return int(view)
    number = matched.group(1) or matched.group(3)
    unit = matched.group(2) or matched.group(4) or ""
    value = float(number)
    if unit == "万":
        value *= 10000
    elif unit == "亿":
        value *= 100000000
    return int(value)


def _sentences(text: str) -> list:
    found = []
    for part in re.split(r"[。！？\n；;]", text or ""):
        sent = re.sub(r"\s+", " ", part).strip(" ，,、")
        if len(sent) < 6 or sent in found:
            continue
        found.append(sent)
    return found


def _join(strips: list) -> str:
    parts = []
    for item in strips:
        text = (item.get("text") or "").strip()
        if text and text not in parts:
            parts.append(text)
        if len(parts) >= 8:
            break
    return "\n".join(parts).strip()


def _items(payload) -> list:
    if isinstance(payload, dict):
        return list(payload.get("results") or payload.get("hits") or [])
    if isinstance(payload, list):
        return payload
    return []


def _call_search(search, query: str, limit: int):
    try:
        count = len(inspect.signature(search).parameters)
    except (TypeError, ValueError):
        count = 1
    if count >= 2:
        return search(query, limit)
    return search(query)


def _bare(fact: str) -> str:
    text = (fact or "").strip()
    for prefix in ("洛克王国世界", "洛克王国"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or "").removeprefix("www.").lower()


def _open_text(open_page, url: str, limit: int) -> str:
    try:
        opened = open_page(url, limit)
    except TypeError:
        opened = open_page(url)
    return opened or ""


def _read_live(label: str, query: str, open_page, rank, video_text, empty: dict) -> dict:
    """官网、维基、视频、全网各搜一轮。某一轮已经采用句子就停下。"""
    from web_search import search_web, wave_plan

    queries = []
    trace = []
    found = {"covered": [], "ambiguous": []}
    settled = {"covered": [], "conflicts": [], "unsettled": False, "text": ""}
    for spec in wave_plan(query):
        queries.append(spec["query"])
        try:
            payload = search_web(
                spec["query"],
                _SEARCH_LIMIT,
                depth=spec["depth"],
                include_domains=spec["include_domains"],
                domains_mode=spec["domains_mode"],
                ori_question=label,
            )
        except Exception as exc:
            logger.warning("联网未完成：%s", type(exc).__name__)
            payload = {"reason": "error", "results": [], "detail": type(exc).__name__}
        rows = _items(payload) if isinstance(payload, dict) else []
        trace.append({
            "wave": spec["name"],
            "query": spec["query"],
            "depth": spec["depth"],
            "reason": (payload or {}).get("reason") if isinstance(payload, dict) else "error",
            "detail": (payload or {}).get("detail") if isinstance(payload, dict) else "",
            "results": rows,
        })
        if isinstance(payload, dict) and payload.get("reason") in {"no_key", "off"}:
            empty["reason"] = payload.get("reason")
            empty["detail"] = "未配置密钥" if payload.get("reason") == "no_key" else "未开启联网"
            empty["queries"] = queries
            empty["retrieved"] = trace
            return empty
        found = _collect(label, rows, open_page, rank, found.get("ambiguous"), video_text)
        settled = _decide(label, found)
        if settled.get("text") or settled.get("unsettled"):
            break
    settled = _reason_agreed(label, settled)
    done = _finish(label, found, settled, queries)
    done["retrieved"] = trace
    return done


def _live_search(query: str, limit: int = _SEARCH_LIMIT) -> dict:
    from web_search import search_web

    return search_web(query, limit)
