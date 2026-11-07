"""监督者按计划派工。工人把结果写回账本，成文只在可以开口时发生。"""
import logging

from agents.fact_memory import admit_utterance, composition_types, concrete_composition
from agents.followup import resume_decision
from agents.intent_judge import first_dispatch, next_question
from agents.job_ledger import already_tried, blank, drop, mark_tried, park, parked, store, unwait, waiting
from agents.thoughts import note_thought

logger = logging.getLogger(__name__)

_STEP_BUDGET = 16
_PLAN_LIMIT = 4
_INTERRUPT = __import__("re").compile(r"不对|换第|换一种删法")
_CARRY = __import__("re").compile(r"该队伍|这套|这一套|上一套|刚才那套|不拘泥|不必拘泥|不局限|不用仓库")
_OFF_HOST = ("rebang.today", "tophub.today", "podcasts.apple.com", "wandoujia.com", "youtube.com", "apple.com")
_OFF_WORD = ("阴阳师", "宝可梦", "播客", "应用下载")


def run_cycle(
    question: str,
    session_id: str = "",
    judged: dict = None,
    progress=None,
    cancel=None,
    user_id: str = "",
    prepared: dict = None,
    learned=None,
    web=None,
    lineup=None,
    warehouse=None,
    lookup=None,
    save=None,
    review=None,
    route_ask=None,
) -> dict:
    """跑完这一单，或停在一个问题上等玩家。"""
    text = (question or "").strip()
    if cancel and cancel():
        return _pack(blank(session_id, text), False)
    held = waiting(session_id)
    earlier = parked(session_id)
    held_label = str(((held or {}).get("gap") or {}).get("label") or "").strip()
    from agents.followup import same_task

    if held is not None and held_label and same_task(held.get("utterance") or "", text):
        ledger = _resume(held, text, session_id)
    elif earlier is not None and _INTERRUPT.search(text):
        ledger = _interrupt(earlier, text)
    elif earlier is not None and _continues_lineup(text, earlier):
        ledger = _carry(earlier, text)
    else:
        if held is not None or earlier is not None:
            drop(session_id)
        ledger = _open(text, session_id, judged or {}, learned or [])
    ledger["reviewer"] = review
    if ledger["progress"]["next"] in {"stop", "need_ask"} and ledger.get("speech"):
        _keep(session_id, ledger)
        return _finish(session_id, text, ledger)
    _loop(
        ledger, session_id, progress, cancel, user_id, prepared,
        web, lineup, warehouse, lookup, save, route_ask,
    )
    _keep(session_id, ledger)
    return _finish(session_id, text, ledger)


def _finish(session_id: str, question: str, ledger: dict) -> dict:
    packed = _pack(ledger, _finished_ok(ledger))
    from agents.lived_memory import absorb_exchange

    absorb_exchange(session_id, question, (packed.get("order") or {}).get("answer") or "")
    return packed


def _keep(session_id: str, ledger: dict) -> None:
    if ledger["progress"].get("next") == "need_ask":
        store(session_id, ledger)
        return
    park(session_id, ledger)
    unwait(session_id)


def _open(text: str, session_id: str, judged: dict, learned: list) -> dict:
    ledger = blank(session_id, text)
    intent = (judged or {}).get("intent") or ""
    ledger["constraints"]["intent"] = intent
    ledger["constraints"]["request"] = str((judged or {}).get("request") or text).strip()
    ledger["constraints"]["source"] = text
    if intent == "battle":
        ledger["constraints"]["mode"] = "battle"
        ledger["utterance"] = next_question(text, judged)
    if intent == "remember":
        _remember(ledger, learned)
        return ledger
    word = first_dispatch(intent)
    if not word:
        _say(ledger, "灯灯这会儿没听清你要做哪一件事。再说一次。", stop=True)
        return ledger
    _read_constraints(ledger, text)
    _seed_plan(ledger, intent)
    if intent == "lineup" and _asks_hot(text):
        word = "need_both"
        ledger["gap"] = {"kind": "meta", "label": "热门"}
    ledger["job_id"] = f"{session_id or 'job'}-{ledger['plan_version']}"
    ledger["progress"]["next"] = word
    ledger["progress"]["next_assignee"] = _assignee(word)
    ledger["progress"]["instruction"] = _goal(word)
    from agents.react_stream import streaming

    if not streaming():
        note_thought(_split_line(ledger))
    return ledger


def _continues_lineup(text: str, earlier: dict) -> bool:
    """后一句说的是上一套的条件，不是另起一套。"""
    if (earlier.get("constraints") or {}).get("intent") != "lineup":
        return False
    if not (earlier.get("utterance") or "").strip():
        return False
    return bool(_CARRY.search(text or ""))


def _carry(ledger: dict, text: str) -> dict:
    """把新条件接到上一套上，清空名单再排，不另记一套。"""
    previous = (ledger.get("utterance") or "").rstrip("。")
    merged = previous + "。" + (text or "").strip()
    ledger["utterance"] = merged
    ledger["constraints"]["request"] = merged
    _read_constraints(ledger, merged)
    ledger["roster"] = []
    ledger["roster_text"] = ""
    ledger["guesses"] = []
    ledger["web_sources"] = []
    ledger["target_types"] = []
    ledger["slots"] = {"local": "closed", "web": "closed", "tried": []}
    ledger["gap"] = None
    ledger["speech"] = ""
    ledger["speech_reviewed"] = False
    ledger["replace_team_id"] = ledger.get("team_id")
    ledger["progress"]["hot_done"] = True
    ledger["progress"]["revision_reason"] = "沿用上一套"
    ledger["progress"]["satisfied"] = False
    note_thought(f"灯灯听出来这是在改上一套：{text}")
    ledger["progress"]["next"] = "need_local"
    ledger["progress"]["next_assignee"] = "资料员"
    ledger["progress"]["instruction"] = "按上一套的核心和限制，加上这句新条件"
    return ledger


def _interrupt(ledger: dict, text: str) -> dict:
    """换删法或换某一只：清空唯一名单，不把两套六人拼在一起。"""
    ledger["interrupt"] = text
    ledger["roster"] = []
    ledger["roster_text"] = ""
    ledger["plan_version"] = int(ledger.get("plan_version") or 1) + 1
    ledger["progress"]["revision_reason"] = "换一种删法"
    ledger["progress"]["hot_done"] = True
    ledger["speech"] = ""
    ledger["speech_reviewed"] = False
    ledger["gap"] = None
    if ledger["plan_version"] > _PLAN_LIMIT:
        _say(ledger, "灯灯按现有伙伴排不出六只。", stop=True)
        return ledger
    _mark(ledger, "监督者", "清空名单后换一种删法", "done")
    ledger["progress"]["next"] = "need_lineup"
    ledger["progress"]["next_assignee"] = "配队员"
    return ledger


def _resume(ledger: dict, text: str, session_id: str) -> dict:
    gap = ledger.get("gap") or {}
    if (ledger.get("constraints") or {}).get("intent") != "lineup" and gap.get("kind") == "identity":
        return _resume_fact(ledger, text, session_id, gap)
    decision = admit_utterance(session_id, text, gap)
    if not decision["keep"]:
        _say(ledger, decision["reason"] or "这句话还填不上。", stop=False)
        ledger["progress"]["next"] = "need_ask"
        return ledger
    ledger["admitted"].append({"label": gap.get("label") or "", "text": decision["text"], "source": "玩家"})
    if gap.get("kind") in {"composition", "identity", "meta"}:
        ledger["target_types"] = composition_types(decision["text"])
    ledger["facts"].append({
        "producer": "玩家",
        "authority": "player",
        "text": decision["text"],
        "covers": gap.get("label") or "",
    })
    ledger["gap"] = None
    note_thought("灯灯记下你补充的这一处")
    if gap.get("kind") == "count":
        ledger["utterance"] = (ledger.get("utterance") or "").rstrip("。") + "。" + decision["text"]
        ledger["progress"]["next"] = "need_write"
    elif gap.get("kind") == "meta":
        ledger["progress"]["hot_done"] = True
        ledger["progress"]["next"] = "need_lineup"
    else:
        ledger["progress"]["next"] = "need_lineup"
    ledger["plan_version"] = int(ledger.get("plan_version") or 1) + 1
    ledger["speech"] = ""
    return ledger


def _resume_fact(ledger: dict, text: str, session_id: str, gap: dict) -> dict:
    """玩家补上缺的那一只。抄出名字，写回原问，接着同一串步骤查。"""
    from agents.fact_read import _rate_fact, next_fact
    from agents.followup import copied_name, standalone_question
    from agents.thoughts import note_thought

    name = copied_name(text)
    label = str(gap.get("label") or "").strip()
    if not name:
        _say(ledger, "灯灯还缺这只精灵的名字。", stop=False)
        ledger["progress"]["next"] = "need_ask"
        return ledger
    fact = str(gap.get("fact") or "").strip()
    if not fact:
        if "使用率" in label:
            fact = "使用率最高的精灵"
        elif _rate_fact(label):
            fact = "出场率最高的精灵"
        else:
            fact = label or "这一处"
    sentence = f"玩家补充：{fact}是{name}。"
    _remember_hop(ledger, fact, [sentence], "player")
    original = ledger.get("utterance") or ""
    rewritten = standalone_question(original, label, name)
    ledger["utterance"] = rewritten
    ledger["constraints"]["request"] = rewritten
    ledger["constraints"]["source"] = rewritten
    ledger.setdefault("admitted", []).append({"label": label or fact, "text": text, "source": "玩家"})
    from agents.chat_notebook import remember_admitted

    remember_admitted(session_id, text, label or fact)
    progress = ledger.setdefault("progress", {})
    progress["hop_kind"] = "chain"
    progress["hop_limit"] = max(int(progress.get("hop_limit") or 0), 4)
    result = next_fact(rewritten, progress.get("hops") or [], ask=None)
    ledger["speech"] = ""
    ledger["speech_reviewed"] = False
    ledger["pending_speech"] = ""
    note_thought("灯灯按你补上的名字，接着查上一问")
    if result.get("action") == "next" and result.get("fact"):
        progress["hop_fact"] = result["fact"]
        ledger["gap"] = {"kind": "identity", "label": result["fact"], "fact": result["fact"]}
        ledger["slots"]["local"] = "empty"
        ledger["progress"]["next"] = "need_local"
        return ledger
    spoken = f"灯灯按你说的，{label or fact}是{name}。"
    if any(word in original for word in ("伤害", "本系", "威力")):
        spoken = result.get("answer") or spoken
    ledger["pending_speech"] = spoken
    ledger["gap"] = None
    ledger["slots"]["local"] = "filled"
    progress["hop_fact"] = ""
    ledger["progress"]["next"] = "speak"
    return ledger


