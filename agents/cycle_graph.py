"""把监督者的调度词收成一张可循环的图。

节点是现有工人。边读账本上的下一个词。
本地和网页两槽并行，回来后用归约合成一份账本。
办事的六个词可以请模型改一次；核对、换删法、开口、停下仍由程序定。
不可行或正在重复的词再问一遍，仍不行就维持程序的词。
"""
import contextvars
import copy
import logging
import os
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)
_REVIEWER = contextvars.ContextVar("cycle_reviewer", default=None)


def current_reviewer():
    """这一轮的成文函数。不放进可保存的账本。"""
    return _REVIEWER.get()

_LOOKUP = {"need_local", "need_web", "need_both"}
_SWITCHABLE = _LOOKUP | {"need_write", "need_ask", "need_lineup", "surf_web", "surf_files", "coder"}
_WORDS = _SWITCHABLE | {"check", "replan", "speak", "stop", "hold"}
_SWITCH_ORDER = ("need_lineup", "need_both", "need_local", "need_web", "need_write", "need_ask")


def _patches(left, right):
    if right == "__clear__":
        return []
    if not right:
        return list(left or [])
    return list(left or []) + list(right)


_CHECKPOINTER = MemorySaver()


class GraphState(TypedDict):
    ledger: dict
    patches: Annotated[list, _patches]


def _on_chain(ledger: dict) -> bool:
    """多跳子问题进行中：外环不能改航道。"""
    return (ledger.get("progress") or {}).get("hop_kind") == "chain"


def choose_tool(ledger: dict, program_word: str, ask=None) -> str:
    """程序给出的词优先。办事的六个词可以改，否决后再问一次。"""
    word = program_word or ""
    progress = ledger.setdefault("progress", {})
    # 子问题链只由 hop_fact / next_fact 推进，不让 Magentic 改成配队或热门。
    if _on_chain(ledger):
        return word
    if word not in _SWITCHABLE or ask is None:
        return word
    progress["reject_reason"] = ""
    proposed = _consult(ledger, word, ask)
    if not proposed or proposed == word:
        return word
    reason = _block_reason(ledger, proposed)
    if not reason:
        progress["chosen_tool"] = proposed
        return proposed
    progress["rejected_tool"] = proposed
    progress["reject_reason"] = reason
    second = _consult(ledger, word, ask)
    if not second or second == word:
        return word
    again = _block_reason(ledger, second)
    if again:
        progress["rejected_tool"] = second
        progress["reject_reason"] = again
        return word
    progress["chosen_tool"] = second
    return second


def _consult(ledger: dict, program_word: str, ask) -> str:
    try:
        return str(ask(ledger, program_word) or "").strip()
    except Exception as exc:
        logger.warning("调度词未改：%s", type(exc).__name__)
        return ""


def _block_reason(ledger: dict, proposed: str) -> str:
    if proposed not in _SWITCHABLE:
        return "这个词不能换"
    if not feasible(ledger, proposed):
        return _fence_reason(ledger, proposed)
    if _repeats(ledger, proposed):
        return "这一格已经试过，还没有新的事实"
    return ""


def _has_question(ledger: dict) -> bool:
    gap = ledger.get("gap") or {}
    if not isinstance(gap, dict):
        gap = {}
    return bool(str(gap.get("label") or "").strip() or str(ledger.get("speech") or "").strip())


def _fence_reason(ledger: dict, word: str) -> str:
    intent = (ledger.get("constraints") or {}).get("intent") or ""
    if _on_chain(ledger) and word in {"need_lineup", "need_both", "need_write", "surf_web", "surf_files", "coder", "replan"}:
        return "多跳题先补当前子问题"
    if word == "need_ask" and not _has_question(ledger):
        return "还没有要问的那一处"
    if word == "need_web" and intent == "order":
        return "改仓库时不能上网"
    if word == "need_both" and intent != "lineup":
        return "只有配队才能两处一起查"
    if word == "need_lineup" and intent in {"search", "order", "remember", "battle", ""}:
        return "这句不用配队"
    if word == "need_write" and intent not in {"order", "lineup"}:
        return "这句不能改仓库"
    return "这个词现在不能用"


