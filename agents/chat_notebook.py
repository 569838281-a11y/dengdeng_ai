"""一段对话里的记事。只跟这次会话走，新开会话是空的。"""
import json
import re
import threading
import time
from pathlib import Path

from config import DATA_DIR, SESSION_TTL

_LOCK = threading.Lock()
_BOOKS: dict = {}
_PATH = Path(DATA_DIR) / "chat_notebooks.json"
_ITEMS = ("光合治愈", "愿力强化", "进化之力")
_TAGS = ("联防", "输出", "消强", "充能", "倾斜")
_ITEM_INTENT = re.compile(r"尽量|习惯|优先|偏好|更喜欢|都用|换成|换为|改成|作为战斗道具")
_TAG_INTENT = re.compile(r"更喜欢|习惯|偏好|优先|喜欢")
_COUNTER_INTENT = re.compile(r"习惯|加入|处理|对付|用来")
_BARE_LIKE = re.compile(r"最喜欢的精灵是|最爱的精灵是|喜欢的精灵是")
_TEAM_USE = re.compile(r"(?:以\s*)?([^\s，。,、！？]{1,12}?)(?:作为|为)(?:核心|主力)")
_TYPE_WORD = "普通|机械|草|火|水|光|地|冰|龙|电|毒|虫|武|翼|萌|幽|恶|幻"
_TYPE_NAMES = tuple(_TYPE_WORD.split("|"))
_TYPE_SAY = re.compile(
    rf"([\u4e00-\u9fffA-Za-z0-9（）()]{{1,16}}?)(?:是|为)({_TYPE_WORD})系"
)
_ATTR_SAY = re.compile(
    rf"([\u4e00-\u9fffA-Za-z0-9（）()]{{1,16}}?)的属性\s*(?:为|是|：|:)\s*[【\[]?({_TYPE_WORD})[】\]]?系?"
)
_FIELD = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9（）()]{1,16}?)的(首领化标签|首领化|标签)\s*(?:为|是|：|:)\s*"
    r"((?:[【\[][^】\]]{1,24}[】\]])|(?:[^\s，。,、；;]{1,8}))"
)
_NAME_TOKEN = r"[\u4e00-\u9fffA-Za-z0-9（）()]{2,16}"
_ALIAS_OF = re.compile(rf"({_NAME_TOKEN})的(?:名字|外号|代称|别称|别名)\s*(?:是|为|叫)\s*({_NAME_TOKEN})")
_ALIAS_IS = re.compile(rf"({_NAME_TOKEN})是({_NAME_TOKEN})的(?:外号|代称|别称|别名|名字)")
_ALIAS_CALL = re.compile(rf"把({_NAME_TOKEN})(?:叫做|称为|叫成)\s*({_NAME_TOKEN})")
_ALIAS_ALSO = re.compile(rf"({_NAME_TOKEN})(?:又叫|也叫|称作)\s*({_NAME_TOKEN})")
_ASK = (
    ("技能石", "技能石"),
    ("自带", "自带"),
    ("血脉", "血脉"),
    ("种族值", "种族值"),
    ("首领化", "首领化"),
    ("特性", "特性"),
    ("标签", "标签"),
    ("属性", "属性"),
    ("进化", "进化"),
    ("技能", "技能"),
)
_BOSS_CAN = re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()]{1,16})(?:可以|能够|能)首领化")
_YES = {"是", "可以", "能", "能够", "有"}
_NO = {"否", "不能", "不可以", "没有"}
# 满了才压。完整卡片少留几张，压过的只留一行摘要。
_MAX_PAGES = 6
_MAX_PAGE_CHARS = 900
_MAX_TOTAL = 4200
_MAX_USED = 6
_MAX_DIGESTS = 8
_KEEP_SKILLS = 8


def _blank() -> dict:
    return {
        "pages": {},
        "digests": [],
        "patches": {},
        "aliases": {},
        "lineups": [],
        "used": [],
        "item": "",
        "prefer": [],
        "counters": [],
        "turn": {},
        "ts": time.time(),
    }


