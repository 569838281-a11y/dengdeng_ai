"""原型问答循环：长期记忆、把追问收成独立查询、中文分词检索。

向量库没有就绪时，仍用 bm25_chinese 把召回做完。
放生、删套、换招和查看仓库保持原句，避免改写出原句里没有的数量。
"""
import logging
import re
import threading

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_bm25 = None
_COUNT = re.compile(r"[一二三四五六七八九十两几\d]+\s*只")


def _user_number(user_id):
    try:
        number = int(user_id)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _counts_match(original: str, rewritten: str) -> bool:
    return _COUNT.findall(original or "") == _COUNT.findall(rewritten or "")


def bm25_retriever():
    """名录和规则上的中文 BM25。不加载嵌入模型。"""
    global _bm25
    with _LOCK:
        if _bm25 is None:
            from bm25_chinese import ChineseBM25Retriever
            from knowledge_search import knowledge_documents

            _bm25 = ChineseBM25Retriever(knowledge_documents(), k=5)
        return _bm25


def bm25_hits(query: str) -> list:
    text = (query or "").strip()
    if not text:
        return []
    retriever = bm25_retriever()
    try:
        docs = retriever.invoke(text)
    except Exception:
        docs = retriever._get_relevant_documents(text)
    hits = []
    for doc in docs or []:
        source = str((doc.metadata or {}).get("source") or "").replace("\\", "/")
        body = (doc.page_content or "").strip()
        if not body:
            continue
        hits.append({
            "title": str((doc.metadata or {}).get("section") or ""),
            "source": source,
            "kind": "bm25",
            "text": body[:1800],
            "photo_name": "",
        })
    return hits


def material_useful(hits: list) -> bool:
    """这一处有没有能继续用的正文。空标题和空摘要不算。"""
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        body = hit.get("text") or hit.get("snippet") or ""
        if str(body).strip():
            return True
    return False


def context_blocks(prepared: dict) -> list:
    from agents.kv_blocks import make_block

    blocks = []
    memory = (prepared or {}).get("memory") or ""
    if memory.strip():
        blocks.append(make_block("mem-turn", "长期记忆", memory.strip(), importance=0.8))
    for index, hit in enumerate((prepared or {}).get("hits") or [], 1):
        body = (hit.get("text") or "").strip()
        if not body:
            continue
        blocks.append(make_block(
            f"bm25-{index}",
            "检索",
            body[:500],
            entities=[hit.get("title") or ""],
            importance=0.7,
        ))
    return blocks


def prepare_turn(question: str, history=None, user_id="", invoke=None, anchor: str = "") -> dict:
    """记忆、改写、分词召回。模型没改成时查询仍是原句。改写丢掉锚定时回到程序接好的句子。"""
    text = (question or "").strip()
    steps = []
    memory = ""
    number = _user_number(user_id)
    if number is not None:
        try:
            from memory_manager import memory_manager

            memory = memory_manager.build_memory_context(number, text, history or []) or ""
            steps.append("memory")
        except Exception as exc:
            logger.warning("长期记忆未拼上：%s", type(exc).__name__)
    from agents.follow_agent import rewrite_followup

    followed = rewrite_followup(text, history, invoke)
    query = followed["query"] or text
    if anchor and anchor not in query:
        query = text
        steps.append("anchor")
    else:
        steps.append("keep" if followed["kept"] else "rewrite")
    hits = []
    try:
        hits = bm25_hits(query)
        steps.append("bm25" if hits else "bm25-empty")
    except Exception as exc:
        logger.warning("中文分词检索未完成：%s", type(exc).__name__)
        steps.append("bm25-empty")
    return {
        "query": query or text,
        "memory": memory,
        "hits": hits,
        "steps": steps,
    }