def _loop(
    ledger, session_id, progress, cancel, user_id, prepared,
    web, lineup, warehouse, lookup, save, route_ask=None,
) -> None:
    from agents.cycle_graph import drive

    drive(
        ledger,
        session_id=session_id,
        progress=progress,
        cancel=cancel,
        prepared=prepared,
        web=web,
        lineup=lineup,
        warehouse=warehouse,
        lookup=lookup,
        save=save,
        route_ask=route_ask,
    )


def _assignee(word: str) -> str:
    return {
        "need_local": "资料员",
        "need_web": "探查员",
        "need_both": "资料员和探查员",
        "need_write": "仓库员",
        "need_ask": "成文",
        "need_lineup": "配队员",
        "check": "程序核对",
        "replan": "监督者",
        "speak": "成文",
        "surf_web": "WebSurfer",
        "surf_files": "FileSurfer",
        "coder": "Coder",
    }.get(word or "", "监督者")


def _matter(ledger: dict) -> str:
    """这一问本身，去掉句尾的标点。"""
    raw = (ledger.get("constraints") or {}).get("request") or ledger.get("utterance") or ""
    return str(raw).strip().rstrip("？?。！!")


def _named(text: str) -> list:
    from pokemon_kb import _mentioned_names, load_pokemon

    return _mentioned_names(text or "", load_pokemon())[:3]


def _split_line(ledger: dict) -> str:
    """开场那一句写出这件事被拆成的几件，调度词不出现。"""
    intent = (ledger.get("constraints") or {}).get("intent") or ""
    target = (ledger.get("constraints") or {}).get("target") or ""
    focus = (ledger.get("constraints") or {}).get("focus") or ""
    matter = _matter(ledger)
    if intent == "lineup":
        from knowledge_search import _ace_label

        parts = ["查仓库和出场规则"]
        ace = _ace_label(ledger.get("utterance") or "")
        if ace:
            parts.append(f"看{ace}")
        if focus:
            parts.append(f"以{focus}系为主")
        parts.append(f"看{target}" if target else "看还缺的那一处")
        parts.append("排一套")
        parts.append("核对")
        parts.append("看这句话")
        return "灯灯先把这件事拆成" + "、".join(parts)
    if intent == "order":
        return f"灯灯先把这件事拆成按「{matter or '这句吩咐'}」看仓库和告诉你结果"
    if intent == "battle":
        return f"灯灯先把这件事拆成查谁赢：{matter or '这场对战'}"
    names = _named(matter)
    if names:
        return "灯灯先把这件事拆成查" + "、".join(names) + (f"，看的是{matter}" if matter else "")
    return f"灯灯先把这件事拆成查{matter or '这一句'}"


_DOING = {
    "need_local": "去名录里核对这一问",
    "need_web": "到外面找名录里没有的那一处",
    "need_both": "名录和外面一起看",
    "need_write": "按玩家的吩咐看仓库",
    "need_ask": "先问玩家还缺的那一处",
    "need_lineup": "按已经看过的资料排一套",
    "check": "核对这套能不能上场",
    "replan": "换一种删法再排",
    "speak": "把查到的告诉玩家",
}


def _seen_text(ledger: dict) -> str:
    rows = []
    for block in ledger.get("facts") or []:
        if isinstance(block, dict) and block.get("text"):
            rows.append(str(block["text"])[:40])
    gap = str(((ledger.get("gap") or {}).get("label")) or "")
    if gap:
        rows.append(f"还缺{gap}")
    return "；".join(rows)[:180]


def stream_step(ledger: dict, word: str) -> bool:
    """这一步先让模型写下想法。没写出字就交给准备好的那句。"""
    from agents.react_stream import step_prompt, stream_prompt

    return stream_prompt(step_prompt(_asked(ledger), _seen_text(ledger), _DOING.get(word) or "接着办这一步"))


def _step_line(ledger: dict, word: str) -> str:
    """每派一步，带上这一步正在办的对象。"""
    target = (ledger.get("constraints") or {}).get("target") or ""
    gap = (ledger.get("gap") or {}).get("label") or ""
    focus = (ledger.get("constraints") or {}).get("focus") or ""
    subject = gap or target
    intent = (ledger.get("constraints") or {}).get("intent") or ""
    matter = _matter(ledger)
    if word == "need_local" and intent != "lineup":
        hop_line = _hop_step_line(ledger, word)
        if hop_line:
            return hop_line
        return f"灯灯去名录里查{matter or '这一句'}"
    if word == "need_local":
        from knowledge_search import _ace_label

        bits = ["仓库", "出场规则"]
        ace = _ace_label(_working(ledger))
        if ace:
            bits.append(ace)
        if subject and subject not in bits:
            bits.append(subject)
        return "灯灯先查" + "、".join(bits)
    if word == "need_web":
        hop_line = _hop_step_line(ledger, word)
        if hop_line:
            return hop_line
        return f"灯灯到外面看{subject or '这一处'}"
    if word == "need_both":
        return "灯灯同时查已有资料和外面的热门"
    if word == "need_lineup":
        if focus and subject:
            return f"灯灯开始排以{focus}系为主、针对{subject}的这一套"
        if subject:
            return f"灯灯开始排针对{subject}的这一套"
        if focus:
            return f"灯灯开始排以{focus}系为主的这一套"
        return "灯灯开始排这一套"
    if word == "check":
        return "灯灯在核对倾斜、属性、输出面和蓄力"
    if word == "replan":
        return "灯灯换一种删法，留下核心再排一次"
    if word == "need_write":
        return "灯灯按这句吩咐看仓库"
    if word == "need_ask":
        return "灯灯要先问清一件事"
    if word == "speak" and intent == "lineup":
        return "灯灯准备告诉你这一套"
    if word == "speak":
        return f"灯灯准备告诉你{matter or '这一问'}"
    if word == "surf_web":
        return f"WebSurfer 到外面看{subject or '这一处'}"
    if word == "surf_files":
        return "FileSurfer 在资料目录里找这一份"
    if word == "coder":
        return "Coder 按名录上的数字算这一道"
    return "灯灯在办"


def _goal(word: str) -> str:
    return {
        "need_local": "查名录、规则、克制和仓库",
        "need_web": "只查当前这一处缺口",
        "need_both": "本地和网页两槽一起填",
        "need_write": "问清通过后读写仓库",
        "need_ask": "只问还缺的那一件",
        "need_lineup": "证据够了才选一次",
        "check": "核对倾斜、属性、输出面和蓄力",
        "replan": "换一种删法",
        "speak": "只说账本允许说的内容",
        "surf_web": "到外面打开一页",
        "surf_files": "在允许的目录里读一份资料",
        "coder": "只算已经允许的那一道",
    }.get(word or "", "写下一步")


def _mark(ledger: dict, assignee: str, goal: str, status: str) -> None:
    steps = ledger.setdefault("plan", [])
    version = int(ledger.get("plan_version") or 1)
    for step in steps:
        if step.get("assignee") == assignee and step.get("goal") == goal and step.get("version") == version and step.get("status") != "done":
            step["status"] = status
            return
    steps.append({
        "id": f"p{version}-{len(steps) + 1}",
        "version": version,
        "assignee": assignee,
        "goal": goal,
        "depends_on": [steps[-1]["id"]] if steps else [],
        "status": status,
        "word": "",
    })


def _seed_plan(ledger: dict, intent: str) -> None:
    if intent == "lineup":
        rows = [
            ("监督者", "拆开核心和限制对象"),
            ("资料员", "查名录、规则、克制和仓库"),
            ("探查员", "名录没有再查这一处"),
            ("问清", "两处都空就只问一件"),
            ("配队员", "证据够了才选一次"),
            ("程序核对", "核对倾斜、属性、输出面和蓄力"),
            ("资料员和探查员", "热门再走同一圈"),
            ("配队员", "清空名单后再选一次"),
            ("程序核对", "热门之后再核对"),
            ("成文", "只说账本允许说的内容"),
        ]
    elif intent == "order":
        rows = [
            ("问清", "只数没写清就只问只数"),
            ("仓库员", "问清通过后读写仓库"),
            ("成文", "只说仓库结果"),
        ]
    else:
        rows = [
            ("资料员", "先查名录"),
            ("探查员", "名录没有才联网"),
            ("成文", "只说查到的资料"),
        ]
    for assignee, goal in rows:
        _mark(ledger, assignee, goal, "pending")


def _read_constraints(ledger: dict, text: str) -> None:
    from agents.battle_orders import _roster_unbounded
    from agents.rag_agent import _focus_type, _target_label

    ledger["constraints"]["focus"] = _focus_type(text)
    ledger["constraints"]["target"] = _target_label(text)
    ledger["constraints"]["warehouse_only"] = not _roster_unbounded(text)
    matched = __import__("re").search(r"第\s*([1-6一二三四五六])\s*只", text or "")
    ledger["constraints"]["replace_slot"] = matched.group(1) if matched else ""