def feasible(ledger: dict, word: str) -> bool:
    """这个词在当前意图下能不能上场。"""
    intent = (ledger.get("constraints") or {}).get("intent") or ""
    if word not in _WORDS:
        return False
    if _on_chain(ledger) and word in {"need_lineup", "need_both", "need_write", "surf_web", "surf_files", "coder", "replan"}:
        return False
    if word in {"need_web", "surf_web"} and intent == "order":
        return False
    if word == "need_both" and intent != "lineup":
        return False
    if word == "need_lineup" and intent in {"search", "order", "remember", "battle", ""}:
        return False
    if word == "need_write" and intent not in {"order", "lineup"}:
        return False
    if word == "need_ask" and not _has_question(ledger):
        return False
    return True


def _gap_key(ledger: dict) -> tuple:
    gap = ledger.get("gap") or {}
    if not isinstance(gap, dict):
        return "", ""
    return gap.get("kind") or "", gap.get("label") or ""


def _slot_tried(ledger: dict, word: str) -> bool:
    tried = list((ledger.get("slots") or {}).get("tried") or [])
    if word == "need_local":
        return "local" in tried
    if word == "need_web":
        return any(str(item).startswith("web:") for item in tried)
    if word == "need_both":
        return "local" in tried and any(str(item).startswith("web:") for item in tried)
    return False


def _gap_covered(ledger: dict) -> bool:
    _kind, label = _gap_key(ledger)
    if not label:
        return False
    for item in ledger.get("facts") or []:
        covers = str(item.get("covers") or "")
        text = str(item.get("text") or "")
        if label == covers or label in text:
            return True
    return False


def _repeats(ledger: dict, word: str) -> bool:
    """同一个词、同一个缺口，格子已经试过，又没有盖住这格的新事实。"""
    if word not in {"need_local", "need_web", "need_both"}:
        return False
    if not _slot_tried(ledger, word):
        return False
    kind, label = _gap_key(ledger)
    opened = (ledger.get("progress") or {}).get("opened") or []
    seen = any(
        isinstance(item, dict) and item.get("word") == word and item.get("kind") == kind and item.get("label") == label
        for item in opened
    )
    return seen and not _gap_covered(ledger)


def _done(ledger: dict) -> bool:
    intent = (ledger.get("constraints") or {}).get("intent") or ""
    if intent == "lineup":
        check = ledger.get("check") or {}
        return bool(check.get("pass")) and len(ledger.get("roster") or []) == 6
    if intent == "order":
        return bool((ledger.get("write") or {}).get("complete"))
    slots = ledger.get("slots") or {}
    return slots.get("local") == "filled" and bool(ledger.get("pending_speech"))


def _moved(ledger: dict) -> bool:
    progress = ledger.get("progress") or {}
    if "seen_facts" not in progress:
        return False
    return (
        len(ledger.get("facts") or []) > int(progress.get("seen_facts") or 0)
        or len(ledger.get("roster") or []) != int(progress.get("seen_roster") or 0)
        or len(ledger.get("guesses") or []) > int(progress.get("seen_guesses") or 0)
    )


def _count_open(ledger: dict) -> str:
    if (ledger.get("constraints") or {}).get("intent") != "order":
        return ""
    from agents.supervisor import _release_without_count

    if _release_without_count(ledger.get("utterance") or ""):
        return "只数还空着。"
    return ""