def _prune_locked() -> None:
    now = time.time()
    stale = [sid for sid, book in _BOOKS.items() if now - float(book.get("ts") or 0) > SESSION_TTL]
    for sid in stale:
        _BOOKS.pop(sid, None)


def _load_locked() -> None:
    if _BOOKS or not _PATH.exists():
        return
    try:
        payload = json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(payload, dict):
        _BOOKS.update(payload)
    _prune_locked()


def _save_locked() -> None:
    _prune_locked()
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_BOOKS, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception:
        return


def _book(session_id: str) -> dict:
    sid = (session_id or "").strip()
    if not sid:
        return _blank()
    _load_locked()
    book = _BOOKS.get(sid)
    if not isinstance(book, dict):
        book = _blank()
        _BOOKS[sid] = book
    book.setdefault("pages", {})
    book.setdefault("digests", [])
    book.setdefault("patches", {})
    book.setdefault("aliases", {})
    book.setdefault("lineups", [])
    book.setdefault("used", [])
    book.setdefault("turn", {})
    book["ts"] = time.time()
    return book


def _noise(text: str) -> bool:
    body = re.sub(r"[\s，。！？、~～,.!?\-]", "", text or "")
    chars = [char for char in body if "\u4e00" <= char <= "\u9fff"]
    if len(chars) < 2:
        return True
    return len(set(chars)) <= 2


def _thin_name(name: str) -> bool:
    """整句闲聊才用上面的规则。两个不同字的精灵名要留下。"""
    chars = [char for char in (name or "") if "\u4e00" <= char <= "\u9fff" or char.isalnum()]
    if len(chars) < 2:
        return True
    return len(set(chars)) == 1


def _bare_favorite(text: str) -> bool:
    return bool(_BARE_LIKE.search(text or "")) and not re.search(r"主力|核心|配队|出场|队伍|首领化|标签", text or "")


def _field_value(label: str, raw: str) -> str:
    value = re.sub(r"[【】\[\]]", "", (raw or "").strip())
    if label == "属性":
        token = value.replace("系", "")
        return token if token in _TYPE_NAMES else ""
    if label == "首领化":
        if value in _YES:
            return "是"
        if value in _NO:
            return "否"
        return ""
    tags = []
    for part in re.split(r"[、，]", value):
        token = part.strip()
        if token in _TAGS and token not in tags:
            tags.append(token)
    return "、".join(tags)


def _line_value(text: str, label: str) -> str:
    matched = re.search(rf"^{re.escape(label)}：(.+)$", text or "", re.M)
    value = matched.group(1).strip() if matched else ""
    return "" if value in {"", "未提供"} else value


def _write_field(text: str, label: str, value: str) -> str:
    body = text or ""
    line = f"{label}：{value}"
    if re.search(rf"^{re.escape(label)}：", body, re.M):
        return re.sub(rf"^{re.escape(label)}：.+$", line, body, count=1, flags=re.M)
    if "证据：" in body:
        return body.replace("证据：", line + "\n证据：", 1)
    return (body.rstrip() + "\n" + line).strip()


def _fix_placeholder(text: str) -> str:
    boss = _line_value(text, "首领化")
    tags = _line_value(text, "标签")
    if boss and tags:
        phrase = "标签和首领化都记下了。"
    elif boss:
        phrase = "标签留空。"
    elif tags:
        phrase = "首领化留空。"
    else:
        phrase = "标签和首领化留空。"
    body = re.sub(r"标签和首领化(?:都记下了|留空)。|标签留空。|首领化留空。", "", text or "")
    if "证据：" in body:
        return re.sub(
            r"证据：[^\n]*",
            lambda match: match.group(0).rstrip("。") + "。" + phrase,
            body,
            count=1,
        )
    return body


