"""给一支队伍打 PPO 奖励分。

奖励来自知识库规则：人数、点名主力、技能池，以及和当前时间窗口高使用率队伍的重合度。
在线 PPO 需要本地策略模型。这里先对最近一次配队轨迹打分，不更新智谱接口模型。

    python train_ppo.py
"""
import json

from pokemon_kb import team_reward
from agents.pipeline import TRACE_DIR


def main() -> int:
    files = sorted(TRACE_DIR.glob("*.json")) if TRACE_DIR.exists() else []
    if not files:
        print("还没有配队轨迹。先在网页上配一次队。")
        return 1
    trace = json.loads(files[-1].read_text(encoding="utf-8"))
    reward = team_reward(trace.get("answer") or "", trace.get("question") or "")
    print(f"最近一次配队奖励：{reward}")
    print(files[-1])
    print("PPO 更新本地策略时，把 team_reward(队伍, 用户要求) 当作奖励。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
