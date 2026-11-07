import { parseAnswer } from "../answerText";

function Parts({ parts }) {
  return parts.map((part, index) => {
    if (part.strong) return <strong key={index}>{part.text}</strong>;
    if (part.href) {
      return (
        <a key={index} href={part.href} target="_blank" rel="noopener">
          {part.text}
        </a>
      );
    }
    return <span key={index}>{part.text}</span>;
  });
}

export function SourceList({ sources = [] }) {
  if (!sources.length) return null;
  return (
    <div className="web-sources">
      <h3 className="bubble-title">来源</h3>
      <ul className="space-y-1">
        {sources.map((item) => (
          <li key={item.url}>
            <a href={item.url} target="_blank" rel="noopener" className="font-bold text-grass-deep underline">
              {item.title}
            </a>
            <span className="block break-all text-xs text-[#5d746c]">{item.url}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function collectSources(text = "", sources = []) {
  const parsed = parseAnswer(text);
  const links = [];
  const seen = new Set();
  for (const item of [...(sources || []), ...parsed.sources]) {
    const url = String(item?.url || "");
    if (!/^https?:\/\//i.test(url) || seen.has(url)) continue;
    seen.add(url);
    links.push({ title: item.title || url, url });
  }
  for (const block of parsed.blocks) {
    const parts = block.parts || block.items?.flat?.() || [];
    for (const part of parts) {
      const url = String(part?.href || "");
      if (!/^https?:\/\//i.test(url) || seen.has(url)) continue;
      seen.add(url);
      links.push({ title: part.text || url, url });
    }
  }
  return links;
}

export function BubbleText({ text = "", sources = [] }) {
  const parsed = parseAnswer(text);
  const links = collectSources(text, sources);
  return (
    <>
      {parsed.blocks.map((block, index) => {
        if (block.type === "title") {
          return (
            <h3 key={index} className="bubble-title font-bold text-grass-deep">
              {block.text}
            </h3>
          );
        }
        if (block.type === "p") {
          return (
            <p key={index} className="my-1 whitespace-pre-wrap">
              <Parts parts={block.parts} />
            </p>
          );
        }
        if (block.type === "ul") {
          return (
            <ul key={index} className="my-1 list-disc pl-5">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  <Parts parts={item} />
                </li>
              ))}
            </ul>
          );
        }
        return (
          <ol key={index} className="my-1 list-decimal pl-5">
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex}>
                <Parts parts={item} />
              </li>
            ))}
          </ol>
        );
      })}
      <SourceList sources={links} />
    </>
  );
}