def _apply_patches(book: dict, name: str, text: str) -> str:
    patch = (book.get("patches") or {}).get(name) or {}
    body = text or ""
    if not body and patch:
        body = f"精灵：{name}"
    for label, value in patch.items():
        if value:
            body = _write_field(body, label, value)
    if patch:
        body = _fix_placeholder(body)
    return body


def _types_from_text(text: str) -> list:
    raw = _line_value(text, "属性")
    if "不一致" in raw:
        return []
    return [part for part in re.split(r"[、，]", raw) if part]


def _types_for(book: dict, name: str) -> list:
    page = (book.get("pages") or {}).get(name) or {}
    found = _types_from_text(_apply_patches(book, name, page.get("text") or ""))
    if found:
        return found
    for item in book.get("digests") or []:
        if item.get("name") == name and item.get("types"):
            return list(item["types"])
    try:
        from pokemon_kb import _name_stem, load_pokemon

        stem = _name_stem(name)
        for mon in load_pokemon():
            if mon.get("name") == name or _name_stem(mon.get("name") or "") == stem:
                return list(mon.get("types") or [])
    except Exception:
        return []
    return []


def _remember_used(book: dict, name: str, types: list = None) -> bool:
    title = (name or "").strip()
    if not title or _thin_name(title):
        return False
    kinds = [kind for kind in (types or _types_for(book, title)) if kind]
    used = [item for item in (book.get("used") or []) if item.get("name") != title]
    used.append({"name": title, "types": kinds})
    book["used"] = used
    return True


def _skill_short(value: str) -> str:
    names = []
    for item in re.split(r"[、，]", value or ""):
        short = item.split("｜")[0].strip()
        if short and short not in names:
            names.append(short)
        if len(names) >= _KEEP_SKILLS:
            break
    if not names:
        return ""
    line = "、".join(names)
    return line + ("等" if value.count("、") >= _KEEP_SKILLS else "")


def _essential(name: str, text: str) -> str:
    """压卡片：只留属性和技能这些还能接着用的栏目，丢掉证据和未填的空行。"""
    body = (text or "").strip()
    if not body.startswith("精灵："):
        return body[:400]
    kept = [f"精灵：{name}"]
    for label in ("属性", "特性", "种族值", "标签", "首领化", "进化"):
        value = _line_value(body, label)
        if label in {"标签", "首领化"}:
            kept.append(f"{label}：{value or '未提供'}")
        elif value:
            kept.append(f"{label}：{value}")
    for label in ("自带", "技能石", "血脉"):
        short = _skill_short(_line_value(body, label))
        if short:
            kept.append(f"{label}：{short}")
    return "\n".join(kept)[:_MAX_PAGE_CHARS]


def _digest_of(name: str, text: str, types: list) -> dict:
    boss = _line_value(text, "首领化") or "未提供"
    tags = _line_value(text, "标签") or "未提供"
    kind = "、".join(types) if types else (_line_value(text, "属性") or "未提供")
    return {
        "name": name,
        "types": list(types or _types_from_text(text)),
        "line": f"{name}｜属性{kind}｜首领化{boss}｜标签{tags}",
    }


