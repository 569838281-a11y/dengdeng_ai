"""打印四句联网检索收回的原始结果和采用的段落。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 本脚本默认用 DeepSeek Search。若要改回 Tavily：PRINT_WEB_ENGINE=tavily python ...
os.environ["WEB_SEARCH_ENGINE"] = (os.environ.get("PRINT_WEB_ENGINE") or "deepseek").strip() or "deepseek"

from agents.web_read import read_web
import config

QUERIES = (
    "闪耀大赛出场率最高的精灵",
    "s2赛季的奇遇精灵",
    "s2赛季登场的传说精灵",
    "闪耀大赛最弱的精灵",
)
OUT = ROOT / "data" / "web_retrieve_print.txt"


def _block(query: str) -> str:
    # 只打印搜寻收回的条目；不逐页打开，避免 Fetch/站点超时拖死整轮。
    outcome = read_web(query, open_page=lambda *args, **kwargs: "")
    lines = [f"查询：{query}", f"采用：{outcome.get('text') or '（没有采用）'}", f"说明：{outcome.get('detail') or ''}"]
    for wave in outcome.get("retrieved") or []:
        rows = wave.get("results") or []
        lines.append(
            f"【{wave.get('wave')}】深度 {wave.get('depth')}｜{wave.get('reason')}｜{len(rows)} 条｜{wave.get('query')}"
        )
        if wave.get("detail"):
            lines.append(f"细节：{wave.get('detail')}")
        for index, item in enumerate(rows, 1):
            auth = item.get("authority")
            auth_bit = f"｜权威 {auth}" if auth is not None else ""
            lines.append(f"{index}. {item.get('title') or ''}")
            lines.append(f"   {item.get('url') or ''}")
            lines.append(f"   相关度 {item.get('score', '')}{auth_bit}｜日期 {item.get('published_date') or '无'}")
            lines.append(f"   {item.get('snippet') or ''}")
    covered = outcome.get("covered") or []
    lines.append(f"通过核对的段落：{len(covered)}")
    for item in covered:
        lines.append(f"- 分数 {item.get('score')}｜{item.get('title')}｜{item.get('url')}")
        lines.append(f"  {item.get('text') or ''}")
    return "\n".join(lines)


def main() -> None:
    engine = (config.WEB_SEARCH_ENGINE or "").strip() or "tavily"
    header = f"引擎：{engine}\n"
    parts = [_block(query) for query in QUERIES]
    text = header + "\n" + ("\n" + "=" * 40 + "\n\n").join(parts) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
