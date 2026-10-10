"""把新手复现指南.md 转成可打印 A4 PDF。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
MD_PATH = ROOT / "新手复现指南.md"
HTML_PATH = ROOT / "新手复现指南.print.html"
PDF_PATH = ROOT / "新手复现指南.pdf"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PUPPETEER = ROOT / "_print_pdf.mjs"

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: #1f2933;
  max-width: 180mm;
  margin: 0 auto;
}
h1 { font-size: 20pt; margin: 0 0 12pt; color: #14532d; page-break-after: avoid; }
h2 {
  font-size: 14pt;
  margin: 18pt 0 8pt;
  padding-bottom: 4pt;
  border-bottom: 1.5pt solid #2f9b64;
  color: #166534;
  page-break-after: avoid;
}
h3 { font-size: 12pt; margin: 14pt 0 6pt; color: #1d4d3a; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #166534; text-decoration: none; }
code {
  font-family: Consolas, "Sarasa Mono SC", "Microsoft YaHei", monospace;
  font-size: 9pt;
  background: #f3f7f2;
  padding: 0 3px;
  border-radius: 3px;
}
pre {
  background: #f6f8f6;
  border: 0.6pt solid #d7eadf;
  border-radius: 6px;
  padding: 8pt 10pt;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 8.5pt;
  page-break-inside: avoid;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 8.8pt;
  margin: 8pt 0 12pt;
  page-break-inside: avoid;
}
th, td {
  border: 0.6pt solid #c9ddd0;
  padding: 4pt 6pt;
  vertical-align: top;
  text-align: left;
}
th { background: #e8f6ea; color: #14532d; }
tr:nth-child(even) td { background: #fbfefb; }
hr { border: none; border-top: 0.6pt solid #d7eadf; margin: 16pt 0; }
.cover {
  text-align: center;
  margin: 8pt 0 20pt;
  padding: 16pt 10pt;
  background: #f4fbf6;
  border: 1pt solid #cfe8d6;
  border-radius: 10px;
}
.cover .sub { color: #4b6458; font-size: 10pt; }
.mermaid { text-align: center; margin: 8pt 0 14pt; page-break-inside: avoid; }
.mermaid svg { max-width: 100%; height: auto; }
"""

HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>新手复现指南</title>
<style>{css}</style>
</head>
<body>
<div class="cover">
  <h1 style="border:none;margin:0 0 6pt;">洛克王国智能助手</h1>
  <div class="sub">新手复现指南 · 可打印版 · A4</div>
</div>
{body}
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({{
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "loose",
    flowchart: {{ htmlLabels: true, useMaxWidth: true, nodeSpacing: 24, rankSpacing: 28 }}
  }});
  await mermaid.run({{ querySelector: ".mermaid" }});
  document.body.dataset.ready = "1";
</script>
</body>
</html>
"""


def md_to_html(text: str) -> str:
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br", "toc"],
        extension_configs={"toc": {"permalink": False}},
    )
    html = re.sub(
        r'<pre><code class="language-mermaid">([\s\S]*?)</code></pre>',
        lambda m: f'<pre class="mermaid">{m.group(1)}</pre>',
        html,
    )
    return html


def write_html() -> None:
    source = MD_PATH.read_text(encoding="utf-8")
    # 封面已在模板里，去掉重复的一级标题以免连打两行
    source = re.sub(r"^# 新手复现指南\s*\n+", "", source, count=1)
    HTML_PATH.write_text(HTML_TMPL.format(css=CSS, body=md_to_html(source)), encoding="utf-8")


def write_puppeteer() -> None:
    PUPPETEER.write_text(
        r"""
import { pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";

const html = process.argv[2];
const pdf = process.argv[3];
const chrome = process.argv[4];

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--disable-gpu", "--no-sandbox"],
});
const page = await browser.newPage();
await page.goto(pathToFileURL(html).href, { waitUntil: "networkidle0", timeout: 120000 });
await page.waitForFunction(() => document.body.dataset.ready === "1", { timeout: 60000 });
await page.pdf({
  path: pdf,
  format: "A4",
  printBackground: true,
  displayHeaderFooter: true,
  headerTemplate: `<div style="font-size:8px;width:100%;text-align:center;color:#667;font-family:'Microsoft YaHei',sans-serif;padding-top:6px;">洛克王国智能助手 · 新手复现指南</div>`,
  footerTemplate: `<div style="font-size:8px;width:100%;text-align:center;color:#667;font-family:'Microsoft YaHei',sans-serif;padding-bottom:6px;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>`,
  margin: { top: "16mm", bottom: "16mm", left: "12mm", right: "12mm" },
});
await browser.close();
""",
        encoding="utf-8",
    )


def ensure_puppeteer() -> None:
    pkg = ROOT / "package.json"
    if not (ROOT / "node_modules" / "puppeteer-core").exists():
        if not pkg.exists():
            pkg.write_text(json.dumps({"private": True, "type": "module"}, ensure_ascii=False), encoding="utf-8")
        subprocess.check_call(["npm", "install", "puppeteer-core@24"], cwd=ROOT, shell=True)


def main() -> int:
    if not MD_PATH.exists():
        print(f"找不到 {MD_PATH}")
        return 1
    if not CHROME.exists():
        print(f"找不到 Chrome：{CHROME}")
        return 1
    write_html()
    write_puppeteer()
    ensure_puppeteer()
    subprocess.check_call(
        ["node", str(PUPPETEER), str(HTML_PATH), str(PDF_PATH), str(CHROME)],
        cwd=ROOT,
        shell=True,
    )
    print(f"已写出 {PDF_PATH} （{PDF_PATH.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