def _add_fact(ledger: dict, producer: str, authority: str, text: str, covers: str) -> None:
    ledger["facts"].append({
        "id": f"fact-{len(ledger['facts']) + 1}",
        "producer": producer,
        "authority": authority,
        "text": text,
        "covers": covers,
    })


def _local(ledger: dict, lookup, prepared) -> None:
    from agents.fact_read import _rate_fact

    status = _fill_local(ledger, lookup, prepared)
    if ledger["constraints"].get("intent") == "lineup":
        _after_local_lineup(ledger, status)
        return
    if status == "trial":
        ledger["progress"]["next"] = "speak"
        return
    if status == "ready":
        ledger["progress"]["next"] = "speak"
        return
    # HALT / 充足性闸已经写成 need_ask 时，不要再改道去网页。
    if (ledger.get("progress") or {}).get("next") == "need_ask":
        return
    label = ((ledger.get("gap") or {}).get("label")) or ledger.get("utterance") or "这一处"
    ask = ((ledger.get("gap") or {}).get("ask")) or ""
    if _rate_fact(label) and _may_web(ledger, label):
        _open_web(ledger, label)
        return
    if ledger["constraints"].get("mode") == "battle" or not _may_web(ledger, label):
        _ask(ledger, "identity", label, ask or "灯灯没有翻到。跟灯灯说一下这一处。")
        return
    _open_web(ledger, label)


def _web_tried(ledger: dict) -> bool:
    tried = (ledger.get("slots") or {}).get("tried") or []
    return "web" in tried or any(str(item).startswith("web:") for item in tried)


def _wants_trial(text: str) -> bool:
    body = text or ""
    if any(word in body for word in ("多少伤害", "伤害数字", "倍率")):
        return False
    return any(word in body for word in ("谁会赢", "谁赢", "打得过"))


def _hop_step_line(ledger: dict, word: str) -> str:
    progress = ledger.get("progress") or {}
    if progress.get("hop_kind") != "chain":
        return ""
    if word == "need_web":
        fact = ((ledger.get("gap") or {}).get("label")) or ""
    else:
        fact = progress.get("hop_fact") or ""
    if not fact:
        return ""
    index = len(progress.get("hops") or []) + 1
    if word == "need_web":
        return f"灯灯到外面看第{index}步：{fact}"
    return f"灯灯去名录里查第{index}步：{fact}"


def _asked(ledger: dict) -> str:
    """按玩家原句核对。听要求时改过的句子只用于开场说明。"""
    source = (ledger.get("constraints") or {}).get("source") or ""
    return source or ledger.get("utterance") or ""


def _open_web(ledger: dict, label: str) -> None:
    from agents.fact_read import _rate_fact
    from agents.thoughts import note_thought

    _request(ledger, "identity", label)
    if not ledger.get("gap"):
        ledger["gap"] = {"kind": "identity", "label": label}
    if _rate_fact(label):
        from agents.react_stream import streaming
        from agents.thoughts import note_read

        if streaming():
            note_read(f"名录里没有{label}")
        else:
            note_thought("名录里没有这一处，灯灯到外面看")
    ledger["progress"]["next"] = "need_web"


def _read_facts(ledger: dict):
    """知识题先按事实核对原文。认不出形状时返回 None，仍走原来的整句。"""
    from agents.battle_agent import open_battle
    from agents.fact_read import classify_hops, read_facts, skill_tokens
    from agents.thoughts import note_read

    question = _asked(ledger)
    progress = ledger.setdefault("progress", {})
    if progress.get("hop_kind") == "chain" and progress.get("hops"):
        return _read_chain(ledger, {
            "limit": int(progress.get("hop_limit") or 4),
            "first": progress.get("hop_fact") or "",
        })
    from agents.adaptive_rag import parametric_answer, route_adaptive
    from agents.lived_memory import recall_answer
    from agents.story_read import is_persona_story, read_dengdeng_story

    # C：人设故事专路由，不进名录/网页（Self-RAG：无检索必要）
    if is_persona_story(question) or ledger["constraints"].get("intent") == "persona_story":
        note_thought("这一问是灯灯自个儿的故事，翻故事本就好")
        story = read_dengdeng_story(question)
        ledger["pending_speech"] = story.get("speech") or ""
        ledger["slots"]["local"] = "filled" if story.get("covered") else "empty"
        ledger["gap"] = None
        if story.get("covered"):
            _add_fact(ledger, "故事", "persona", story.get("speech") or "", "灯灯的成长故事")
            return "ready"
        _ask(ledger, "identity", "灯灯的故事", story.get("speech") or "灯灯还没翻到自个儿的故事。")
        return "missing"

    grade = route_adaptive(question)
    progress["adaptive"] = grade
    # B：archival 谓词召回（含出场率；不限 adaptive 档）
    remembered = recall_answer(ledger.get("session_id") or "", question)
    if remembered:
        note_read("灯灯翻到以前记下的这一处")
        ledger["pending_speech"] = remembered
        ledger["slots"]["local"] = "filled"
        ledger["gap"] = None
        _add_fact(ledger, "记忆", "memory", remembered, question)
        return "ready"
    if grade == "A":
        note_thought("这一问不查名录，灯灯按记得的说")
        ledger["pending_speech"] = parametric_answer(question, ledger.get("session_id") or "")
        ledger["slots"]["local"] = "filled"
        ledger["gap"] = None
        return "ready"
    opened = open_battle(question)
    if opened is not None:
        return _apply_battle(ledger, opened)
    if _wants_trial(question):
        return None
    classified = classify_hops(question)
    if classified["kind"] == "chain":
        return _read_chain(ledger, classified)
    read = read_facts(question)
    queries = read["queries"]
    if not queries:
        return None
    kept = ledger.setdefault("progress", {})
    kept["fact_queries"] = list(queries)
    from agents.react_stream import streaming

    live = streaming()
    if not live:
        for fact in queries:
            note_read(f"正在查{fact}")
        names = _named(question)
        if names:
            note_read("正在看" + "、".join(names))
    tokens = []
    for item in read["covered"]:
        _add_fact(ledger, "资料员", "catalog", " ".join(item["lines"]), item["fact"])
        if str(item.get("fact") or "").endswith("的技能"):
            for name in skill_tokens(item.get("lines") or []):
                if name not in tokens:
                    tokens.append(name)
    if tokens:
        kept["keep_tokens"] = tokens
    if live:
        for item in read["covered"]:
            snippet = " ".join(item.get("lines") or [])[:80]
            note_read(snippet or f"名录里有{item.get('fact') or '这一处'}")
        for fact in read["missing"]:
            note_read(f"名录里没有{fact}")
    if read["missing"]:
        missing = read["missing"][0]
        ledger["gap"] = {"kind": "identity", "label": missing, "ask": read["ask"]}
        ledger["slots"]["local"] = "empty"
        if read["speech"]:
            ledger["pending_speech"] = read["speech"]
        return "missing"
    ledger["pending_speech"] = read["speech"]
    ledger["slots"]["local"] = "filled"
    ledger["gap"] = None
    if live and not kept.get("hop_kind"):
        from agents.react_stream import ircot_fact

        nxt = ircot_fact(question, read.get("speech") or "")
        have = {item.get("fact") for item in read["covered"]}
        if nxt and nxt not in have:
            kept["hops"] = [
                {
                    "fact": item.get("fact") or "",
                    "text": " ".join(item.get("lines") or []),
                    "lines": list(item.get("lines") or []),
                    "names": [],
                }
                for item in read["covered"]
            ]
            kept["hop_kind"] = "chain"
            kept["hop_limit"] = 4
            kept["hop_fact"] = nxt
            return _read_chain(ledger, {"limit": 4, "first": nxt})
    return "ready"


def _read_chain(ledger: dict, classified: dict) -> str:
    """多步只查当前这一句。对上之后再写下一句。"""
    from agents.fact_read import _ask_sentence, _power_tail, _rate_fact, chain_answer, next_fact, read_one
    from agents.thoughts import note_read

    progress = ledger.setdefault("progress", {})
    progress["hop_kind"] = "chain"
    progress["hop_limit"] = int(classified.get("limit") or 4)
    progress.setdefault("hops", [])
    if not progress.get("hop_fact"):
        progress["hop_fact"] = classified.get("first") or ""
    question = _asked(ledger)
    guard = 0
    while guard < progress["hop_limit"]:
        guard += 1
        steps = progress["hops"]
        fact = progress.get("hop_fact") or ""
        if not fact or any(item.get("fact") == fact for item in steps) or len(steps) >= progress["hop_limit"]:
            break
        from agents.react_stream import streaming

        live = streaming()
        if not live:
            note_read(f"正在查第{len(steps) + 1}步：{fact}")
        queries = progress.setdefault("fact_queries", [])
        if fact not in queries:
            queries.append(fact)
        one = read_one(fact)
        gate = one.get("gate") or {}
        if live:
            if one["covered"]:
                note_read((" ".join(one.get("lines") or [])[:80]) or f"名录里有{fact}")
            elif gate.get("status") == "partial":
                note_read(f"名录里{fact}还不齐：{gate.get('detail') or '证据偏窄'}")
            else:
                note_read(f"名录里没有{fact}")
        if not one["covered"]:
            speech = chain_answer(question, steps)
            from agents.fact_read import outside_query

            label = outside_query(question) or fact if _rate_fact(fact) else fact
            ask = _ask_sentence(fact, speech)
            if gate.get("detail"):
                ask = f"{speech}灯灯翻到的还不够齐（{gate.get('detail')}）。跟灯灯说一下{fact}。" if speech else (
                    f"灯灯翻到的{fact}还不齐（{gate.get('detail')}）。跟灯灯说一下。"
                )
            ledger["gap"] = {
                "kind": "identity",
                "label": label,
                "fact": fact,
                "ask": ask,
                "gate": gate,
            }
            ledger["slots"]["local"] = "empty"
            progress["evidence_gate"] = gate
            if speech:
                ledger["pending_speech"] = speech
            # partial 技能比较：先尝试网页补全，再问人
            if gate.get("status") == "partial" and _may_web(ledger, fact) and not _rate_fact(fact):
                _open_web(ledger, fact)
                return "missing"
            return "missing"
        authority = "rules" if _power_tail(fact) else "catalog"
        _remember_hop(ledger, fact, one["lines"], authority)
        progress["evidence_gate"] = gate
        from agents.react_stream import streaming

        ask = _model_next if streaming() else None
        result = next_fact(question, progress["hops"], ask=ask)
        if result.get("action") != "next":
            return _halt_or_ready(ledger, question, result.get("answer") or "")
        progress["hop_fact"] = result.get("fact") or ""
    return _halt_or_ready(ledger, question, "")