def dispatch_brief(ledger: dict, program_word: str) -> str:
    """交给模型的现状。只读账本上已经有的格子。"""
    slots = ledger.get("slots") or {}
    gap_kind, gap_label = _gap_key(ledger)
    gap_text = gap_kind or "无"
    if gap_label:
        gap_text = f"{gap_text} {gap_label}"
    tried = "、".join(str(item) for item in (slots.get("tried") or [])) or "无"
    check = ledger.get("check") or {}
    progress = ledger.get("progress") or {}
    if _on_chain(ledger):
        hop = progress.get("hop_fact") or gap_label or "这一处"
        done = len(progress.get("hops") or [])
        return (
            f"多跳子问题进行中。当前只补：{hop}。"
            f"已完成 {done} 步。缺口：{gap_text}。"
            f"本地：{slots.get('local') or 'closed'}。网页：{slots.get('web') or 'closed'}。"
            f"已经试过：{tried}。"
            f"不要看网页闲话改航道。只能选 need_local、need_web、need_ask。"
            f"程序建议 {program_word}。"
        )
    parts = [
        f"原话：{(ledger.get('utterance') or '无')}。",
        f"意图：{((ledger.get('constraints') or {}).get('intent') or '无')}。",
        f"缺口：{gap_text}。",
        f"本地：{slots.get('local') or 'closed'}。网页：{slots.get('web') or 'closed'}。",
        f"已经试过：{tried}。",
        f"事实 {len(ledger.get('facts') or [])} 条。猜测 {len(ledger.get('guesses') or [])} 条。名单 {len(ledger.get('roster') or [])} 只。",
        f"核对：{'过了' if check.get('pass') else '还没过'}。",
        _count_open(ledger),
        f"做完了没有：{'做完了' if _done(ledger) else '还没做完'}。",
        f"是不是在重复：{'在重复' if _repeats(ledger, program_word) else '没有重复'}。",
        f"有没有新的事实或名单：{'有' if _moved(ledger) else '没有'}。",
        f"程序建议 {program_word}。",
    ]
    reason = progress.get("reject_reason") or ""
    if reason:
        parts.append(f"上一次选择不行：{reason}。")
    return "".join(part for part in parts if part)


def _parse_switch(body: str) -> str:
    found = []
    for name in _SWITCH_ORDER:
        index = body.find(name)
        if index >= 0:
            found.append((index, name))
    if not found:
        return ""
    found.sort()
    return found[0][1]


def ask_dispatch(ledger: dict, program_word: str) -> str:
    """有密钥时请模型在六个办事的词里选一个。失败就维持程序的词。"""
    if not (os.getenv("ZHIPU_API_KEY") or os.getenv("DEEPSEEK_API_KEY")):
        return program_word
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from llm_provider import get_team_invoke

        invoke = get_team_invoke(12)
        result = invoke([
            SystemMessage(content="只输出一个词：need_local、need_web、need_both、need_write、need_ask、need_lineup。不要解释。"),
            HumanMessage(content=dispatch_brief(ledger, program_word)),
        ])
        text = getattr(result, "content", result)
        if isinstance(text, list):
            text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in text
            )
        parsed = _parse_switch(str(text or ""))
        return parsed or program_word
    except Exception as exc:
        logger.warning("模型没改调度词：%s", type(exc).__name__)
    return program_word


def note_opening(ledger: dict, word: str) -> None:
    """记下这一步派出的词，供下一次判断有没有在重复。"""
    progress = ledger.setdefault("progress", {})
    progress["seen_facts"] = len(ledger.get("facts") or [])
    progress["seen_roster"] = len(ledger.get("roster") or [])
    progress["seen_guesses"] = len(ledger.get("guesses") or [])
    kind, label = _gap_key(ledger)
    opened = [item for item in (progress.get("opened") or []) if isinstance(item, dict)]
    opened.append({"word": word, "kind": kind, "label": label})
    progress["opened"] = opened[-8:]


def restore_previous(ledger: dict) -> bool:
    """回到这一步开始前的账本。评审函数留在原处。"""
    prior = list(ledger.get("prior") or [])
    if not prior:
        return False
    snap = prior[-1]
    reviewer = ledger.get("reviewer")
    ledger.clear()
    ledger.update(copy.deepcopy(snap))
    ledger["prior"] = prior[:-1]
    ledger["reviewer"] = reviewer
    ledger.setdefault("progress", {})["reverted"] = True
    return True


