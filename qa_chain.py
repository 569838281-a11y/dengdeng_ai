from typing import List, Dict, Any
import sys

# 设置默认编码为UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain, create_history_aware_retriever
from langchain.chains.history_aware_retriever import create_history_aware_retriever
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

from config import (
    USE_RERANKER, 
    RERANKER_TOP_K, 
    RERANKER_THRESHOLD,
    BM25_WEIGHT,
    VECTOR_WEIGHT,
    USE_ADAPTIVE_RETRIEVAL,
    USE_QUERY_EXPANSION,
    RETRIEVAL_K,
    USE_PARENT_CHILD,
)
from llm_provider import get_llm_provider
from vectorstore import create_hybrid_retriever
from query_router import AdaptiveRetriever, STRATEGY_CONFIG

CONTEXTUALIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你的任务是把对话历史+用户最新问题压缩成一个独立的检索查询词。

严格规则：
1. 只输出查询词，不超过30个字
2. 禁止回答问题、禁止生成步骤、禁止给出建议
3. 如果用户最新问题已经是一个独立问题，直接输出它
4. 如果用户问题依赖历史上下文，融合历史信息后输出查询词

示例：
- 用户问"怎么做"而历史在讨论海运 → 输出"从事海运业务的条件和流程"
- 用户问"第三条税率"而历史在讨论增值税法 → 输出"增值税法第三条税率规定"
- 用户问"小微企业税收优惠" → 直接输出"小微企业税收优惠"（不需要改）"""),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])

QA_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是洛克宠物配队助手，只根据已知资料组队。

已知内容：
{context}

{memory_context}

回答要求：
1. 只根据「已知内容」里的对战细则、属性、特性、种族值、个体值、技能池、战斗风格和使用率配队。没有的事实不要编造。
2. 用户点名的主力必须留在队伍里。提到上个月就用上个月的使用率，否则用前一天的使用率。
3. 已知内容里每段开头有 [citation:X]。引用时沿用这个标签，并写出文件名。
4. 输出【队伍】和【理由】。队伍应有 6 只，招式必须来自该洛克宠物自己的技能池。
5. 资料不足时直接说明，不要用常识凑队伍。
6. 用户询问之前说过什么时，从对话历史和长期记忆中回答。"""),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])


def format_docs_with_citations(docs: List[Document]) -> str:
    """格式化文档，添加引用标签
    
    Args:
        docs: 文档列表
    
    Returns:
        格式化后的文档字符串，每个片段带有[citation:X]标签
    """
    formatted_docs = []
    
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source") or doc.metadata.get("file_name") or "未知来源"
        page = doc.metadata.get("page", "")
        content = doc.page_content.strip()
        
        # 添加引用标签
        page_info = f" (第{page}页)" if str(page) else ""
        citation_label = f"[citation:{i}]"
        
        formatted_doc = f"{citation_label} 文件: {source}{page_info}\n{content}\n"
        formatted_docs.append(formatted_doc)
    
    return "\n".join(formatted_docs)