def _apply_battle(ledger: dict, opened: dict) -> str:
    from agents.thoughts import note_read

    if opened.get("kind") == "simulate" and opened.get("trial"):
        ledger["trial"] = opened["trial"]
        ledger["pending_speech"] = opened.get("speech") or ""
        ledger["slots"]["local"] = "filled"
        ledger["gap"] = None
        note_read("对战员正在看这场对战")
        return "trial"
    ledger["pending_speech"] = opened.get("speech") or ""
    ledger["slots"]["local"] = "filled"
    ledger["gap"] = None
    note_read("对战员正在算这一下的伤害")
    _add_fact(ledger, "对战员", "catalog", opened.get("speech") or "", "这一下的最终伤害数字")
    return "ready"


def _remember_hop(ledger: dict, fact: str, lines: list, authority: str) -> None:
    from agents.fact_read import names_in

    kept = [line.strip() for line in lines if (line or "").strip()]
    text = " ".join(kept)
    ledger.setdefault("progress", {}).setdefault("hops", []).append({
        "fact": fact,
        "text": text,
        "lines": kept,
        "names": names_in(fact, text),
    })
    producer = {"web": "探查员", "player": "玩家"}.get(authority, "资料员")
    _add_fact(ledger, producer, authority, text, fact)


def _model_next(question: str, steps: list) -> str:
    """模板写不出下一句时，请模型只写一条事实。名字对不上就由调用方停下。"""
    from llm_provider import get_team_invoke

    covered = "\n".join(
        f"{item.get('fact')}：{item.get('text')}" for item in (steps or []) if item.get("text")
    )
    prompt = (
        "根据已经对上的原文，写下一句要查的事实。"
        "只输出这一句，不超过20个字。"
        "句中的精灵名必须出现在原文或原问题里。"
        "没有下一步就只输出：完成\n"
        f"原问题：{question}\n已对上：\n{covered}"
    )
    try:
        raw = get_team_invoke(12)(prompt)
    except Exception as exc:
        logger.warning("下一步事实未写成：%s", type(exc).__name__)
        return ""
    text = getattr(raw, "content", None) or str(raw or "")
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line.strip()


def _halt_or_ready(ledger: dict, question: str, speech: str = "") -> str:
    """HALT：claims 未齐不 speak；Self-RAG critique 不通过则问人。"""
    from agents.evidence_gate import critique_answer, halt_ready
    from agents.fact_read import chain_answer

    progress = ledger.setdefault("progress", {})
    hops = progress.get("hops") or []
    text = (speech or "").strip() or chain_answer(question, hops)
    halt = halt_ready(question, hops, text)
    progress["halt"] = halt
    critique = critique_answer(question, text, hops)
    progress["critique"] = {
        "pass": critique.get("pass"),
        "issues": list(critique.get("issues") or []),
        "relation": critique.get("relation") or "",
    }
    if not halt.get("ok") or not critique.get("pass"):
        missing = halt.get("missing") or []
        label = (missing[0].get("label") if missing else "") or "这一处"
        ask = halt.get("ask") or f"灯灯还缺{label}。跟灯灯说一下。"
        from agents.thoughts import note_thought

        note_thought("证据还没盖住这一问，灯灯先不收口")
        _ask(ledger, "identity", label, ask)
        ledger["slots"]["local"] = "empty"
        if text:
            ledger["pending_speech"] = text
        progress["hop_fact"] = progress.get("hop_fact") or (missing[0].get("id") if missing else "")
        return "missing"
    ledger["pending_speech"] = text
    ledger["gap"] = None
    ledger["slots"]["local"] = "filled"
    progress["hop_fact"] = ""
    return "ready"


def _continue_chain(ledger: dict) -> str:
    """网页对上当前这一步后，写出下一步。返回 continue、ready、missing 或 skip。"""
    from agents.evidence_gate import SUPPORT, judge_sufficiency
    from agents.fact_read import _rate_fact, chain_answer, next_fact

    progress = ledger.setdefault("progress", {})
    if progress.get("hop_kind") != "chain":
        return "skip"
    fact = progress.get("hop_fact") or progress.get("rate_hop") or ""
    text = ""
    for item in reversed(ledger.get("guesses") or []):
        if item.get("grade") != "对得上" or not (item.get("text") or "").strip():
            continue
        covers = item.get("covers") or ""
        if covers == fact or (fact and covers == progress.get("rate_hop")) or (
            _rate_fact(covers) and _rate_fact(fact)
        ):
            text = item["text"].strip()
            break
    if not fact or not text:
        return "skip"
    steps = progress.setdefault("hops", [])
    if any(item.get("fact") == fact for item in steps):
        return "skip"
    gate = judge_sufficiency(fact, [text], {"name": "", "text": text, "fill": "hit"})
    progress["evidence_gate"] = gate
    if gate.get("status") != SUPPORT and _rate_fact(fact):
        # 网页摘录仍不够当冠军句
        from agents.thoughts import note_thought

        note_thought(f"网页证据偏窄：{gate.get('detail') or '不足'}")
        _ask(ledger, "identity", fact, f"灯灯到外面看了，还不敢认定{fact}。跟灯灯说一下这一处。")
        return "missing"
    _remember_hop(ledger, fact, [text], "web")
    from agents.react_stream import streaming

    # 模板优先；模型下一步仍受队伍闸门约束，避免写成「毒队的属性」。
    result = next_fact(ledger.get("utterance") or "", progress["hops"], ask=None)
    if result.get("action") != "next" and streaming():
        result = next_fact(
            ledger.get("utterance") or "",
            progress["hops"],
            ask=_model_next,
        )
    limit = int(progress.get("hop_limit") or 4)
    if (
        result.get("action") == "next"
        and result.get("fact")
        and result["fact"] != fact
        and len(progress["hops"]) < limit
    ):
        progress["hop_fact"] = result["fact"]
        ledger["gap"] = {"kind": "identity", "label": result["fact"]}
        return "continue"
    status = _halt_or_ready(ledger, ledger.get("utterance") or "", result.get("answer") or "")
    return "ready" if status == "ready" else status


def _may_web(ledger: dict, label: str) -> bool:
    """单步仍是上过网就不再上。多步按这一句事实另算，整问最多三次上网。"""
    progress = ledger.get("progress") or {}
    tried = (ledger.get("slots") or {}).get("tried") or []
    if progress.get("hop_kind") == "chain":
        if int(progress.get("web_calls") or 0) >= 3:
            return False
        return ("web:" + (label or "")) not in tried
    return not _web_tried(ledger)


def _fill_local(ledger: dict, lookup, prepared) -> str:
    """资料员一步取一条。取完把槽交给监督者，自己不决定下一步。"""
    from agents.thoughts import note_read

    ledger["slots"]["local"] = "open"
    mark_tried(ledger, "local")
    if ledger["constraints"].get("intent") != "lineup":
        read = _read_facts(ledger)
        if read is not None:
            return read
        found = _lookup(ledger, lookup, prepared, use_web=False)
        if found.get("trial"):
            ledger["trial"] = found["trial"]
            ledger["pending_speech"] = found.get("answer") or ""
            from agents.react_stream import streaming

            if streaming():
                note_read((found.get("answer") or "这场对战有结果了")[:80])
            else:
                note_read("正在看这场对战")
            return "trial"
        outside = ""
        from agents.fact_read import outside_query

        outside = outside_query(_asked(ledger))
        if found.get("found") and not outside:
            _add_fact(ledger, "资料员", "catalog", found.get("answer") or "", ledger.get("utterance") or "")
            ledger["pending_speech"] = found.get("answer") or ""
            ledger["slots"]["local"] = "filled"
            from agents.react_stream import streaming

            if streaming():
                note_read((found.get("answer") or "名录里有这一处")[:80])
            else:
                names = _named(ledger.get("utterance") or "")
                if names:
                    note_read("正在看" + "、".join(names))
                else:
                    note_read(f"正在看和「{_matter(ledger) or '这一句'}」有关的资料")
            return "ready"
        if outside:
            ledger["gap"] = {
                "kind": "identity",
                "label": outside,
                "ask": f"灯灯还没翻到{outside}。跟灯灯说一下。",
            }
            ledger["slots"]["local"] = "empty"
            ledger["pending_speech"] = ""
            return "missing"
        ledger["slots"]["local"] = "empty"
        return "missing"
    return _fill_local_lineup(ledger)