def reduce_branches(base: dict, local: dict, web: dict, hot_round: bool) -> dict:
    """权威事实取资料员，可作废证据取探查员，名单不从这两路产生。"""
    merged = base
    merged["facts"] = list(local.get("facts") or [])
    merged["requests"] = list(local.get("requests") or [])
    merged["guesses"] = list(web.get("guesses") or [])
    merged["web_sources"] = list(web.get("web_sources") or [])
    if web.get("guest"):
        merged["guest"] = web["guest"]
    slots = dict(merged.get("slots") or {})
    local_slots = local.get("slots") or {}
    web_slots = web.get("slots") or {}
    if local_slots.get("local"):
        slots["local"] = local_slots["local"]
    if web_slots.get("web"):
        slots["web"] = web_slots["web"]
    tried = []
    for item in list(local_slots.get("tried") or []) + list(web_slots.get("tried") or []):
        if item not in tried:
            tried.append(item)
    slots["tried"] = tried
    merged["slots"] = slots
    if hot_round:
        merged["gap"] = {"kind": "meta", "label": "热门"}
        if local.get("target_types"):
            merged["target_types"] = list(local["target_types"])
    else:
        if web.get("gap"):
            merged["gap"] = web["gap"]
        if web.get("target_types"):
            merged["target_types"] = list(web["target_types"])
        elif local.get("target_types"):
            merged["target_types"] = list(local["target_types"])
    if web.get("pending_speech"):
        merged["pending_speech"] = web["pending_speech"]
    web_queries = list(((web.get("progress") or {}).get("web_queries")) or [])
    if web_queries:
        progress = merged.setdefault("progress", {})
        kept = list(progress.get("web_queries") or [])
        for item in web_queries:
            if item not in kept:
                kept.append(item)
        progress["web_queries"] = kept
    merged["roster"] = list(base.get("roster") or [])
    return merged


def _plain(ledger: dict) -> dict:
    out = {}
    for key, value in ledger.items():
        if key in {"reviewer", "prior"}:
            continue
        try:
            out[key] = copy.deepcopy(value)
        except Exception:
            continue
    return out


def _remember(ledger: dict) -> None:
    prior = [item for item in (ledger.get("prior") or [])]
    snap = _plain(ledger)
    prior.append(snap)
    ledger["prior"] = prior[-6:]


