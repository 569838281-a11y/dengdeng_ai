import { Portrait } from "../ui/Portrait";
import { BubbleText } from "./BubbleText";
import { TrialReplay } from "./BattleBox";
import { TeamCards } from "./TeamCards";

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

function ThoughtChain({ trace = [], live = false }) {
  if (!trace.length) return null;
  const labels = { thought: "Thought", read: "Read", edit: "Edited" };
  return (
    <ol className="thought-chain">
      {trace.map((item, index) => (
        <li key={`${item.kind}-${index}`} className={live && index === trace.length - 1 ? "is-live" : ""}>
          <b>{labels[item.kind] || "Thought"}</b>
          <span>{item.text}</span>
        </li>
      ))}
    </ol>
  );
}

export function ChatBubble({ message, onTrialFinish }) {
  const mine = message.role === "user";
  const face = mine ? "user" : assistantFace(message);
  return (
    <article className={`flex w-full items-start gap-2 ${mine ? "flex-row-reverse" : ""}`}>
      <span className="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-2xl border-2 border-wood bg-cream">
        <Portrait name={face} form="base" alt="" className="h-12 w-12" />
      </span>
      <div
        className={`max-w-3xl min-w-0 rounded-[1.4rem] border-4 px-4 py-3 break-words ${
          mine ? "border-honey bg-honey/80" : "border-grass bg-cream"
        }`}
      >
        {message.role === "assistant" ? (
          <>
            <ThoughtChain trace={message.trace} live={message.mood === "thinking"} />
            {message.text && !(message.mood === "thinking" && message.trace?.length) ? (
              <BubbleText text={message.text} sources={message.webSources || []} />
            ) : null}
            {message.trial ? <TrialReplay trial={message.trial} onFinish={() => onTrialFinish?.(message)} /> : null}
            {message.team ? <TeamCards team={message.team} /> : null}
          </>
        ) : (
          <p className="whitespace-pre-wrap">{message.text}</p>
        )}
      </div>
    </article>
  );
}