def _fill_local_lineup(ledger: dict) -> str:
    from agents.battle_orders import _catalog, _stock
    from agents.chat_notebook import catalog_for_session
    from agents.rag_agent import _resolve_target, _target_label
    from agents.thoughts import note_read
    from pokemon_kb import load_rules

    note_read("正在看仓库里有哪些伙伴")
    stock = _stock()
    _add_fact(ledger, "资料员", "warehouse", f"仓库里有{len(stock)}只可出场的伙伴", "warehouse")
    note_read("正在看出场规则")
    _add_fact(ledger, "资料员", "rules", "出场规则已读" if load_rules() else "出场规则没读到", "rules")
    from knowledge_search import _ace_label

    label = _target_label(_working(ledger)) or ledger["constraints"].get("target") or ""
    catalog = catalog_for_session(_catalog(), ledger.get("session_id") or "")
    ace = _ace_label(_working(ledger))
    if ace and ace not in catalog and not ledger.get("guest") and not already_tried(ledger, "web:" + ace):
        note_read(f"正在名录里找{ace}")
        ledger["slots"]["local"] = "empty"
        return "missing_ace"
    target = _resolve_target(label, catalog) if label else {"missing": "", "types": []}
    if label:
        note_read(f"正在名录里找{label}")
    covered = _gap_covered(ledger, label)
    if label and target.get("missing") and not covered:
        ledger["slots"]["local"] = "empty"
        return "missing"
    if target.get("types") and not ledger.get("target_types"):
        ledger["target_types"] = list(target.get("types") or [])
    _add_fact(ledger, "资料员", "catalog", label or "名录里的出场条件", label or "core")
    ledger["slots"]["local"] = "filled"
    return "ready"


def _after_local_lineup(ledger: dict, status: str) -> None:
    label = ledger["constraints"].get("target") or ""
    from agents.rag_agent import _target_label

    from knowledge_search import _ace_label

    label = _target_label(_working(ledger)) or label
    if status == "missing_ace":
        ace = _ace_label(_working(ledger)) or "主力"
        _request(ledger, "sprite", ace)
        ledger["gap"] = {"kind": "sprite", "label": ace}
        ledger["progress"]["next"] = "need_web"
        return
    if status == "missing":
        _request(ledger, "identity", label or "限制对象")
        if already_tried(ledger, "web:" + (label or "限制对象")):
            _ask(ledger, "composition", label or "这一处", f"灯灯还不知道{label or '这一处'}的组成和打法。跟灯灯说一下。")
            return
        ledger["gap"] = {"kind": "composition", "label": label or "这一处"}
        ledger["progress"]["next"] = "need_web"
        return
    ledger["progress"]["next"] = "need_lineup"


def _web(ledger: dict, web, lookup) -> None:
    status = _fill_web(ledger, web, lookup)
    _after_web(ledger, status, lookup)


def _both(ledger: dict, lookup, prepared, web) -> None:
    """两个槽一起打开，都填完才回到监督者。限制对象仍空时，只问那一件。"""
    hot_round = _both_hot(ledger)
    if not ledger.get("gap"):
        ledger["gap"] = {"kind": "meta", "label": "热门"}
    local_status = _fill_local(ledger, lookup, prepared)
    if hot_round:
        ledger["gap"] = {"kind": "meta", "label": "热门"}
    status = _fill_web(ledger, web, lookup)
    _finish_both(ledger, local_status, status, lookup)


def _both_hot(ledger: dict) -> bool:
    gap = ledger.get("gap") or {}
    return not gap or gap.get("kind") == "meta"


def _finish_both(ledger: dict, local_status: str, status: str, lookup) -> None:
    """本地和网页都回来之后再决定下一词。名单仍只有一份。"""
    from agents.rag_agent import _target_label

    label = _target_label(_working(ledger)) or ledger["constraints"].get("target") or "这一处"
    if ledger["constraints"].get("intent") == "lineup" and local_status == "missing":
        if status == "useful":
            ledger["progress"]["hot_done"] = True
        _request(ledger, "identity", label)
        _ask(ledger, "composition", label, f"灯灯还不知道{label}的组成和打法。跟灯灯说一下。")
        return
    _after_web(ledger, status, lookup)


def _fill_web(ledger: dict, web, lookup) -> str:
    from agents.fact_read import _rate_fact

    if ledger["constraints"].get("intent") == "order":
        ledger["slots"]["web"] = "closed"
        return "closed"
    gap = ledger.get("gap") or {}
    label = gap.get("label") or ""
    kind = gap.get("kind") or "identity"
    if kind == "meta":
        label = "热门"
        ledger["gap"] = {"kind": "meta", "label": "热门"}
    query = label or ledger.get("utterance") or ""
    ledger["slots"]["web"] = "open"
    if kind == "sprite" and query:
        mark_tried(ledger, "web:" + query)
        guest, pages = _read_outside_ace(ledger, web, query)
        kept = ledger.setdefault("web_sources", [])
        seen = {item.get("url") for item in kept}
        for page in pages:
            if page.get("url") and page["url"] not in seen:
                kept.append(page)
                seen.add(page["url"])
        if guest:
            ledger["guest"] = guest
            ledger["slots"]["web"] = "filled"
            return "useful"
        ledger["slots"]["web"] = "empty"
        return "empty"
    mark_tried(ledger, "web:" + query)
    found_pages = []
    outcome = _web_outcome(web, query, found_pages)
    kept = ledger.setdefault("web_sources", [])
    seen = {item.get("url") for item in kept}
    progress = ledger.setdefault("progress", {})
    urls = progress.setdefault("web_urls", [])
    for page in found_pages:
        url = page.get("url") or ""
        if url and url in urls:
            continue
        if url:
            urls.append(url)
        if url and url not in seen:
            kept.append(page)
            seen.add(url)
        elif not url:
            kept.append(page)
    if progress.get("hop_kind") == "chain":
        progress["web_calls"] = int(progress.get("web_calls") or 0) + 1
    progress.setdefault("web_queries", [])
    for item in outcome.get("queries") or []:
        if item not in progress["web_queries"]:
            progress["web_queries"].append(item)
    for item in outcome.get("ambiguous") or []:
        _add_guess(ledger, item.get("text") or "", "", "含糊")
    for item in outcome.get("conflicts") or []:
        _add_guess(ledger, item.get("text") or "", "", "矛盾")
    if outcome.get("unsettled"):
        ask = f"外面这几页对{query}的说法不一致。跟灯灯说一下。"
        gap = ledger.get("gap") or {"kind": kind, "label": query}
        gap["ask"] = ask
        ledger["gap"] = gap
        ledger["slots"]["web"] = "empty"
        return "empty"
    blob = outcome.get("text") or ""
    if outcome.get("reason") == "off":
        ledger["slots"]["web"] = "empty"
        return "off"
    cover = query
    hop = (progress.get("hop_fact") or "")
    rate_hop = progress.get("rate_hop") or ""
    if hop and cover != hop and _rate_fact(hop) and _rate_fact(cover):
        cover = hop
    chain = progress.get("hop_kind") == "chain"
    fill = (outcome.get("fill") or "").strip()
    bridge = (outcome.get("bridge") or "").strip()
    name = (outcome.get("name") or "").strip()
    bridging = bool((ledger.get("gap") or {}).get("bridge"))

    # 桥跳回来（CRAG/IRCoT）：阵容页只填 lineup_members，禁止升格为 rate_champion。
    if bridging or (progress.get("bridge_used") and rate_hop and not _rate_fact(query)):
        from agents.evidence_slots import (
            AMBIGUOUS,
            CORRECT,
            crag_rate_champion,
            rate_ask_from_members,
        )
        from agents.fact_read import _targets, _team_like
        from agents.thoughts import note_thought
        from agents.web_read import _catalog_names

        pool = " ".join(
            part for part in [
                blob,
                name,
                " ".join(item.get("text") or "" for item in (outcome.get("covered") or [])),
                " ".join(item.get("title") or "" for item in (outcome.get("covered") or [])),
            ] if part
        )
        avoid = set(_targets(_asked(ledger)))
        judged = crag_rate_champion(pool, fill=fill, bridge=bridge or "桥", name=name)
        progress["crag"] = judged
        members = [
            item
            for item in (judged.get("members") or _catalog_names(pool) or [])
            if item and item not in avoid and not _team_like(item)
        ]
        progress["lineup_members"] = members
        target = rate_hop or hop or "出场率最高的精灵"
        # Correct：桥页上居然有「最高是〔名录〕」——极少见，才允许写冠军。
        if judged.get("status") == CORRECT and judged.get("champion"):
            blob = f"{target}是{judged['champion']}。"
            _add_guess(ledger, blob, target, "对得上")
            ledger["slots"]["web"] = "filled"
            progress["bridge_done"] = True
            return "useful"
        # Ambiguous/Incorrect：有成员也不升格；问人（Self-RAG：不支持则不断言）。
        note_thought("阵容证据不能直接当成出场率第一")
        ask = rate_ask_from_members(members, target)
        _ask(ledger, "identity", target, ask)
        ledger["slots"]["web"] = "empty"
        progress["bridge_done"] = True
        progress["bridge_ambiguous"] = judged.get("status") == AMBIGUOUS
        return "empty"

    # 出场率：Hit / Bridge / Miss（CRAG：仅 Correct 冠军句可 Hit）
    if _rate_fact(cover) or _rate_fact(hop) or _rate_fact(query):
        from agents.evidence_slots import CORRECT, crag_rate_champion
        from agents.fact_read import bridge_followup

        target = hop if _rate_fact(hop) else cover
        judged = crag_rate_champion(blob, fill=fill, bridge=bridge, name=name)
        progress["crag"] = judged
        if judged.get("status") == CORRECT and judged.get("champion"):
            blob = f"{target}是{judged['champion']}。"
            _add_guess(ledger, blob, target, "对得上")
            ledger["slots"]["web"] = "filled"
            return "useful"
        if (fill == "bridge" or bridge) and not progress.get("bridge_used"):
            from agents.thoughts import note_thought

            entity = bridge or "这套阵容"
            progress["bridge_used"] = True
            progress["rate_hop"] = hop if _rate_fact(hop) else (cover if _rate_fact(cover) else hop or cover)
            progress["lineup_members"] = list(judged.get("members") or [])
            follow = bridge_followup(entity)
            ledger["gap"] = {
                "kind": "identity",
                "label": follow,
                "fact": progress["rate_hop"],
                "bridge": True,
                "ask": f"灯灯看到{entity}，再查里面的精灵。",
            }
            ledger["slots"]["web"] = "empty"
            note_thought(f"灯灯先顺着{entity}去查出场精灵")
            return "bridge"
        ledger["slots"]["web"] = "empty"
        return "empty"

    if not blob:
        ledger["slots"]["web"] = "empty"
        return "empty"
    if _catalog_blocks(ledger, query):
        _add_guess(ledger, blob, "", "舍弃")
        ledger["slots"]["web"] = "filled"
        return "useful"
    _add_guess(ledger, blob, cover, "对得上")
    ledger["slots"]["web"] = "filled"
    kind = (ledger.get("gap") or {}).get("kind") or kind
    if ledger["constraints"].get("intent") == "lineup" and kind in {"composition", "identity"} and concrete_composition(blob):
        ledger["target_types"] = composition_types(blob) or ledger.get("target_types") or []
    # 多跳时网页全文不进开口草稿，只保留本跳中间答给 next_fact。
    if not chain and kind != "meta" and ledger["constraints"].get("intent") != "lineup":
        head = (ledger.get("pending_speech") or "").strip()
        ledger["pending_speech"] = f"{head} {blob}".strip() if head else blob
    return "useful"