def drive(
    ledger,
    session_id="",
    progress=None,
    cancel=None,
    prepared=None,
    web=None,
    lineup=None,
    warehouse=None,
    lookup=None,
    save=None,
    route_ask=None,
    resume=None,
    thread_id="",
) -> None:
    """按调度词跑完这一单。图的结果写回原来的账本。"""
    from agents import supervisor as sup

    deps = {
        "progress": progress,
        "cancel": cancel,
        "prepared": prepared,
        "web": web,
        "lineup": lineup,
        "warehouse": warehouse,
        "lookup": lookup,
        "save": save,
        "route_ask": route_ask,
    }
    budget = {"n": 0}

    def gate(state):
        book = state["ledger"]
        if deps["cancel"] and deps["cancel"]():
            book["progress"]["next"] = "stop"
            return {"ledger": book, "patches": "__clear__"}
        if int(book.get("plan_version") or 1) > sup._PLAN_LIMIT:
            sup._say(book, "灯灯按现有伙伴排不出六只。", stop=True)
            return {"ledger": book, "patches": "__clear__"}
        word = book["progress"].get("next") or ""
        if word in {"", "stop", "need_ask", "hold"}:
            return {"ledger": book}
        budget["n"] += 1
        if budget["n"] > sup._STEP_BUDGET:
            sup._say(book, "灯灯按现有伙伴排不出六只。", stop=True)
            return {"ledger": book, "patches": "__clear__"}
        from agents.react_stream import react_turn, streaming

        spoke = False
        proposed = ""
        if streaming():
            hop = ""
            if _on_chain(book):
                hop = (book.get("progress") or {}).get("hop_fact") or (book.get("gap") or {}).get("label") or ""
            spoke, proposed = react_turn(sup._asked(book), sup._seen_text(book), word, hop_fact=hop)
        ask = deps["route_ask"]
        if proposed and not _on_chain(book):
            ask = lambda _ledger, _program, chosen=proposed: chosen
        chosen = choose_tool(book, word, ask)
        if chosen != word:
            book["progress"]["next"] = chosen
            book["progress"]["revision_reason"] = "监督者改了下一步"
            word = chosen
        if word not in _WORDS:
            sup._say(book, "灯灯这会儿没听清你要做哪一件事。再说一次。", stop=True)
            return {"ledger": book, "patches": "__clear__"}
        note_opening(book, word)
        _remember(book)
        line = sup._step_line(book, word)
        if not spoke and not sup.stream_step(book, word):
            sup.note_thought(line)
        sup._mark(book, sup._assignee(word), sup._goal(word), "running")
        book["progress"]["next_assignee"] = sup._assignee(word)
        book["progress"]["instruction"] = sup._goal(word)
        sup._tell(deps["progress"], line)
        from agents.thoughts import note_thought

        if word and word != proposed:
            note_thought(f"Action: {word}")
        return {"ledger": book, "patches": "__clear__"}

    def route(state):
        word = (state["ledger"].get("progress") or {}).get("next") or ""
        if word in {"", "stop", "need_ask"}:
            return END
        if word == "hold":
            return "confirm"
        if word == "need_both":
            return [Send("local_branch", state), Send("web_branch", state)]
        return {
            "need_local": "local",
            "need_web": "web",
            "need_write": "write",
            "need_lineup": "lineup",
            "check": "check",
            "replan": "replan",
            "speak": "speak",
            "surf_web": "surf_web",
            "surf_files": "surf_files",
            "coder": "coder",
        }.get(word, "unknown")

    def local_branch(state):
        book = _plain(state["ledger"])
        if not book.get("gap"):
            book["gap"] = {"kind": "meta", "label": "热门"}
        status = sup._fill_local(book, deps["lookup"], deps["prepared"])
        return {"patches": [{"kind": "local", "ledger": book, "status": status}]}

    def web_branch(state):
        book = _plain(state["ledger"])
        hot = sup._both_hot(book)
        if hot:
            book["gap"] = {"kind": "meta", "label": "热门"}
        status = sup._fill_web(book, deps["web"], deps["lookup"])
        return {"patches": [{"kind": "web", "ledger": book, "status": status, "hot": hot}]}

    def join_both(state):
        book = state["ledger"]
        patches = list(state.get("patches") or [])
        local = next((item for item in patches if item.get("kind") == "local"), None)
        web_patch = next((item for item in patches if item.get("kind") == "web"), None)
        if local is None or web_patch is None:
            sup._say(book, "灯灯这会儿没把两处资料合上。", stop=True)
            return {"ledger": book, "patches": "__clear__"}
        hot = bool(web_patch.get("hot"))
        reduce_branches(book, local["ledger"], web_patch["ledger"], hot)
        sup._finish_both(book, local["status"], web_patch["status"], deps["lookup"])
        return {"ledger": book, "patches": "__clear__"}

    def _worker(state, word):
        book = state["ledger"]
        if word == "need_write":
            sup._write(book, deps["warehouse"])
        elif word == "need_local":
            sup._local(book, deps["lookup"], deps["prepared"])
        elif word == "need_web":
            sup._web(book, deps["web"], deps["lookup"])
        elif word == "surf_web":
            from agents.surf_agents import web_surfer

            web_surfer(book, deps["web"])
        elif word == "surf_files":
            from agents.surf_agents import file_surfer

            file_surfer(book)
        elif word == "coder":
            from agents.surf_agents import coder

            coder(book)
        elif word == "need_lineup":
            sup._lineup(book, deps["lineup"])
        elif word == "check":
            sup._check(book)
        elif word == "replan":
            book["plan_version"] = int(book.get("plan_version") or 1) + 1
            book["roster"] = []
            book["progress"]["revision_reason"] = "换一种删法"
            book["progress"]["next"] = "need_lineup"
            sup._mark(book, "监督者", "换一种删法后再选一次", "done")
        elif word == "speak":
            if _illegal_speak(book):
                restore_previous(book)
                sup._say(book, book.get("pending_speech") or "灯灯先不把这套交出去。", stop=True)
            else:
                sup._speak(book, deps["save"])
        else:
            sup._say(book, "灯灯这会儿没听清你要做哪一件事。再说一次。", stop=True)
        return {"ledger": book}

    def confirm(state):
        """同一次运行停在这里。点头或拒绝之后，从这一步接着往下走。"""
        from langgraph.types import interrupt

        book = state["ledger"]
        pending = book.get("pending_write") or {}
        approved = bool(interrupt(pending))
        token = pending.get("token") or ""
        if approved and token:
            from agents.write_confirm import commit

            try:
                done = commit(token)
            except Exception as exc:
                logger.warning("点头后没有记下：%s", type(exc).__name__)
                done = {}
            book["write"]["complete"] = True
            book["pending_write"] = None
            book["pending_speech"] = done.get("text") or book.get("speech") or "灯灯记下了。"
            if done.get("roster"):
                book["roster_text"] = done["roster"]
            book["progress"]["next"] = "speak"
        else:
            if token:
                from agents.write_confirm import reject

                try:
                    reject(token)
                except Exception:
                    pass
            book["pending_write"] = None
            book["write"]["complete"] = False
            book["speech"] = "灯灯没有记下。"
            book["progress"]["next"] = "stop"
        return {"ledger": book, "patches": "__clear__"}

    def _illegal_speak(book) -> bool:
        if (book.get("constraints") or {}).get("intent") != "lineup":
            return False
        check = book.get("check") or {}
        return not (check.get("pass") and len(book.get("roster") or []) == 6)

    graph = StateGraph(GraphState)
    graph.add_node("gate", gate)
    graph.add_node("local", lambda state: _worker(state, "need_local"))
    graph.add_node("web", lambda state: _worker(state, "need_web"))
    graph.add_node("write", lambda state: _worker(state, "need_write"))
    graph.add_node("lineup", lambda state: _worker(state, "need_lineup"))
    graph.add_node("check", lambda state: _worker(state, "check"))
    graph.add_node("replan", lambda state: _worker(state, "replan"))
    graph.add_node("speak", lambda state: _worker(state, "speak"))
    graph.add_node("surf_web", lambda state: _worker(state, "surf_web"))
    graph.add_node("surf_files", lambda state: _worker(state, "surf_files"))
    graph.add_node("coder", lambda state: _worker(state, "coder"))
    graph.add_node("confirm", confirm)
    graph.add_node("unknown", lambda state: _worker(state, ""))
    graph.add_node("local_branch", local_branch)
    graph.add_node("web_branch", web_branch)
    graph.add_node("join_both", join_both)
    graph.add_edge(START, "gate")
    graph.add_conditional_edges("gate", route)
    for name in ("local", "web", "write", "lineup", "check", "replan", "unknown", "join_both", "surf_web", "surf_files", "coder", "confirm"):
        graph.add_edge(name, "gate")
    graph.add_edge("local_branch", "join_both")
    graph.add_edge("web_branch", "join_both")
    graph.add_edge("speak", END)
    app = graph.compile(checkpointer=_CHECKPOINTER)
    held = ledger.setdefault("progress", {})
    if resume is None:
        held["thread_id"] = __import__("uuid").uuid4().hex
    run_thread = thread_id or held.get("thread_id") or session_id or "cycle"
    held["thread_id"] = run_thread
    reviewer = ledger.pop("reviewer", None)
    review_token = _REVIEWER.set(reviewer)
    config = {"configurable": {"thread_id": run_thread}, "recursion_limit": 80}
    try:
        if resume is None:
            result = app.invoke({"ledger": ledger, "patches": []}, config)
        else:
            from langgraph.types import Command

            result = app.invoke(Command(resume=bool(resume)), config)
    except Exception as exc:
        logger.warning("工作循环未走完：%s", type(exc).__name__)
        if not ledger.get("speech"):
            sup._say(ledger, "灯灯这会儿没接上话。", stop=True)
        return
    finally:
        _REVIEWER.reset(review_token)
        if reviewer is not None and "reviewer" not in ledger:
            ledger["reviewer"] = reviewer
    final = (result or {}).get("ledger") or ledger
    if final is not ledger:
        data = dict(final)
        ledger.clear()
        ledger.update(data)
        if reviewer is not None:
            ledger["reviewer"] = reviewer


def resume_held(thread_id: str, approved: bool) -> dict:
    """点头或拒绝之后，把停住的那一次计算接着跑完。"""
    book = {"progress": {"thread_id": thread_id}, "speech": "", "write": {}, "constraints": {}}
    drive(book, session_id=thread_id, resume=approved, thread_id=thread_id)
    return book
