import { Portrait } from "../ui/Portrait";
import { BubbleText, SourceList, collectSources } from "./BubbleText";
import { TrialReplay } from "./BattleBox";
import { TeamCards } from "./TeamCards";

function lineupLead(text) {
  const body = String(text || "").trim();
  const marked = body.match(/灯灯(?:记下了|改好了)第\s*\d+\s*套出场。/);
  if (marked) return marked[0];
  const end = body.indexOf("。");
  if (end > 0 && end < 48) return body.slice(0, end + 1);
  return "";
}

function inferMood(text) {
  const body = String(text || "").trim();
  if (!body) return "cry";
  if (body.includes("⏳") || /书中看到过这个知识点|冰雪聪明的灯灯|灵感到底在哪里/.test(body)) return "thinking";
  if (body.startsWith("❌") || /检索失败|没有找到|未找到|超时|知识量还不够|你问的问题太难了|可爱的双灯鱼/.test(body)) return "cry";
  return "normal";
}

function assistantFace(message) {
  const mood = message.mood || inferMood(message.text);
  if (mood === "thinking") return "dengdeng_thinking";
  if (mood === "cry") return "dengdeng_crying";
  return "dengdeng";
}

function confirmToken(trace = [], pending) {
  if (pending?.token) return pending.token;
  for (const item of trace) {
    const found = String(item.text || "").match(/^待确认\s+([a-f0-9]+)/);
    if (found) return found[1];
  }
  return "";
}

function ThoughtChain({ trace = [], live = false, pending, onConfirmWrite, onRejectWrite }) {
  if (!trace.length && !pending) return null;
  const labels = { thought: "Thought", read: "Read", edit: "Edited" };
  const token = confirmToken(trace, pending);
  return (
    <div>
      {trace.length ? (
        <ol className="thought-chain">
          {trace.map((item, index) => (
            <li key={`${item.kind}-${index}`} className={live && index === trace.length - 1 ? "is-live" : ""}>
              <b>{labels[item.kind] || "Thought"}</b>
              <span>{item.text}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {token && onConfirmWrite ? (
        <p className="mt-2 flex gap-3 text-sm">
          <button type="button" className="underline" onClick={() => onConfirmWrite(token)}>
            同意记下
          </button>
          {onRejectWrite ? (
            <button type="button" className="underline" onClick={() => onRejectWrite(token)}>
              先不记
            </button>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

export function ChatBubble({ message, onTrialFinish, onRevise, onConfirmWrite, onRejectWrite }) {
  const mine = message.role === "user";
  const face = mine ? "user" : assistantFace(message);
  return (
    <article className={`flex w-full items-start gap-2 ${mine ? "flex-row-reverse" : ""}`}>
      <span className="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-2xl border-2 border-wood bg-cream">
        <Portrait name={face} form="base" alt="" className="h-12 w-12" />
      </span>
      <div
        className={`min-w-0 rounded-[1.4rem] border-4 px-4 py-3 break-words ${
          message.team ? "max-w-5xl" : "max-w-3xl"
        } ${mine ? "border-honey bg-honey/80" : "border-grass bg-cream"}`}
      >
        {message.role === "assistant" ? (
          <>
            <ThoughtChain
              trace={message.trace}
              live={message.mood === "thinking"}
              pending={message.pending}
              onConfirmWrite={onConfirmWrite}
              onRejectWrite={onRejectWrite}
            />
            {message.team ? (
              <>
                {lineupLead(message.text) ? <p className="my-1">{lineupLead(message.text)}</p> : null}
                <TeamCards team={message.team} onRevise={onRevise ? (team) => onRevise(message, team) : null} />
                {message.team.reason ? <p className="mt-2 text-sm">配队原因：{message.team.reason}</p> : null}
                {message.team.issues?.length ? (
                  <ul className="mt-1 list-disc pl-5 text-sm text-hp">
                    {message.team.issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                ) : null}
                <SourceList sources={collectSources(message.text, message.webSources || [])} />
              </>
            ) : message.text && !(message.mood === "thinking" && message.trace?.length) ? (
              <BubbleText text={message.text} sources={message.webSources || []} />
            ) : null}
            {message.trial ? <TrialReplay trial={message.trial} onFinish={() => onTrialFinish?.(message)} /> : null}
          </>
        ) : (
          <p className="whitespace-pre-wrap">{message.text}</p>
        )}
      </div>
    </article>
  );
}
