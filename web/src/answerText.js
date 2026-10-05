const LEADING_HASH = /^#{1,6}\s*/;
const SOURCE_LINE = /^(.+?)｜(https?:\/\/\S+)$/;
const LIST_UL = /^[-•]\s+(.+)$/;
const LIST_OL = /^(\d+)\.\s+(.+)$/;

function visible(text) {
  return String(text || "").replace(LEADING_HASH, "").replace(/#{2,}/g, "").trim();
}

function isSafeUrl(url) {
  return /^https?:\/\/[^\s]+$/i.test(url || "") && !/^javascript:/i.test(url || "");
}

export function inlineParts(line) {
  const source = visible(line);
  const parts = [];
  const pattern = /\*\*([^*\n]+)\*\*|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let cursor = 0;
  let match = pattern.exec(source);
  while (match) {
    if (match.index > cursor) parts.push({ text: source.slice(cursor, match.index) });
    if (match[1]) {
      parts.push({ text: match[1], strong: true });
    } else if (isSafeUrl(match[3])) {
      parts.push({ text: match[2], href: match[3] });
    } else {
      parts.push({ text: match[0] });
    }
    cursor = match.index + match[0].length;
    match = pattern.exec(source);
  }
  if (cursor < source.length) parts.push({ text: source.slice(cursor) });
  return parts.filter((part) => part.text);
}

function isTitle(line) {
  const text = visible(line);
  if (!text || /https?:\/\//i.test(text) || /^[⏳❌]/.test(text)) return "";
  if (/^[-•]\s+/.test(text) || /^\d+\.\s+/.test(text)) return "";
  if (/^[【[][^】\]]{1,30}[】\]]$/.test(text)) return text;
  if (text.length <= 18 && !/[。！？，、：]/.test(text)) return text;
  return "";
}

export function parseAnswer(raw) {
  const lines = String(raw || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  const sources = [];
  let paragraph = [];
  let list = null;

  function flushParagraph() {
    if (!paragraph.length) return;
    blocks.push({ type: "p", parts: inlineParts(paragraph.join("\n")) });
    paragraph = [];
  }

  function flushList() {
    if (!list) return;
    blocks.push(list);
    list = null;
  }

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const trimmed = rawLine.trim();
    if (trimmed === "```" || /^```\w*$/.test(trimmed)) continue;
    if (trimmed === "来源" || trimmed === "【来源】") {
      flushParagraph();
      flushList();
      for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
        const sourceLine = visible(lines[cursor]);
        if (!sourceLine) continue;
        const matched = sourceLine.match(SOURCE_LINE);
        if (matched && isSafeUrl(matched[2])) {
          sources.push({ title: matched[1].trim(), url: matched[2] });
        }
      }
      break;
    }
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    const title = isTitle(rawLine);
    if (title) {
      flushParagraph();
      flushList();
      blocks.push({ type: "title", text: title });
      continue;
    }
    const bullet = trimmed.match(LIST_UL);
    const ordered = trimmed.match(LIST_OL);
    if (bullet || ordered) {
      flushParagraph();
      const kind = bullet ? "ul" : "ol";
      if (!list || list.type !== kind) {
        flushList();
        list = { type: kind, items: [] };
      }
      list.items.push(inlineParts((bullet || ordered)[bullet ? 1 : 2]));
      continue;
    }
    flushList();
    paragraph.push(rawLine.trimEnd());
  }
  flushParagraph();
  flushList();
  return { blocks, sources };
}