def _compact_locked(book: dict, protect: set = None) -> None:
    """记满时按这个顺序收。刚写上的和还在用的精灵不收成摘要。

    1. 完整卡片先收成栏目：留下属性、特性、种族值、进化、标签、首领化，技能每栏最多八个。证据和仍是未提供的空行去掉。
    2. 还是超了，就把最久没翻到、而且不是偏好精灵的卡片收成一行摘要。
    3. 同一种属性只留最后一次用过的那只。习惯和克制只留最近的几条。
    4. 摘要也多了，就丢掉最旧的一行。用户补过的栏目仍留在补丁里，下次读到会再贴回去。
    """
    keep = set(protect or [])
    for item in book.get("used") or []:
        if item.get("name"):
            keep.add(item["name"])
    pages = dict(book.get("pages") or {})
    for name in list(pages):
        page = dict(pages[name] or {})
        raw = _apply_patches(book, name, page.get("text") or "")
        page["text"] = raw if raw.startswith("精灵：") else raw[:400]
        page["sources"] = list(page.get("sources") or [])[:3]
        pages[name] = page
    total = sum(len((page.get("text") or "")) for page in pages.values())
    digests = list(book.get("digests") or [])
    if len(pages) > _MAX_PAGES or total > _MAX_TOTAL:
        for name in list(pages):
            page = pages[name]
            raw = page.get("text") or ""
            if raw.startswith("精灵："):
                page["text"] = _essential(name, raw)
        total = sum(len((page.get("text") or "")) for page in pages.values())
    if len(pages) > _MAX_PAGES or total > _MAX_TOTAL:
        for name in list(pages):
            if len(pages) <= _MAX_PAGES and total <= _MAX_TOTAL:
                break
            if name in keep:
                continue
            page = pages.pop(name)
            text = page.get("text") or ""
            digests.append(_digest_of(name, text, _types_from_text(text)))
            total -= len(text)
    book["pages"] = pages
    book["digests"] = digests[-_MAX_DIGESTS:]
    newest = {}
    for item in book.get("used") or []:
        title = item.get("name") or ""
        if not title:
            continue
        kinds = item.get("types") or []
        if not kinds:
            newest[title] = {"name": title, "types": []}
            continue
        for kind in kinds:
            previous = next((key for key, row in newest.items() if kind in (row.get("types") or [])), "")
            if previous and previous != title:
                newest[previous]["types"] = [item_kind for item_kind in newest[previous]["types"] if item_kind != kind]
                if not newest[previous]["types"]:
                    newest.pop(previous, None)
            row = newest.setdefault(title, {"name": title, "types": []})
            if kind not in row["types"]:
                row["types"].append(kind)
    book["used"] = list(newest.values())[-_MAX_USED:]
    book["prefer"] = list(book.get("prefer") or [])[-5:]
    book["counters"] = list(book.get("counters") or [])[-4:]
    patches = dict(book.get("patches") or {})
    if len(patches) > 12:
        protected = set(pages) | {item.get("name") for item in book["used"]}
        for name in list(patches):
            if len(patches) <= 12:
                break
            if name not in protected:
                patches.pop(name, None)
    book["patches"] = patches


def _clean_name(name: str) -> str:
    return re.sub(r"^(?:把|用|让)", "", (name or "").strip())


def stated_fields(question: str) -> list:
    """这一句里明确改过的栏目。只用于这段对话，不写名录。"""
    text = question or ""
    found = []
    for match in _TYPE_SAY.finditer(text):
        found.append((_clean_name(match.group(1)), "属性", match.group(2)))
    for match in _ATTR_SAY.finditer(text):
        found.append((_clean_name(match.group(1)), "属性", match.group(2)))
    for match in _FIELD.finditer(text):
        label = "首领化" if "首领化" in match.group(2) else "标签"
        value = _field_value(label, match.group(3))
        if value:
            found.append((_clean_name(match.group(1)), label, value))
    for match in _BOSS_CAN.finditer(text):
        found.append((_clean_name(match.group(1)), "首领化", "是"))
    return found


def _alias_token(raw: str) -> str:
    token = re.sub(r"^(?:把|用|让)", "", (raw or "").strip()).strip("，。！？、")
    if not token or re.search(r"什么|哪些|谁", token):
        return ""
    return token


def stated_aliases(question: str) -> list:
    """这一句里互换的叫法。左边是原来的名字，右边是可以换着叫的说法。"""
    text = question or ""
    found = []

    def add(canonical: str, alias: str) -> None:
        left = _alias_token(canonical)
        right = _alias_token(alias)
        if not left or not right or left == right or _thin_name(left) or _thin_name(right):
            return
        pair = (left, right)
        if pair not in found:
            found.append(pair)

    for match in _ALIAS_OF.finditer(text):
        add(match.group(1), match.group(2))
    for match in _ALIAS_IS.finditer(text):
        add(match.group(2), match.group(1))
    for match in _ALIAS_CALL.finditer(text):
        add(match.group(1), match.group(2))
    for match in _ALIAS_ALSO.finditer(text):
        add(match.group(1), match.group(2))
    return found


