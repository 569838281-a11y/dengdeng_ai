"""进程内懒加载的灯灯 LoRA。只做给定上下文的成文，不选人、不算伤害。"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = Path(os.getenv("LORA_ADAPTER_DIR", ROOT / "data" / "lora" / "adapter"))
BASE_MODEL = os.getenv("LORA_BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")

_bundle = None
_error = None


def adapter_ready() -> bool:
    return (ADAPTER_DIR / "adapter_config.json").is_file()


def generate(messages: list) -> str:
    """do_sample=False，只解码新 token。加载失败时抛出，由上层回退。"""
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
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=dtype,
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base, ADAPTER_DIR)
    if torch.cuda.is_available():
        model = model.to("cuda")
    model.eval()
    logger.info("灯灯 LoRA 已加载：%s", ADAPTER_DIR)
    return model, tokenizer
