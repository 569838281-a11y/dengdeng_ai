"""进程内懒加载的灯灯 LoRA。只做给定上下文的成文，不选人、不算伤害。"""
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = Path(os.getenv("LORA_ADAPTER_DIR", ROOT / "data" / "lora" / "adapter"))
BASE_MODEL = os.getenv("LORA_BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")

_bundle = None
_error = None


def adapter_ready() -> bool:
    return (ADAPTER_DIR / "adapter_config.json").is_file()


def _compress_fenced_messages(messages: list, question: str) -> list:
    from agents.kv_blocks import compress_fenced_context

    packed = []
    for message in messages or []:
        item = dict(message)
        content = str(item.get("content") or "")
        if item.get("role") == "user" and "<context>" in content:
            content, _stats = compress_fenced_context(content, question)
            item["content"] = content
        packed.append(item)
    return packed


def _attention_block_scores(model, tokenizer, question: str, blocks: list):
    """用最后一层「问句 token → 块内 token」的注意力给块打分。拿不到注意力时返回 None。"""
    import torch

    from agents.kv_blocks import mean_observation_attention

    segments = []
    cursor = 0
    spans = []
    for block in blocks:
        piece = block["text"] + "\n"
        segments.append(piece)
        spans.append((cursor, cursor + len(piece)))
        cursor += len(piece)
    full = "".join(segments) + (question or "。")
    encoded = tokenizer(
        full,
        return_offsets_mapping=True,
        return_tensors="pt",
        add_special_tokens=True,
    )
    offsets = encoded.pop("offset_mapping")[0].tolist()
    encoded = {key: value.to(model.device) for key, value in encoded.items()}
    with torch.no_grad():
        output = model(**encoded, output_attentions=True, use_cache=False)
    attentions = getattr(output, "attentions", None)
    if not attentions or attentions[-1] is None:
        return None
    layer = attentions[-1][0].mean(dim=0).tolist()

    def token_span(char_start: int, char_end: int):
        indexes = [
            index for index, (start, end) in enumerate(offsets)
            if end > start and not (start >= char_end or end <= char_start)
        ]
        if not indexes:
            return (0, 0)
        return (indexes[0], indexes[-1] + 1)

    block_spans = [token_span(start, end) for start, end in spans]
    obs_start, obs_end = token_span(cursor, len(full))
    if obs_end <= obs_start:
        return None
    return mean_observation_attention(layer, obs_start, obs_end, block_spans)


def _rescore_fenced(model, tokenizer, messages: list, question: str) -> list:
    from agents.kv_blocks import _FENCE, compress_fenced_context, evidence_block, select_blocks

    packed = []
    for message in messages or []:
        item = dict(message)
        content = str(item.get("content") or "")
        matched = _FENCE.search(content) if item.get("role") == "user" else None
        if not matched:
            packed.append(item)
            continue
        parts = [part.strip() for part in re.split(r"\n\s*\n", matched.group(1)) if part.strip()]
        blocks = [evidence_block(f"ctx-{index}", part) for index, part in enumerate(parts, 1)]
        query = (question or "").strip() or (content[:matched.start()] + content[matched.end():]).strip()
        scores = None
        try:
            scores = _attention_block_scores(model, tokenizer, query, blocks)
        except Exception as exc:
            logger.warning("块注意力打分失败，改用 Q·K：%s", exc)
        if not scores or len(scores) != len(blocks):
            content, _stats = compress_fenced_context(content, query)
        else:
            kept, _stats = select_blocks(
                query,
                blocks,
                window_turns=0,
                attention=lambda _question, _blocks: scores,
            )
            rendered = "\n\n".join(block["text"] for block in kept)
            content = content[:matched.start()] + "<context>\n" + rendered + "\n</context>" + content[matched.end():]
        item["content"] = content
        packed.append(item)
    return packed


def generate(messages: list, question: str = "") -> str:
    """do_sample=False，只解码新 token。加载失败时抛出，由上层回退。

    用户消息里的 <context> 先按块压缩再送进模型。云端 teacher 不走这里。
    """
    global _bundle, _error
    if _error is not None:
        raise RuntimeError(_error)
    if _bundle is None:
        if not adapter_ready():
            _error = f"找不到灯灯适配器：{ADAPTER_DIR / 'adapter_config.json'}"
            raise RuntimeError(_error)
        try:
            _bundle = _load()
        except Exception as exc:
            _error = f"{type(exc).__name__}: {exc}"
            raise
    model, tokenizer = _bundle
    if os.getenv("SNAPKV_ATTENTION") == "1":
        messages = _rescore_fenced(model, tokenizer, messages, question)
    else:
        messages = _compress_fenced_messages(messages, question)
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    encoded = tokenizer(prompt, return_tensors="pt")
    encoded = {key: value.to(model.device) for key, value in encoded.items()}
    input_len = encoded["input_ids"].shape[-1]
    output = model.generate(
        **encoded,
        max_new_tokens=512,
        do_sample=False,
    )
    new_tokens = output[0][input_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def _load():
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(ADAPTER_DIR, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    kwargs = {"torch_dtype": dtype, "trust_remote_code": True}
    if os.getenv("SNAPKV_ATTENTION") == "1":
        kwargs["attn_implementation"] = "eager"
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, **kwargs)
    model = PeftModel.from_pretrained(base, ADAPTER_DIR)
    if torch.cuda.is_available():
        model = model.to("cuda")
    model.eval()
    logger.info("灯灯 LoRA 已加载：%s", ADAPTER_DIR)
    return model, tokenizer