def _catalog_blocks(ledger: dict, label: str) -> bool:
    """名录已经写明的种族值、技能、克制、特性，不被网页句子换掉。"""
    if not any(word in (label or "") for word in ("种族值", "技能", "克制", "抵抗", "特性")):
        return False
    for item in ledger.get("facts") or []:
        if item.get("authority") in {"catalog", "rules"} and item.get("covers") == label:
            return True
    return False


def _after_web(ledger: dict, status: str, lookup) -> None:
    from agents.fact_read import _rate_fact

    if status == "closed":
        ledger["progress"]["next"] = "need_write"
        return
    kind = (ledger.get("gap") or {}).get("kind") or "identity"
    label = (ledger.get("gap") or {}).get("label") or "这一处"
    lineup = ledger["constraints"].get("intent") == "lineup"
    progress = ledger.setdefault("progress", {})
    if kind == "sprite":
        ledger["gap"] = None
        ledger["progress"]["next"] = "need_local"
        return
    if status == "bridge":
        # 已写好 bridge gap.label，再上网只查成员。
        ledger["progress"]["next"] = "need_web"
        return
    if status == "useful":
        # 桥跳补到精灵名后，cover 在 rate_hop 上，继续链。
        if progress.get("bridge_done") and progress.get("rate_hop"):
            progress["hop_fact"] = progress["rate_hop"]
        advanced = "skip"
        if not lineup and kind not in {"meta", "sprite"}:
            advanced = _continue_chain(ledger)
        if advanced == "continue":
            ledger["progress"]["next"] = "need_local"
            return
        if advanced == "ready":
            ledger["progress"]["next"] = "speak"
            return
        if advanced == "missing":
            # HALT / 充足性闸已写好 ask
            return
        ledger["gap"] = None
        if kind == "meta":
            ledger["progress"]["hot_done"] = True
            ledger["progress"]["next"] = "need_lineup"
            return
        ledger["progress"]["next"] = "need_lineup" if lineup else "speak"
        return
    if kind == "meta":
        _ask(ledger, "meta", "热门", "灯灯还不知道现在热门的精灵和阵容。跟灯灯说一下。")
        return
    # 桥跳 Ambiguous 已写好 CRAG ask 时，不要覆盖成「没翻到」。
    if status == "empty" and (ledger.get("progress") or {}).get("next") == "need_ask":
        kept_ask = (
            ((ledger.get("gap") or {}).get("ask") or "")
            or ((ledger.get("write") or {}).get("pending_question") or "")
            or (ledger.get("speech") or "")
            or (ledger.get("pending_speech") or "")
        )
        if "不敢认定" in kept_ask or "阵容里看到" in kept_ask:
            return
    if status == "empty" and (ledger.get("progress") or {}).get("bridge_ambiguous"):
        # 双保险：CRAG Ambiguous 标记在，只保留已有问句
        if ledger.get("speech") or ((ledger.get("write") or {}).get("pending_question")):
            ledger["progress"]["next"] = "need_ask"
            return
    # 桥跳失败或出场率仍空：停下来问人，不再发明队的属性。
    ask_label = progress.get("rate_hop") or ((ledger.get("gap") or {}).get("fact")) or label
    if not lineup and (_rate_fact(ask_label) or _rate_fact(label) or (ledger.get("gap") or {}).get("bridge")) and status in {"off", "empty"}:
        if status == "off":
            sentence = f"名录里没有{ask_label}。跟灯灯说一下这一处。"
        else:
            sentence = f"灯灯到外面看了，没翻到{ask_label}。跟灯灯说一下这一处。"
        _ask(ledger, "identity", ask_label, sentence)
        kept = ledger.get("gap") or {}
        if progress.get("hop_fact") and not kept.get("fact"):
            kept["fact"] = progress["hop_fact"]
            ledger["gap"] = kept
        elif progress.get("rate_hop"):
            kept["fact"] = progress["rate_hop"]
            ledger["gap"] = kept
        return
    if not lineup:
        sentence = ((ledger.get("gap") or {}).get("ask")) or "灯灯没有翻到。跟灯灯说一下这一处。"
        _ask(ledger, "identity", label, sentence)
        return
    _ask(ledger, "composition", label, f"灯灯还不知道{label}的组成和打法。跟灯灯说一下。")


def _lineup(ledger: dict, lineup) -> None:
    if ledger.get("guest"):
        drafted = _draft_guest(ledger)
        ledger["roster"] = list(drafted.get("names") or []) if drafted.get("ok") else []
        ledger["check"] = {
            "pass": bool(drafted.get("ok")),
            "issues": list(drafted.get("hard") or []),
            "stall_count": int((ledger.get("check") or {}).get("stall_count") or 0),
            "satisfied": "",
            "answer": drafted.get("answer") or "",
            "cut": "guest",
        }
        ledger["progress"]["next"] = "check"
        return
    runner = lineup or _preview
    cut = "alternate" if int((ledger.get("check") or {}).get("stall_count") or 0) >= 1 else ""
    try:
        drafted = runner(_working(ledger), ledger.get("session_id") or "", list(ledger.get("target_types") or []), cut)
    except Exception as exc:
        logger.warning("配队未完成：%s", type(exc).__name__)
        drafted = {"ok": False, "names": [], "answer": "灯灯这会儿没接上话。", "hard": ["short"]}
    ledger["roster"] = list(drafted.get("names") or []) if drafted.get("ok") else []
    ledger["check"] = {
        "pass": bool(drafted.get("ok")),
        "issues": list(drafted.get("hard") or []),
        "stall_count": int((ledger.get("check") or {}).get("stall_count") or 0),
        "satisfied": "",
        "answer": drafted.get("answer") or "",
        "cut": cut or "first",
    }
    ledger["progress"]["next"] = "check"


def _check(ledger: dict) -> None:
    check = ledger.get("check") or {}
    issues = list(check.get("issues") or [])
    check["facets"] = {
        "倾斜": "tilt" not in issues,
        "属性": "uniform" not in issues,
        "输出面": "counter" not in issues,
        "蓄力": "on_write",
    }
    if check.get("pass") and len(ledger.get("roster") or []) == 6:
        if not ledger["progress"].get("hot_done"):
            ledger["gap"] = {"kind": "meta", "label": "热门"}
            ledger["roster"] = []
            ledger["plan_version"] = int(ledger.get("plan_version") or 1) + 1
            ledger["progress"]["instruction"] = "热门再走同一圈"
            ledger["progress"]["next"] = "need_both"
            ledger["check"] = check
            return
        check["satisfied"] = "满意"
        ledger["progress"]["satisfied"] = True
        ledger["check"] = check
        ledger["progress"]["next"] = "speak"
        return
    if "identity" in issues and not (check.get("answer") or "").strip():
        from agents.rag_agent import _target_label

        label = _target_label(_working(ledger)) or "这一处"
        _ask(ledger, "composition", label, f"灯灯还不知道{label}的组成和打法。跟灯灯说一下。")
        return
    stall = int(check.get("stall_count") or 0) + 1
    check["stall_count"] = stall
    check["satisfied"] = "不满意"
    check["pass"] = False
    ledger["progress"]["stall_count"] = stall
    ledger["progress"]["satisfied"] = False
    ledger["check"] = check
    ledger["pending_speech"] = check.get("answer") or "灯灯按现有伙伴排不出六只。"
    if stall >= 2:
        _say(ledger, ledger["pending_speech"], stop=True)
        return
    ledger["progress"]["next"] = "replan"


def _write(ledger: dict, warehouse) -> None:
    ledger["slots"]["web"] = "closed"
    text = _working(ledger)
    if _release_without_count(text):
        _ask(ledger, "count", "只数", "告诉灯灯改几只。")
        return
    runner = warehouse or _order
    try:
        result = runner(text, ledger.get("session_id") or "")
    except Exception as exc:
        logger.warning("仓库未完成：%s", type(exc).__name__)
        _say(ledger, "灯灯这会儿没接上话。", stop=True)
        return
    if _pause_for_confirm(ledger, result):
        return
    answer = (result or {}).get("answer") or ""
    ledger["write"]["tool"] = "warehouse"
    ledger["write"]["complete"] = bool((result or {}).get("ok"))
    ledger["write"]["pending_question"] = "" if result.get("ok") else answer
    if answer and not result.get("ok") and "几只" in answer:
        _ask(ledger, "count", "只数", answer)
        return
    ledger["pending_speech"] = answer
    ledger["progress"]["next"] = "speak"


