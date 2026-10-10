"""加载 LoRA 适配器，抽出撰写员技能并复现回答。

检索仍调用知识库。这个脚本替代的是撰写员和核对员那两次大模型调用。

    python lora_reproducer.py --question "你的问题"
"""
import argparse
import os
from pathlib import Path

from agents.pipeline import snippets_from_docs
from agents.skill_distill import build_user_message
from agents.skill_text import load_skill


def reproduce(question: str, retriever, adapter_dir: str, base_model: str) -> str:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    adapter = Path(adapter_dir)
    if not (adapter / "adapter_config.json").exists():
        raise FileNotFoundError(
            f"还没有 LoRA 适配器：{adapter}。先导出轨迹再运行 python train_lora.py"
        )

    skill_text = load_skill("writer")
    docs = retriever.invoke(question)
    snippets = snippets_from_docs(docs or [])
    messages = [
        {
            "role": "system",
            "content": "你是经过技能蒸馏的本地模型。先抽出给定智能体技能的步骤，再只根据检索片段复现该技能的任务。",
        },
        {"role": "user", "content": build_user_message(skill_text, question, snippets)},
    ]

    tokenizer = AutoTokenizer.from_pretrained(adapter, trust_remote_code=True)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    base = AutoModelForCausalLM.from_pretrained(base_model, trust_remote_code=True, torch_dtype=dtype)
    model = PeftModel.from_pretrained(base, adapter)
    model.eval()
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt")
    if torch.cuda.is_available():
        model = model.to("cuda")
        inputs = {key: value.to("cuda") for key, value in inputs.items()}
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=512, do_sample=False)
    new_tokens = output[0][inputs["input_ids"].shape[-1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="用 LoRA 模型复现撰写员技能")
    parser.add_argument("--question", required=True)
    parser.add_argument("--adapter", default="data/lora/adapter")
    parser.add_argument("--base", default=os.getenv("LORA_BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"))
    args = parser.parse_args()

    from vectorstore import build_or_load_vectorstore, read_manifest
    from qa_chain import build_retriever
    from config import DATA_DIR, PERSIST_DIRECTORY
    from cache_utils import load_cache_with_meta

    vectorstore = build_or_load_vectorstore([])
    manifest = read_manifest(PERSIST_DIRECTORY)
    documents = load_cache_with_meta(Path(DATA_DIR) / "_documents_cache.pkl", manifest)
    parents = load_cache_with_meta(Path(DATA_DIR) / "_parent_documents_cache.pkl", manifest)
    retriever = build_retriever(
        vectorstore,
        documents=documents,
        parent_documents=parents,
        adaptive=False,
    )
    print(reproduce(args.question, retriever, args.adapter, args.base))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