def _asks_question(text: str) -> bool:
    return bool(re.search(r"什么|哪些|吗|？|\?", text or ""))


def _is_alias_statement(question: str) -> bool:
    if _asks_question(question):
        return False
    return bool(stated_aliases(question))


def _is_correction(question: str) -> bool:
    if _asks_question(question):
        return False
    return bool(stated_fields(question))


def asked_labels(question: str) -> list:
    if _is_correction(question):
        return []
    found = []
    for needle, label in _ASK:
        if needle in (question or "") and label not in found:
            found.append(label)
    if "技能" in found and any(item in found for item in ("自带", "技能石", "血脉")):
        found = [item for item in found if item != "技能"]
    elif found == ["技能"]:
        found = ["自带", "技能石", "血脉"]
    return found


def _shown(label: str, value: str) -> str:
    if not value:
        return "未提供"
    if label != "属性":
        return value
    parts = []
    for part in re.split(r"[、，]", value):
        token = part.strip()
        if not token:
            continue
        parts.append(token if token.endswith("系") else token + "系")
    return "、".join(parts) or "未提供"


_VAGUE = re.compile(r"^(?:好的|随便|那支很强|很强|不错|不知道|嗯+|哦+)[。！]?$")


def remember_admitted(session_id: str, text: str, label: str) -> None:
    """玩家补上的一句。只记这段对话，来源标成玩家，不写进名录。"""
    body = (text or "").strip()
    title = (label or "").strip()
    if not (session_id or "").strip() or not body or not title:
        return
    with _LOCK:
        book = _book(session_id)
        rows = [dict(item) for item in (book.get("admitted") or []) if isinstance(item, dict)]
        rows.append({"text": body, "label": title, "source": "玩家"})
        book["admitted"] = rows[-12:]
        _save_locked()


def remember_turn(session_id: str, names: list, field: str, intent: str) -> None:
    """这一问在说哪些精灵、哪一栏。不记威力、倍率和种族值。"""
    sid = (session_id or "").strip()
    kept = []
    for name in names or []:
        title = str(name or "").strip()
        if title and title not in kept:
            kept.append(title)
    if not sid or not kept:
        return
    label = str(field or "").strip()
    if any(char.isdigit() for char in label):
        label = ""
    with _LOCK:
        book = _book(sid)
        book["turn"] = {
            "names": kept,
            "field": label,
            "intent": str(intent or "").strip(),
        }
        _save_locked()