def _speak(ledger: dict, save) -> None:
    """成文只读已经允许对玩家说的内容，不改计划和名单。开口前再跑一遍 HALT。"""
    if ledger["constraints"].get("intent") == "lineup" and ledger["check"].get("pass") and len(ledger.get("roster") or []) == 6:
        _deliver(ledger, save)
        return
    if (ledger.get("progress") or {}).get("hop_kind") == "chain":
        from agents.evidence_gate import critique_answer, halt_ready

        question = _asked(ledger)
        hops = (ledger.get("progress") or {}).get("hops") or []
        speech = ledger.get("pending_speech") or ledger.get("speech") or ""
        halt = halt_ready(question, hops, speech)
        critique = critique_answer(question, speech, hops)
        ledger.setdefault("progress", {})["halt"] = halt
        ledger["progress"]["critique"] = {
            "pass": critique.get("pass"),
            "issues": list(critique.get("issues") or []),
            "relation": critique.get("relation") or "",
        }
        if not halt.get("ok") or not critique.get("pass"):
            missing = halt.get("missing") or []
            label = (missing[0].get("label") if missing else "") or "这一处"
            _ask(ledger, "identity", label, halt.get("ask") or f"灯灯还缺{label}。跟灯灯说一下。")
            return
    _say(ledger, ledger.get("pending_speech") or ledger.get("speech") or "", stop=True)


def _request(ledger: dict, missing: str, label: str) -> None:
    ledger["requests"].append({
        "id": f"req-{len(ledger['requests']) + 1}",
        "missing": missing if missing in {"meta", "identity", "counter", "rule"} else "identity",
        "label": label,
    })


def _deliver(ledger: dict, save) -> None:
    names = list(ledger.get("roster") or [])
    guest = ledger.get("guest") or {}
    if guest:
        from agents.battle_orders import _save_with_guest

        companions = [name for name in names if name != guest.get("name")]
        try:
            sentence, ok, roster = _save_with_guest(
                _working(ledger),
                companions,
                guest,
                replace_id=ledger.get("replace_team_id") or None,
            )
        except Exception as exc:
            logger.warning("出场未写下：%s", type(exc).__name__)
            _say(ledger, "灯灯这会儿没接上话。", stop=True)
            return
        if _pause_for_confirm(ledger, {"roster": roster}):
            return
        ledger["write"]["complete"] = bool(ok)
        if not ok:
            _say(ledger, sentence or "灯灯这会儿没接上话。", stop=True)
            return
        _finish_roster(ledger, names, sentence, roster)
        return
    if len(names) != 6:
        _say(ledger, "仓库里的伙伴还凑不齐六只，灯灯先不记新的一套出场。", stop=True)
        return
    runner = save or _save
    try:
        sentence, ok, roster = runner(
            _working(ledger),
            names,
            ledger.get("session_id") or "",
            ledger.get("replace_team_id"),
        )
    except TypeError:
        sentence, ok, roster = runner(_working(ledger), names, ledger.get("session_id") or "")
    except Exception as exc:
        logger.warning("出场未写下：%s", type(exc).__name__)
        _say(ledger, "灯灯这会儿没接上话。", stop=True)
        return
    if _pause_for_confirm(ledger, {"roster": roster}):
        return
    ledger["write"]["complete"] = bool(ok)
    if not ok:
        _say(ledger, sentence or "灯灯按现有伙伴排不出六只。", stop=True)
        return
    _finish_roster(ledger, names, sentence, roster)


def _finish_roster(ledger: dict, names: list, sentence: str, roster: str) -> None:
    ledger["check"]["pass"] = True
    ledger["check"]["satisfied"] = "满意"
    why = _why(ledger, names)
    if why and roster and "选取的理由是" in roster:
        roster = roster.replace("选取的理由是", "选取的理由是" + why, 1)
    head = sentence
    cut = sentence.find("。")
    if cut > 0:
        head = sentence[:cut + 1]
    shown = head + "六只是" + "、".join(names) + "。" + why
    cite = _cite(ledger)
    if cite:
        shown += "\n" + cite
    found = __import__("re").search(r"第\s*(\d+)\s*套", sentence or "")
    if found:
        ledger["team_id"] = int(found.group(1))
    _say(ledger, shown, stop=True)
    ledger["roster_text"] = roster


def _remember(ledger: dict, learned: list) -> None:
    if learned:
        note_thought("灯灯记下你的规矩了")
        _say(ledger, "灯灯记下你的规矩了。", stop=True)
        return
    _say(ledger, "这句话对不上灯灯还缺的资料。", stop=True)


def _lookup(ledger, lookup, prepared, use_web: bool) -> dict:
    if lookup is not None:
        found = lookup(ledger.get("utterance") or "", use_web, ledger.get("session_id") or "")
        return found or {}
    from knowledge_search import run_knowledge_search

    def report(*_args):
        return None

    return run_knowledge_search(
        ledger.get("utterance") or "",
        report,
        use_web=use_web,
        session_id=ledger.get("session_id") or "",
        skip_intent=True,
        prepared=prepared,
        skip_learn=True,
    )


def _page_ok(title: str, url: str, text: str) -> bool:
    blob = f"{title} {url} {text}"
    if any(word in blob for word in _OFF_WORD):
        return False
    host = url.lower()
    return not any(name in host for name in _OFF_HOST)


def _why(ledger: dict, names: list) -> str:
    utterance = ledger.get("utterance") or ""
    bits = []
    matched = __import__("re").search(r"(?:以|用)\s*([^\s，。,、]{1,8}?)(?:作为|为)(?:核心|主力)", utterance)
    if matched:
        core = matched.group(1)
        from agents.battle_orders import _catalog

        if core not in names and core not in _catalog():
            bits.append(f"名录里没有叫{core}的精灵，所以这六只里没有它。")
        elif core not in names:
            bits.append(f"这一次没有把{core}放进六只。")
        else:
            bits.append(f"六只里留了{core}。")
    guest = (ledger.get("guest") or {}).get("name") or ""
    target = (ledger.get("constraints") or {}).get("target") or ""
    if guest and guest in names:
        if target and ledger.get("target_types"):
            bits.append(f"针对{target}，留下了能应对这些属性的伙伴。")
        elif target:
            bits.append(f"还没有对上{target}的组成，这六只不是按那一支的打法挑的。")
        if (ledger.get("constraints") or {}).get("warehouse_only", True):
            bits.append(f"{guest}按外面读到的资料入队，其余五只都在仓库里还有剩。")
        else:
            bits.append(f"{guest}按外面读到的资料入队，其余五只只要求名录里有，不扣仓库。")
        return "".join(bits)
    if target:
        if ledger.get("target_types"):
            bits.append(f"针对{target}，留下了能应对这些属性的伙伴。")
        else:
            bits.append(f"还没有对上{target}的组成，这六只不是按那一支的打法挑的。")
    if (ledger.get("constraints") or {}).get("warehouse_only", True):
        bits.append("这六只都在仓库里还有剩。")
    else:
        bits.append("这六只只要求名录里有，不扣仓库。")
    return "".join(bits)


def _cite(ledger: dict) -> str:
    marks = []
    for index, page in enumerate(ledger.get("web_sources") or [], 1):
        url = str(page.get("url") or "")
        if not url.startswith("http"):
            continue
        marks.append(f"[{index}]({url})")
        if len(marks) >= 3:
            break
    if not marks:
        return ""
    return "外面参考了" + " ".join(marks) + "。"


def _add_guess(ledger: dict, text: str, covers: str, grade: str) -> None:
    body = (text or "").strip()
    if not body:
        return
    ledger["guesses"].append({
        "id": f"guess-{len(ledger['guesses']) + 1}",
        "producer": "探查员",
        "authority": "web",
        "discardable": True,
        "grade": grade,
        "text": body,
        "covers": covers,
    })


def _web_outcome(web, query: str, sources: list = None) -> dict:
    from agents.thoughts import note_read
    from agents.web_read import read_web

    opener = None
    video_text = None
    if web is None:
        from web_search import read_page
        from agents.external_mcp import tools_live

        opener = read_page
        if tools_live():
            from agents.video_speech import speech_of
            video_text = speech_of
    outcome = read_web(query, search=web or _web_search, open_page=opener, video_text=video_text)
    covered = outcome.get("covered") or []
    text = (outcome.get("text") or "").strip()
    if outcome.get("fill") == "bridge" and outcome.get("bridge"):
        note_read(f"外面读到阵容桥：{outcome.get('bridge')}，再查成员")
        seen = set()
        for item in covered:
            title = item.get("title") or query or "这一页"
            url = item.get("url") or ""
            if url and url not in seen:
                seen.add(url)
                note_read(f"正在阅读{title}（{url}）")
                if sources is not None:
                    sources.append({"title": title, "url": url})
        return outcome
    if not covered and not text:
        if outcome.get("ambiguous"):
            note_read(f"外面读过，没对上{query or '这一处'}")
        else:
            note_read(f"外面没有翻到{query or '这一处'}")
        return outcome
    if not covered and text:
        note_read(f"外面读到和{query or '这一处'}有关的摘录")
        return outcome
    seen = set()
    for item in covered:
        title = item.get("title") or query or "这一页"
        url = item.get("url") or ""
        if url and url in seen:
            continue
        if url:
            seen.add(url)
            note_read(f"正在阅读{title}（{url}）")
            if sources is not None:
                sources.append({"title": title, "url": url})
        else:
            note_read(f"正在阅读{title}")
    return outcome


