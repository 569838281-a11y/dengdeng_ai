"""把用户修正和完美配对收成 DPO 训练集。

智谱接口没有可更新的权重。DPO 训练的是本地开源模型，样本在 data/preferences/dpo.jsonl。

    python train_dpo.py
"""
from pokemon_kb import DPO_PATH, rebuild_preference_dataset


def main() -> int:
    count = rebuild_preference_dataset()
    print(f"DPO 偏好对：{count} 条")
    print(DPO_PATH)
    if not count:
        print("还没有可对比的样本。请在网页上拒绝一支队伍并写下更想要的成员，或让模型回答与 knowledge/gold_teams.jsonl 不同的配队要求。")
        return 1
    print("有偏好对之后，用本地模型做 DPO。不要对智谱 API 模型调用训练。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