def build_retriever(
    vectorstore: Chroma,
    documents: List[Document] = None,
    parent_documents: List[Document] = None,
    user_id: int = None,
    adaptive: bool = USE_ADAPTIVE_RETRIEVAL,
):
    """构建检索器（检索链与离线检索评测共用）。

    Args:
        vectorstore: 向量数据库（公用数据库）
        documents: 原始文档列表（用于 BM25 混合检索）
        parent_documents: 父块文档列表（用于 ParentChildRetriever）
        user_id: 用户ID（如果提供，将同时检索用户个人数据库）
        adaptive: 是否启用自适应检索（LLM 路由）。离线评测可传 False 以完全离线运行
    """
    llm_provider = get_llm_provider()

    if adaptive and documents:
        # 自适应检索模式：为每种策略创建不同的检索器
        retrievers = {}
        for strategy, cfg in STRATEGY_CONFIG.items():
            ret = create_hybrid_retriever(
                vectorstore,
                documents,
                k=int(cfg.get("retrieval_k") or RETRIEVAL_K),
                use_reranker=USE_RERANKER,
                reranker_top_k=RERANKER_TOP_K,
                reranker_threshold=RERANKER_THRESHOLD,
                bm25_weight=cfg["bm25_weight"],
                vector_weight=cfg["vector_weight"]
            )
            retrievers[strategy] = ret

        retriever = AdaptiveRetriever(
            retrievers=retrievers,
            llm=llm_provider,
            use_expansion=USE_QUERY_EXPANSION,
            default_strategy="混合"
        )
        print(f"✅ 自适应检索器已启用（{len(retrievers)} 种策略，查询扩展: {'开启' if USE_QUERY_EXPANSION else '关闭'}）")
    else:
        # 传统固定权重模式
        retriever = create_hybrid_retriever(
            vectorstore,
            documents,
            k=RETRIEVAL_K,
            use_reranker=USE_RERANKER,
            reranker_top_k=RERANKER_TOP_K,
            reranker_threshold=RERANKER_THRESHOLD,
            bm25_weight=BM25_WEIGHT,
            vector_weight=VECTOR_WEIGHT
        )
        print("⚠️ 使用固定权重混合检索（自适应检索已禁用）")

    # 如果启用父子块检索，用 ParentChildRetriever 包装基础检索器
    if USE_PARENT_CHILD and parent_documents:
        from vectorstore import ParentChildRetriever
        retriever = ParentChildRetriever(
            base_retriever=retriever,
            parent_documents=parent_documents
        )
        print(f"✅ 父子块检索已启用（子块检索 → 父块返回，{len(parent_documents)} 个父块）")

    # 如果有用户ID，创建联合检索器
    if user_id:
        try:
            from user_vectorstore import get_user_vectorstore
            from vectorstore import CombinedRetriever

            # 先查数据库，确认用户是否真的上传过文件
            has_db_uploads = False
            try:
                from database import get_user_documents
                uploads = get_user_documents(user_id)
                has_db_uploads = len(uploads) > 0
            except Exception:
                has_db_uploads = False

            if not has_db_uploads:
                print(f"⚠️ 用户 {user_id}: 数据库无上传记录，跳过个人数据库")
            else:
                try:
                    from api import get_embeddings
                    embeddings = get_embeddings()
                except ImportError:
                    from embeddings import create_embeddings
                    embeddings = create_embeddings()

                user_vectorstore = get_user_vectorstore(user_id, embeddings)
                if user_vectorstore:
                    user_retriever = create_hybrid_retriever(
                        user_vectorstore,
                        documents=None,
                        k=RETRIEVAL_K,
                        use_reranker=False
                    )
                    retriever = CombinedRetriever(
                        public_retriever=retriever,
                        user_retriever=user_retriever,
                        public_weight=0.7,
                        user_weight=0.15
                    )
                    print(f"✅ 用户 {user_id}: 联合检索器（公用+{len(uploads)}个个人文档）")
                else:
                    print(f"⚠️ 用户 {user_id}: 个人向量库为空，仅使用公用数据库")
        except Exception as e:
            print(f"⚠️ 创建用户检索器失败: {e}，仅使用公用数据库")

    return retriever


class CitationLabelRetriever(BaseRetriever):
    """给检索片段加上 [citation:N]，让模型引用的编号和片段一致。"""

    base_retriever: Any = Field(default=None)

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(self, query: str, *, run_manager=None, **kwargs) -> List[Document]:
        docs = self.base_retriever.invoke(query)
        labeled = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source") or doc.metadata.get("file_name") or "未知来源"
            page = doc.metadata.get("page", "")
            page_info = f" (第{page}页)" if str(page) else ""
            body = doc.page_content.strip()
            if body.startswith("[citation:"):
                body = body.split("\n", 1)[-1].strip()
            labeled.append(Document(
                page_content=f"[citation:{i}] 文件: {source}{page_info}\n{body}",
                metadata={**doc.metadata, "citation_id": i},
            ))
        return labeled

    async def _aget_relevant_documents(self, query: str, *, run_manager=None, **kwargs) -> List[Document]:
        return self._get_relevant_documents(query, run_manager=run_manager)


def build_conversational_qa_chain(vectorstore: Chroma, documents: List[Document] = None, user_id: int = None, parent_documents: List[Document] = None):
    """构建支持多轮对话的检索问答链
    
    Args:
        vectorstore: 向量数据库（公用数据库）
        documents: 原始文档列表（用于BM25混合检索）
        user_id: 用户ID（如果提供，将同时检索用户个人数据库）
        parent_documents: 父块文档列表（用于ParentChildRetriever）
    
    Returns:
        支持对话历史的检索问答链
    """
    # 策略模式：通过供应商抽象获取模型实例，主备降级与超时重试由 llm_provider 层负责
    llm_provider = get_llm_provider()
    llm = llm_provider.llm

    retriever = build_retriever(
        vectorstore,
        documents=documents,
        parent_documents=parent_documents,
        user_id=user_id,
        adaptive=USE_ADAPTIVE_RETRIEVAL,
    )
    retriever = CitationLabelRetriever(base_retriever=retriever)
    history_aware_retriever = create_history_aware_retriever(
        llm, retriever, CONTEXTUALIZE_PROMPT
    )
    
    question_answer_chain = create_stuff_documents_chain(llm, QA_PROMPT)
    
    conversational_chain = create_retrieval_chain(
        history_aware_retriever, question_answer_chain
    )
    
    return conversational_chain


def invoke_chain_with_memory(
    chain,
    question: str,
    chat_history: List,
    memory_context: str = ""
):
    """调用链并添加记忆上下文
    
    Args:
        chain: QA链
        question: 用户问题
        chat_history: 对话历史
        memory_context: 长期记忆上下文
    
    Returns:
        链的输出结果
    """
    formatted_history = format_chat_history(chat_history)
    
    return chain.invoke({
        "input": question,
        "chat_history": formatted_history,
        "memory_context": memory_context
    })