def turn_of(session_id: str):
    sid = (session_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        turn = book.get("turn") if isinstance(book, dict) else None
        if not isinstance(turn, dict) or not turn.get("names"):
            return None
        return {
            "names": [str(name) for name in turn.get("names") or [] if str(name).strip()],
            "field": str(turn.get("field") or ""),
            "intent": str(turn.get("intent") or ""),
        }


def admitted_of(session_id: str) -> list:
    sid = (session_id or "").strip()
    if not sid:
        return []
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        return [dict(item) for item in (book.get("admitted") or []) if isinstance(item, dict)]


def learn(session_id: str, question: str) -> list:
    """从这一句里记下有用的补充和配队习惯。噪声、空泛的喜好不记。"""
    text = question or ""
    if not (session_id or "").strip() or _noise(text) or _VAGUE.match(text.strip()):
        return []
    added = []
    with _LOCK:
        book = _book(session_id)
        bare = _bare_favorite(text)
        if not bare and _ITEM_INTENT.search(text):
            for name in _ITEMS:
                if name in text and book.get("item") != name:
                    book["item"] = name
                    added.append(f"尽量使用{name}作为战斗道具")
                    break
        if not bare and _TAG_INTENT.search(text):
            prefer = list(book.get("prefer") or [])
            for tag in _TAGS:
                if tag in text and tag not in prefer:
                    prefer.append(tag)
                    added.append(f"更喜欢{tag}")
            book["prefer"] = prefer
        if not bare and "消强" in text and "强化" in text and _COUNTER_INTENT.search(text):
            counters = list(book.get("counters") or [])
            pair = {"bring": "消强", "against": "强化"}
            if pair not in counters:
                counters.append(pair)
                added.append("习惯加入消强来处理强化")
            book["counters"] = counters
        if not bare:
            matched = _TEAM_USE.search(text)
            used_name = re.sub(r"^(?:把|用|让)", "", matched.group(1).strip()) if matched else ""
            if used_name and _remember_used(book, used_name):
                added.append(f"喜欢使用{used_name}")
        patches = dict(book.get("patches") or {})
        pages = dict(book.get("pages") or {})
        found = stated_fields(text)
        for name, label, value in found:
            if not name or _thin_name(name):
                continue
            current = dict(patches.get(name) or {})
            if current.get(label) == value:
                continue
            current[label] = value
            patches[name] = current
            if name in pages:
                page = dict(pages[name])
                page["text"] = _apply_patches(book | {"patches": patches}, name, page.get("text") or "")
                pages.pop(name, None)
                pages[name] = page
            added.append(f"记下{name}的{label}")
        book["patches"] = patches
        book["pages"] = pages
        aliases = dict(book.get("aliases") or {})
        for canonical, alias in stated_aliases(text):
            if aliases.get(alias) == canonical:
                continue
            aliases[alias] = canonical
            added.append(f"记下{alias}就是{canonical}")
        book["aliases"] = aliases
        if added:
            _compact_locked(book, {name for name, _label, _value in found})
            _save_locked()
    return added


def note_used(session_id: str, name: str, types: list = None) -> None:
    """配队真的用上了某只，就记下「喜欢使用」。同一属性后来的覆盖先前的。"""
    title = (name or "").strip()
    if not (session_id or "").strip() or not title or _thin_name(title):
        return
    with _LOCK:
        book = _book(session_id)
        if not _remember_used(book, title, types):
            return
        _compact_locked(book, {title})
        _save_locked()


def favored_names(session_id: str) -> list:
    sid = (session_id or "").strip()
    if not sid:
        return []
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        return [item.get("name") for item in (book.get("used") or []) if item.get("name")]


def type_favorites(session_id: str) -> list:
    sid = (session_id or "").strip()
    if not sid:
        return []
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        return [dict(item) for item in (book.get("used") or []) if item.get("name") and item.get("types")]


def preference_clause(session_id: str) -> str:
    with _LOCK:
        book = _book(session_id) if (session_id or "").strip() else _blank()
        bits = []
        if book.get("item"):
            bits.append(f"尽量使用{book['item']}作为战斗道具")
        for tag in book.get("prefer") or []:
            bits.append(f"更喜欢{tag}")
        for pair in book.get("counters") or []:
            bits.append(f"习惯加入{pair['bring']}来处理{pair['against']}")
    return "。".join(bits)


def style_sentence(session_id: str) -> str:
    clause = preference_clause(session_id)
    if not clause:
        return ""
    return "灯灯记得你说过：" + clause + "。"


def remember_page(session_id: str, name: str, text: str, sources: list = None) -> None:
    title = (name or "").strip()
    body = (text or "").strip()
    if not (session_id or "").strip() or not title or not body:
        return
    with _LOCK:
        book = _book(session_id)
        pages = dict(book.get("pages") or {})
        pages.pop(title, None)
        pages[title] = {
            "text": _apply_patches(book, title, body)[:1800],
            "sources": list(sources or [])[:5],
        }
        book["pages"] = pages
        book["digests"] = [item for item in (book.get("digests") or []) if item.get("name") != title]
        _compact_locked(book, {title})
        _save_locked()


def recall_pages(session_id: str, question: str) -> list:
    text = question or ""
    sid = (session_id or "").strip()
    if not sid or not text.strip():
        return []
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        names = sorted(set(book.get("pages") or {}) | {item.get("name") for item in (book.get("digests") or [])}, key=len, reverse=True)
        found = []
        for name in names:
            if not name or name not in text:
                continue
            page = dict((book.get("pages") or {}).get(name) or {})
            if page:
                page["text"] = _apply_patches(book, name, page.get("text") or "")
            else:
                digest = next((item for item in (book.get("digests") or []) if item.get("name") == name), {})
                page = {"text": _apply_patches(book, name, digest.get("line") or ""), "sources": []}
            page["name"] = name
            found.append(page)
    return found


def session_type_overrides(session_id: str) -> dict:
    """这段对话里改过的属性。键是精灵名，值是属性列表。不读名录文件。"""
    sid = (session_id or "").strip()
    if not sid:
        return {}
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        found = {}
        for name, patch in (book.get("patches") or {}).items():
            kind = str((patch or {}).get("属性") or "").strip()
            if kind in _TYPE_NAMES:
                found[name] = [kind]
        return found


def catalog_for_session(catalog: dict, session_id: str) -> dict:
    """配队和克制用这份副本。只替换改过的属性，不改原名录。"""
    overrides = session_type_overrides(session_id)
    if not overrides or not catalog:
        return catalog
    copied = dict(catalog)
    for name, kinds in overrides.items():
        mon = copied.get(name)
        if not isinstance(mon, dict):
            continue
        twin = dict(mon)
        twin["types"] = list(kinds)
        copied[name] = twin
    return copied


def apply_page_text(session_id: str, name: str, text: str) -> str:
    sid = (session_id or "").strip()
    title = (name or "").strip()
    if not sid or not title:
        return text or ""
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        return _apply_patches(book, title, text or "")


_WHOLE = re.compile(r"具体信息|具体资料|全部信息|所有信息|全部资料|详细信息|都讲讲|的全部|介绍一下")


def alias_map(session_id: str) -> dict:
    """外号指向原来的名字。问句里两个叫法都能对上同一只。"""
    sid = (session_id or "").strip()
    if not sid:
        return {}
    with _LOCK:
        _load_locked()
        raw = dict((_BOOKS.get(sid) or {}).get("aliases") or {})

    def canonical(name: str, seen: set) -> str:
        nxt = raw.get(name)
        if not nxt or name in seen:
            return name
        return canonical(nxt, seen | {name})

    mapped = {}
    for alias, target in raw.items():
        left = str(alias or "").strip()
        right = canonical(str(target or "").strip(), set())
        if left and right and left != right:
            mapped[left] = right
    return mapped


def apply_aliases(session_id: str, text: str) -> str:
    body = text or ""
    for alias, canonical in sorted(alias_map(session_id).items(), key=lambda item: len(item[0]), reverse=True):
        body = body.replace(alias, canonical)
    return body


def alias_bridge(session_id: str, text: str) -> str:
    hits = []
    for alias, canonical in alias_map(session_id).items():
        if alias in (text or ""):
            hits.append(f"{alias}就是{canonical}")
    if not hits:
        return ""
    return "这段对话里，" + "，".join(hits) + "，两个叫法是同一只。"


def remember_lineup(session_id: str, members: list) -> None:
    """同一套出场只记成队友。不把他们写成对手或核心伙伴。"""
    names = []
    for name in members or []:
        title = str(name or "").strip()
        if title and title not in names and not _thin_name(title):
            names.append(title)
    if len(names) < 2 or not (session_id or "").strip():
        return
    with _LOCK:
        book = _book(session_id)
        rows = [list(item) for item in (book.get("lineups") or []) if isinstance(item, list)]
        if names not in rows:
            rows.append(names)
        book["lineups"] = rows[-8:]
        _save_locked()


def lineups_of(session_id: str) -> list:
    sid = (session_id or "").strip()
    if not sid:
        return []
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        return [list(item) for item in (book.get("lineups") or []) if isinstance(item, list) and len(item) >= 2]


def drop(session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        _load_locked()
        _BOOKS.pop(sid, None)
        _save_locked()