def _search(web, query: str, sources: list = None) -> str:
    return (_web_outcome(web, query, sources).get("text") or "")


def _gap_covered(ledger: dict, label: str) -> bool:
    if not label:
        return True
    for item in ledger.get("admitted") or []:
        if item.get("label") == label:
            return True
    for item in ledger.get("guesses") or []:
        if label in (item.get("text") or "") or item.get("covers") == label:
            return True
    return False


def _working(ledger: dict) -> str:
    base = ledger.get("utterance") or ""
    extra = "。".join(item.get("text") or "" for item in ledger.get("admitted") or [] if item.get("text"))
    if not extra:
        return base
    return base.rstrip("。") + "。" + extra


def _release_without_count(text: str) -> bool:
    from agents.battle_orders import _wants_release
    from agents.work_cycle import _COUNT

    return _wants_release(text or "") and not _COUNT.search(text or "")


def _ask(ledger: dict, kind: str, label: str, sentence: str) -> None:
    previous = ledger.get("gap") if isinstance(ledger.get("gap"), dict) else {}
    ledger["gap"] = {"kind": kind, "label": label}
    if previous.get("fact"):
        ledger["gap"]["fact"] = previous["fact"]
    ledger["write"]["pending_question"] = sentence
    _say(ledger, sentence, stop=False)
    ledger["progress"]["next"] = "need_ask"


def _say(ledger: dict, sentence: str, stop: bool) -> None:
    from agents.dengdeng_reply import reply_notice

    text = (sentence or "").strip()
    if stop and text and not ledger.get("speech_reviewed"):
        text = _review_before_release(ledger, text)
    if text:
        ledger["speech"] = reply_notice(text)["text"]
    ledger["progress"]["next"] = "stop" if stop else ledger["progress"]["next"]


def _review_before_release(ledger: dict, text: str) -> str:
    """交出去之前看这句话。改写只收措辞，名单仍以程序为准。"""
    from agents.speech_review import review_speech

    ledger["speech_reviewed"] = True
    from agents.react_stream import review_prompt, stream_prompt

    if not stream_prompt(review_prompt(_asked(ledger))):
        note_thought("灯灯在看这句话答没答上核心、顺不顺、有没有重复或矛盾、有没有不该出现的词")
    from agents.cycle_graph import current_reviewer

    reviewer = current_reviewer() or ledger.get("reviewer") or review_speech
    try:
        result = reviewer(
            ledger.get("utterance") or "",
            text,
            {
                "names": list(ledger.get("roster") or []),
                "keep": list((ledger.get("progress") or {}).get("keep_tokens") or []),
            },
        ) or {}
    except Exception as exc:
        logger.warning("成文审查未完成：%s", type(exc).__name__)
        note_thought("灯灯这会儿没看完这句话，先按原来的说")
        return text
    issues = [str(item) for item in (result.get("issues") or []) if str(item).strip()]
    chosen = str(result.get("text") or "").strip() or text
    ledger["speech_review"] = {"pass": bool(result.get("pass")), "issues": issues}
    if result.get("repaired") and chosen != text:
        note_thought("灯灯把这句话里没说稳的地方收掉了")
    if not result.get("pass"):
        note_thought(_review_gap(issues or ["core"]))
    elif not (result.get("repaired") and chosen != text):
        note_thought("灯灯看过这句话，可以告诉你")
    return chosen


def _review_gap(issues: list) -> str:
    labels = {
        "core": "还没答上你问的核心",
        "extra": "多答了没问的事",
        "fluency": "还不顺或不完整",
        "repeat": "有重复的话",
        "conflict": "前后有矛盾",
        "hallucination": "有对不上资料的话",
        "voice": "有不像灯灯的词",
    }
    shown = [labels[item] for item in issues if item in labels]
    if not shown:
        return "灯灯觉得这句话还不能就这样告诉你"
    return "灯灯觉得这句话" + "、".join(shown)


def _asks_hot(text: str) -> bool:
    from agents.rag_agent import _HOT

    return bool(_HOT.search(text or ""))


def _draft_guest(ledger: dict) -> dict:
    """名录外的主力占一位。其余五只按仓库或名录来排。"""
    from agents.battle_orders import _catalog
    from agents.rag_agent import _companions
    from pokemon_kb import load_rules, type_chart

    guest = ledger.get("guest") or {}
    name = guest.get("name") or "主力"
    if not load_rules():
        return {"ok": False, "names": [], "answer": "灯灯没有翻到相关信息。", "hard": ["rules"]}
    text = _working(ledger)
    if ledger["constraints"].get("warehouse_only", True):
        from agents.rag_agent import _pool

        pool = _pool(text)
    else:
        pool = list(_catalog())
    seated = _companions(
        guest,
        pool,
        _catalog(),
        type_chart(),
        list(ledger.get("target_types") or []),
        text,
    )
    companions = list(seated.get("names") or [])
    names = [name] + companions
    hard = [item for item in (seated.get("gaps") or []) if item in {"short", "tilt", "uniform"}]
    if hard or len(names) != 6:
        if ledger["constraints"].get("warehouse_only", True):
            answer = f"仓库里的伙伴还凑不齐五只陪{name}出场。"
        else:
            answer = f"名录里也凑不齐五只陪{name}出场。"
        return {"ok": False, "names": names, "answer": answer, "hard": hard or ["short"]}
    return {"ok": True, "names": names, "answer": "", "hard": []}


def _read_outside_ace(ledger: dict, web, name: str) -> tuple:
    """先翻图鉴同名页。没有这一页，再用这次联网读到的句子。"""
    from agents.thoughts import note_read
    from knowledge_search import _guest_ready, present_outside_sprite

    pages = []
    if web is None:
        from agents.chat_notebook import remember_page
        from knowledge_search import _wiki_lookup

        wiki = _wiki_lookup(name)
        extract = (wiki or {}).get("extract") or ""
        url = (wiki or {}).get("url") or ""
        title = (wiki or {}).get("title") or name
        if url:
            note_read(f"正在阅读{title}（{url}）")
            pages.append({"title": title, "url": url})
        ready = _guest_ready(name, extract) if extract else {}
        if ready:
            remember_page(ledger.get("session_id") or "", name, extract, pages)
            return ready, pages
    found = []
    blob = _search(web, name, found)
    pages.extend(found)
    if not blob:
        return {}, pages
    ready = _guest_ready(name, blob)
    if ready:
        return ready, pages
    card = blob if blob.startswith("精灵：") else present_outside_sprite(name, blob)
    return _guest_ready(name, card) or {}, pages


def _preview(question: str, session_id: str, target_types: list, cut: str = "") -> dict:
    from agents.rag_agent import preview_lineup

    return preview_lineup(question, session_id, target_types, cut)


def _order(question: str, session_id: str) -> dict:
    from agents.battle_orders import run_battle_order

    return run_battle_order(question, session_id=session_id)


def _save(question: str, names: list, session_id: str, replace_id: int = None):
    from agents.battle_orders import _save_team

    return _save_team(question, names=names, replace_id=replace_id or None, session_id=session_id)


def _web_search(query: str, limit: int = 10) -> dict:
    from web_search import search_web

    return search_web(query, limit)


def _tell(progress, sentence: str) -> None:
    if progress is None or not sentence:
        return
    progress("retrieve", sentence)


def _pause_for_confirm(ledger: dict, result: dict = None) -> bool:
    """改表已经寄存。停在这一轮，等玩家点头。不新增调度词。"""
    from agents.write_confirm import take

    pending = take()
    if not pending:
        return False
    roster = pending.get("roster") or (result or {}).get("roster") or ""
    if roster:
        ledger["roster_text"] = roster
    ledger["pending_write"] = {
        "token": pending.get("token") or "",
        "preview": pending.get("preview") or "",
        "label": pending.get("label") or "",
    }
    ledger["write"]["complete"] = False
    ledger["write"]["tool"] = ledger["write"].get("tool") or "warehouse"
    ledger["speech"] = pending.get("preview") or "灯灯等你点头。"
    ledger["progress"]["next"] = "hold"
    from agents.write_confirm import bind_thread

    bind_thread(pending.get("token") or "", (ledger.get("progress") or {}).get("thread_id") or "")
    return True


def _finished_ok(ledger: dict) -> bool:
    if ledger.get("pending_write"):
        return False
    if ledger["progress"].get("next") == "need_ask":
        return False
    intent = ledger["constraints"].get("intent") or ""
    if intent == "lineup":
        return bool((ledger.get("check") or {}).get("pass"))
    if intent == "order":
        return bool((ledger.get("write") or {}).get("complete"))
    if not intent:
        return False
    return bool(ledger.get("speech")) and ledger["progress"].get("next") == "stop"


def _pack(ledger: dict, ok: bool) -> dict:
    return {
        "order": {
            "answer": ledger.get("speech") or "",
            "roster": ledger.get("roster_text") or "",
            "ok": ok,
            "trial": ledger.get("trial"),
            "rounds": ledger.get("plan") or [],
            "web_sources": ledger.get("web_sources") or [],
            "pending_write": ledger.get("pending_write") or None,
        },
        "ledger": {
            "plan_version": ledger.get("plan_version"),
            "plan": ledger.get("plan") or [],
            "facts": ledger.get("facts") or [],
            "guesses": ledger.get("guesses") or [],
            "requests": ledger.get("requests") or [],
            "roster": ledger.get("roster") or [],
            "check": ledger.get("check") or {},
            "progress": ledger.get("progress") or {},
            "gap": ledger.get("gap"),
            "admitted": ledger.get("admitted") or [],
            "slots": ledger.get("slots") or {},
            "speech_review": ledger.get("speech_review") or {},
        },
    }
