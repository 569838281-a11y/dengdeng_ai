"""把灯灯 teacher 成文蒸馏成 Qwen2.5-1.5B-Instruct 的 LoRA。

只学习「给定资料 → 灯灯口吻」。不选人、不算伤害、不背图鉴。
默认 3 个 epoch，8GB 显存用 fp16、batch 1、梯度累积 8、梯度检查点、max_length 1536。

示例：
    python train_lora.py
    python train_lora.py --max-length 1280
"""
import argparse
import json
import math
import os
from pathlib import Path


def _load_examples(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _mask_labels(tokenizer, messages, max_length: int):
    prompt = tokenizer.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True
    )
    full = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full, add_special_tokens=False, truncation=True, max_length=max_length)
    input_ids = full_ids["input_ids"]
    labels = list(input_ids)
    prompt_len = min(len(prompt_ids), len(labels))
    for index in range(prompt_len):
        labels[index] = -100
    if all(label == -100 for label in labels):
        return None
    return {"input_ids": input_ids, "attention_mask": full_ids["attention_mask"], "labels": labels}


def main() -> int:
    parser = argparse.ArgumentParser(description="把灯灯成文蒸馏为 1.5B LoRA")
    parser.add_argument("--data", default="data/lora/train.jsonl")
    parser.add_argument("--base", default=os.getenv("LORA_BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"))
    parser.add_argument("--output", default="data/lora/adapter")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=0, help="0 表示按 epoch 训完，不要用很小的步数当正式结果")
    parser.add_argument("--max-length", type=int, default=1536)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--grad-accum", type=int, default=8)
    args = parser.parse_args()
    if "7B" in args.base or "7b" in args.base:
        print("只训练 Qwen2.5-1.5B-Instruct，不下 7B。")
        return 1

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"还没有灯灯训练集：{data_path}")
        print("先运行：python -m agents.lora_collect")
        return 1

    examples = [row for row in _load_examples(data_path) if row.get("messages")]
    if not examples:
        print("训练集是空的。")
        return 1

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    tokenizer = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device != "cuda":
        print("当前没有 CUDA。CPU 只适合冒烟，正式评测数字必须在 GPU 上重跑。")
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        trust_remote_code=True,
        torch_dtype=dtype,
    )
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "v_proj"],
    ))
    if device == "cuda":
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()

    class VoiceDataset(torch.utils.data.Dataset):
        def __init__(self, rows):
            self.rows = []
            for row in rows:
                item = _mask_labels(tokenizer, row["messages"], args.max_length)
                if item is not None:
                    self.rows.append(item)

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, index):
            return self.rows[index]

    dataset = VoiceDataset(examples)
    if not dataset:
        print("样本在截断后没有可学习的回答，请加大 --max-length。")
        return 1
    steps_per_epoch = max(1, math.ceil(len(dataset) / args.grad_accum))
    total_steps = args.max_steps if args.max_steps > 0 else steps_per_epoch * args.epochs
    print(
        f"样本 {len(dataset)}，max_length {args.max_length}，"
        f"累积 {args.grad_accum}，计划优化步数 {total_steps}，设备 {device}"
    )

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=str(output_dir / "checkpoints"),
            per_device_train_batch_size=1,
            gradient_accumulation_steps=args.grad_accum,
            learning_rate=args.learning_rate,
            max_steps=total_steps,
            logging_steps=5,
            save_strategy="no",
            report_to=[],
            fp16=device == "cuda",
            gradient_checkpointing=device == "cuda",
            dataloader_pin_memory=device == "cuda",
        ),
        train_dataset=dataset,
        data_collator=lambda features: tokenizer.pad(
            {"input_ids": [feature["input_ids"] for feature in features]},
            padding=True,
            return_tensors="pt",
        ) | {
            "labels": torch.nn.utils.rnn.pad_sequence(
                [torch.tensor(feature["labels"]) for feature in features],
                batch_first=True,
                padding_value=-100,
            )
        },
    )
    trainer.train()
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"LoRA 适配器已写入 {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