def build_retrieval_qa_chain(vectorstore: Chroma, documents: List[Document] = None, user_id: int = None, parent_documents: List[Document] = None):
    """构建检索问答链（兼容旧版本）
    
    Args:
        vectorstore: 向量数据库
        documents: 原始文档列表（用于BM25混合检索）
        user_id: 用户ID（可选）
        parent_documents: 父块文档列表（用于ParentChildRetriever）
    
    Returns:
        支持对话历史的检索问答链
    """
    return build_conversational_qa_chain(
        vectorstore, 
        documents=documents, 
        user_id=user_id,
        parent_documents=parent_documents
    )


def format_chat_history(history: List) -> List[BaseMessage]:
    """将对话历史格式化为LangChain消息列表
    
    Args:
        history: 支持多种格式：
            - Gradio 6.0 格式：[{"role": "user", "content": [{"text": "...", "type": "text"}]}]
            - 字典格式：[{"role": "user", "content": "..."}]
            - 元组格式：[("user message", "assistant message"), ...]
    
    Returns:
        [HumanMessage(...), AIMessage(...), ...]
    """
    messages = []
    
    for msg in history:
        if isinstance(msg, dict):
            role = msg.get("role", "")
            raw_content = msg.get("content", "")
            
            # Gradio 6.0 格式：content 是列表
            if isinstance(raw_content, list):
                text_parts = []
                for item in raw_content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                content = " ".join(text_parts)
            else:
                content = str(raw_content)
            
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        elif isinstance(msg, (list, tuple)) and len(msg) == 2:
            user_msg, assistant_msg = msg
            if user_msg:
                messages.append(HumanMessage(content=str(user_msg)))
            if assistant_msg:
                messages.append(AIMessage(content=str(assistant_msg)))
    
    return messages


def extract_sources(source_documents: List[Document], max_content_length: int = 300) -> List[str]:
    """从源文档中提取来源信息（包含文件名、页码和原文片段）。
    
    Args:
        source_documents: 检索到的文档列表
        max_content_length: 原文最大长度（字符数）
    
    Returns:
        格式化的来源列表：["文件名 (第X页)\n> 原文片段..."]
    """
    sources = []
    seen = set()
    
    for doc in source_documents:
        source_name = doc.metadata.get("source") or doc.metadata.get("file_name") or "未知来源"
        page = doc.metadata.get("page", "")
        
        content = doc.page_content.strip()
        if content.startswith("[citation:"):
            content = content.split("\n", 1)[-1].strip()
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."
        
        key = f"{source_name}_{page}"
        if key not in seen:
            seen.add(key)
            
            page_info = f" (第{page}页)" if str(page) else ""
            formatted_source = f"{source_name}{page_info}\n> {content}"
            sources.append(formatted_source)
    
    return sources


def extract_cited_sources(answer_text: str, source_documents: List[Document]) -> List[str]:
    """从LLM回答中提取实际引用的来源
    
    Args:
        answer_text: LLM的回答文本
        source_documents: 检索到的文档列表
    
    Returns:
        实际被引用的来源列表
    """
    import re
    
    # 从回答中提取引用的文件名
    cited_files = set()
    
    # 匹配模式1：原文参考来源：XXX.pdf
    pattern1 = r'原文参考来源[：:]\s*([^\n。,，]+?\.pdf)'
    matches1 = re.findall(pattern1, answer_text, re.IGNORECASE)
    cited_files.update(matches1)
    
    # 匹配模式2：参考来源：XXX.pdf
    pattern2 = r'参考来源[：:]\s*([^\n。,，]+?\.pdf)'
    matches2 = re.findall(pattern2, answer_text, re.IGNORECASE)
    cited_files.update(matches2)
    
    # 匹配模式3：来源：XXX.pdf
    pattern3 = r'来源[：:]\s*([^\n。,，]+?\.pdf)'
    matches3 = re.findall(pattern3, answer_text, re.IGNORECASE)
    cited_files.update(matches3)
    
    # 如果没有找到任何引用，返回前3个最相关的文档
    if not cited_files and source_documents:
        return extract_sources(source_documents[:3])
    
    # 从source_documents中找出被引用的文档
    sources = []
    seen = set()
    
    for doc in source_documents:
        source_name = doc.metadata.get("source") or doc.metadata.get("file_name") or "未知来源"
        
        # 检查这个文档是否被引用
        is_cited = False
        for cited_file in cited_files:
            # 模糊匹配：去掉.pdf后缀进行比较
            cited_base = cited_file.replace('.pdf', '').strip()
            source_base = source_name.replace('.pdf', '').strip()
            if cited_base in source_base or source_base in cited_base:
                is_cited = True
                break
        
        if is_cited and source_name not in seen:
            seen.add(source_name)
            page = doc.metadata.get("page", "")
            content = doc.page_content.strip()[:200]
            if len(content) == 200:
                content += "..."
            
            page_info = f" (第{page}页)" if str(page) else ""
            formatted_source = f"{source_name}{page_info}\n> {content}"
            sources.append(formatted_source)
    
    return sources