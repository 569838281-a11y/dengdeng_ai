"""分工智能体，以及把撰写技能蒸馏到 LoRA 模型的工具。"""

__all__ = ["run_collaborative_agents"]


def __getattr__(name):
    if name == "run_collaborative_agents":
        from agents.pipeline import run_collaborative_agents
        return run_collaborative_agents
    raise AttributeError(name)
