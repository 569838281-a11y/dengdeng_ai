import { useEffect, useRef, useState } from "react";
import { Footprints, Globe, LogOut, PawPrint, Search, Send, Settings, Swords, UserPlus, Users } from "lucide-react";
import { api, parseTeam } from "../api";
import { Frame } from "../ui/Frame";
import { GameIcon } from "../ui/GameIcon";
import { IconButton } from "../ui/IconButton";
import { BattleBox } from "./BattleBox";
import { ChatBubble } from "./ChatBubble";

const modes = [
  { id: "team", label: "智能配队", iconId: "icon-mode-team", icon: Users },
  { id: "search", label: "检索信息", iconId: "icon-mode-search", icon: Search },
  { id: "battle", label: "模拟对战", iconId: "icon-mode-battle", icon: Swords },
];
const storageKey = "roco-guest-chats";

function thinkingLine() {
  return "灯灯在听这句话。";
}

function formatTeam(team) {
  const lines = ["队伍配置为"];
  for (const member of team.members || []) {
    const tags = (member.tags || []).join("、");
    const skills = (member.skills || []).map((skill) => skill.raw || skill.name).filter(Boolean).join("、");
    lines.push(`- ${member.name}｜标签：${tags || "未提供"}｜血脉：${member.blood || "初始血脉"}｜技能：${skills}`);
  }
  lines.push(`战斗道具：【${team.item || "未提供"}】`);
  lines.push(`选取的理由是${team.reason || "按你拖过的这一套"}`);
  return lines.join("\n");
}

function lineupLead(text) {
  const body = String(text || "").trim();
  const marked = body.match(/灯灯(?:记下了|改好了)第\s*\d+\s*套出场。/);
  if (marked) return marked[0];
  const end = body.indexOf("。");
  if (end > 0 && end < 48) return body.slice(0, end + 1);
  return body;
}

function lineupRecord(answer, team, sources) {
  const lines = ["队伍配置为"];
  for (const member of team.members || []) {
    const tags = (member.tags || []).join("、");
    const skills = (member.skills || []).map((skill) => skill.raw || skill.name).filter(Boolean).join("、");
    lines.push(`- ${member.name}｜标签：${tags}｜血脉：${member.blood || ""}｜技能：${skills}`);
  }
  if (team.item) lines.push(`战斗道具：【${team.item}】`);
  if (team.reason) lines.push(`选取的理由是${team.reason}`);
  const blocks = [lineupLead(answer), lines.join("\n")];
  const sourceLines = (sources || [])
    .filter((item) => /^https?:\/\//i.test(item?.url || ""))
    .map((item) => `${item.title || item.url}｜${item.url}`);
  if (sourceLines.length) blocks.push(["来源", ...sourceLines].join("\n"));
  return blocks.filter(Boolean).join("\n\n");
}

export function ChatApp({ auth, onLeave, onEnter }) {
  const [mode, setMode] = useState("team");
  const [sidebar, setSidebar] = useState(true);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState([]);
  const [chats, setChats] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [settings, setSettings] = useState(false);
  const [passwordForm, setPasswordForm] = useState({ old: "", next: "", message: "" });
  const [upgrade, setUpgrade] = useState({ username: "", password: "", message: "" });
  const [sessionId, setSessionId] = useState("");
  const [useWeb, setUseWeb] = useState(true);
  const scroller = useRef(null);
  const runRef = useRef(0);
  const inflightRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const modeLabel = modes.find((item) => item.id === mode)?.label || "";

  useEffect(() => {
    let cancel = false;
    (async () => {
      const session = await api("/session", { method: "POST", body: "{}" });
      if (cancel) return;
      setSessionId(session.session_id);
      if (auth.kind === "user") {
        setChats(await api(`/conversations?user_id=${auth.userId}`));
      } else {
        setChats(JSON.parse(sessionStorage.getItem(storageKey) || "[]"));
      }
    })().catch(() => {});
    return () => {
      cancel = true;
    };
  }, [auth.kind, auth.userId]);

  useEffect(() => {
    if (!sessionId) return;
    let cancel = false;
    api(`/files/pending?session_id=${encodeURIComponent(sessionId)}`)
      .then((rows) => {
        if (cancel || !Array.isArray(rows) || !rows.length) return;
        setMessages((current) => {
          const seen = new Set(current.map((item) => item.pending?.token).filter(Boolean));
          const extra = rows
            .filter((item) => item?.token && !seen.has(item.token))
            .map((item) => ({
              id: `pending-${item.token}`,
              role: "assistant",
              text: item.preview || "灯灯等你点头。",
              mood: "normal",
              pending: item,
              team: parseTeam(item.roster),
              trace: [
                { kind: "edit", text: item.preview || item.label || "等你点头" },
                { kind: "thought", text: `待确认 ${item.token}` },
              ],
            }));
          return extra.length ? [...current, ...extra] : current;
        });
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (auth.kind !== "guest" || !activeId) return;
    const title = messages.find((item) => item.role === "user")?.text?.slice(0, 18) || "新的对话";
    setChats((rows) => {
      const next = rows.filter((item) => item.id !== activeId);
      next.unshift({ id: activeId, title, mode, messages, sessionId });
      const saved = next.slice(0, 30);
      sessionStorage.setItem(storageKey, JSON.stringify(saved));
      return saved;
    });
  }, [messages, activeId, mode, auth.kind, sessionId]);

  useEffect(() => {
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages]);

  async function newChat() {
    setActiveId("");
    setMessages([]);
    setMode("team");
    if (auth.kind === "user") {
      setSessionId("");
      return;
    }
    setSessionId("");
    const session = await api("/session", { method: "POST", body: "{}" });
    setSessionId(session.session_id);
  }

  async function openChat(chat) {
    setActiveId(String(chat.id));
    setMode(chat.mode || "team");
    if (auth.kind === "guest") {
      setMessages(chat.messages || []);
      if (chat.sessionId) {
        setSessionId(chat.sessionId);
      } else {
        const session = await api("/session", { method: "POST", body: "{}" });
        setSessionId(session.session_id);
      }
      return;
    }
    if (chat.session_id) setSessionId(chat.session_id);
    const rows = await api(`/conversations/${chat.id}`);
    setMessages(rows.map((row) => ({
      role: row.role,
      text: row.content,
      team: parseTeam(row.content),
    })));
  }

  async function ensureServerChat(title) {
    if (auth.kind !== "user") {
      let sid = sessionId;
      if (!sid) {
        const session = await api("/session", { method: "POST", body: "{}" });
        sid = session.session_id;
        setSessionId(sid);
      }
      const id = activeId || `guest-${Date.now()}`;
      if (!activeId) setActiveId(id);
      return { id, sessionId: sid };
    }
    if (activeId) return { id: activeId, sessionId: sessionId || "" };
    const created = await api(`/conversations?user_id=${auth.userId}`, {
      method: "POST",
      body: JSON.stringify({ title }),
    });
    setActiveId(String(created.id));
    setSessionId(created.session_id || "");
    setChats((rows) => [created, ...rows]);
    return { id: String(created.id), sessionId: created.session_id || "" };
  }

  async function remember(chatId, role, text) {
    if (auth.kind !== "user" || !chatId) return;
    await api(`/conversations/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ user_id: auth.userId, role, content: text }),
    });
  }

  function finishTrial(message) {
    if (!message?.id || !message.trial || message.trial.played) return;
    setMessages((rows) => rows.map((row) => {
      if (row.id !== message.id) return row;
      const closing = row.trial?.closing || "";
      const intro = row.trial?.intro || row.text || "";
      const text = closing && !String(row.text || "").includes(closing) ? `${intro}\n${closing}` : row.text;
      return { ...row, text, mood: "normal", trial: { ...row.trial, played: true } };
    }));
  }

  function patchLast(patch) {
    setMessages((rows) => {
      if (!rows.length) return rows;
      const next = rows.slice();
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  }

  function patchById(id, patch) {
    setMessages((rows) => rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function kindFor(task) {
    const lineup = /配队|组建|出场|队伍|为核心/.test(task || "");
    const lookup = /技能池|种族值|特性|为什么|克制|是什么|技能/.test(task || "");
    if (lineup && !lookup) return "team";
    if (lookup && !lineup) return "search";
    return mode === "search" ? "search" : "team";
  }

  async function askJob({ kind, question, bubbleId, sid, chatId, run, note }) {
    const path = kind === "search" ? "/knowledge/jobs" : "/agents/jobs";
    const job = await api(path, {
      method: "POST",
      timeoutMs: 12000,
      body: JSON.stringify({
        question,
        session_id: sid,
        include_history: true,
        ...(kind === "search" ? { use_web: useWeb } : {}),
        ...(auth.userId ? { user_id: auth.userId } : {}),
      }),
    });
    if (!job.job_id) throw new Error(kind === "search" ? "接口没有返回检索任务编号" : "接口没有返回任务编号");
    if (inflightRef.current?.run === run) {
      inflightRef.current.jobIds = [...(inflightRef.current.jobIds || []), job.job_id];
    }
    const withNote = (trace) => (note ? [{ kind: "thought", text: note }, ...(trace || [])] : trace);
    const source = new EventSource(`/api/v1/jobs/${job.job_id}/events`);
    source.onmessage = (event) => {
      if (runRef.current !== run) return;
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!data || data.kind === "ping" || data.kind === "status") {
        if (data?.kind === "status" && ["done", "error", "superseded", "awaiting_confirm"].includes(data.status)) source.close();
        return;
      }
      setMessages((rows) => rows.map((row) => {
        if (row.id !== bubbleId) return row;
        const trace = [...(row.trace || [])];
        if (data.kind === "delta") {
          const last = trace[trace.length - 1];
          if (last && last.kind === "thought" && last.open) trace[trace.length - 1] = { ...last, text: data.text };
          else trace.push({ kind: "thought", text: data.text, open: true });
          return { ...row, trace, mood: "thinking" };
        }
        if (data.kind === "close") {
          const last = trace[trace.length - 1];
          if (last?.open) trace[trace.length - 1] = { ...last, open: false };
          return { ...row, trace, mood: "thinking" };
        }
        if (trace.some((item) => item.kind === data.kind && item.text === data.text)) return row;
        return { ...row, trace: [...trace, { kind: data.kind, text: data.text }], mood: row.mood === "normal" ? row.mood : "thinking" };
      }));
    };
    source.onerror = () => source.close();
    if (runRef.current === run) patchById(bubbleId, { trace: withNote(job.trace), mood: "thinking" });
    let view = job;
    // 多跳联网（出场率桥接 + 名录 + 成文）常超过 3 分钟；超时只表示前端等不及，后台可能仍在跑。
    const deadline = Date.now() + (kind === "search" ? 360000 : 600000);
    const finished = ["done", "error", "superseded", "awaiting_confirm"];
    while (runRef.current === run && Date.now() < deadline && !finished.includes(view.status)) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      if (runRef.current !== run) {
        source.close();
        return null;
      }
      view = await api(`${path}/${job.job_id}`, { timeoutMs: 8000 });
      if (runRef.current !== run) {
        source.close();
        return null;
      }
      if (view.trace) {
        setMessages((rows) => rows.map((row) => {
          if (row.id !== bubbleId) return row;
          const server = withNote(view.trace);
          const local = row.trace || [];
          const serverTail = server[server.length - 1]?.text?.length || 0;
          const localTail = local[local.length - 1]?.text?.length || 0;
          const newer = server.length > local.length || (server.length === local.length && serverTail >= localTail);
          return { ...row, trace: newer ? server : local, mood: "thinking" };
        }));
      }
    }
    source.close();
    if (runRef.current !== run || !view || view.status === "superseded") return null;
    if (view.status === "error" || view.error) {
      patchById(bubbleId, { text: `❌ ${view.error || view.message || "失败"}`, trace: view.trace, mood: "cry" });
    } else if (view.status === "awaiting_confirm" || view.pending_write) {
      const pending = view.pending_write || null;
      patchById(bubbleId, {
        text: pending?.preview || view.answer || "灯灯等你点头。",
        trace: withNote(view.trace),
        pending,
        team: view.team || parseTeam(view.roster) || parseTeam(pending?.roster),
        mood: "normal",
      });
    } else if (view.status !== "done") {
      const timeoutText = kind === "search" ? "❌ 检索超时：任务仍在处理，请稍后重试" : "❌ 配队超时：任务仍在处理，请稍后重试";
      patchById(bubbleId, { text: timeoutText, trace: view.trace, mood: "cry" });
    } else if (view.trial?.frames?.length) {
      patchById(bubbleId, {
        text: view.trial.intro || view.answer || "",
        trial: view.trial,
        trace: withNote(view.trace),
        mood: "thinking",
      });
      await remember(chatId, "assistant", `${view.trial.intro || ""}\n${view.trial.closing || ""}`.trim());
      return view;
    } else if (kind === "search") {
      const answer = view.answer || "";
      const hits = view.hits || [];
      const cry = !String(answer).trim() || /知识量还不够|你问的问题太难了|可爱的双灯鱼/.test(answer);
      patchById(bubbleId, {
        text: answer,
        hits,
        trace: withNote(view.trace),
        webSources: view.web_sources || [],
        mood: cry || (hits.length === 0 && !(view.web_sources || []).length) ? "cry" : "normal",
      });
    } else {
      const answer = view.answer || "";
      const team = view.team || parseTeam(view.answer) || parseTeam(view.roster);
      const webSources = view.web_sources || [];
      patchById(bubbleId, {
        text: answer,
        trace: withNote(view.trace),
        team,
        webSources,
        mood: String(answer).trim() ? "normal" : "cry",
      });
      if (team) {
        await remember(chatId, "assistant", lineupRecord(answer, team, webSources));
        return view;
      }
    }
    await remember(chatId, "assistant", view.answer || view.error || view.message || "");
    return view;
  }

  async function reviseTeam(message, team) {
    const corrected = formatTeam(team);
    const result = await api("/teams/revise", {
      method: "POST",
      timeoutMs: 20000,
      body: JSON.stringify({
        question: message.question || "",
        model_answer: message.text || corrected,
        corrected_team: corrected,
      }),
    });
    return result;
  }

  function settleWrite(token, text, roster) {
    const team = parseTeam(roster);
    setMessages((rows) => [
      ...rows.map((row) => (row.pending?.token === token ? { ...row, pending: null } : row)),
      { role: "assistant", text, team, mood: "normal" },
    ]);
  }

  async function confirmWrite(token) {
    const result = await api("/files/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    settleWrite(token, result.text || `灯灯记下了${result.saved || ""}。`, result.roster);
  }

  async function rejectWrite(token) {
    const result = await api("/files/reject", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    settleWrite(token, result.text || "灯灯没有记下。", "");
  }

  async function send(event) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || mode === "battle") return;
    setDraft("");
    const flight = inflightRef.current;
    if (flight && runRef.current === flight.run) {
      const run = ++runRef.current;
      const previous = flight.question;
      const oldIds = flight.jobIds || [];
      setBusy(true);
      inflightRef.current = { run, question: text, jobIds: [], mode, sid: flight.sid || sessionId };
      let bubbles = [];
      try {
        const chat = await ensureServerChat(text.slice(0, 18));
        if (runRef.current !== run) return;
        const chatId = chat.id;
        const sid = chat.sessionId || flight.sid || sessionId;
        inflightRef.current.sid = sid;
        if (auth.kind === "guest" && !activeId) setActiveId(chatId);
        await remember(chatId, "user", text);
        const verdict = await api("/followup", {
          method: "POST",
          timeoutMs: 12000,
          body: JSON.stringify({ previous, incoming: text, supersede_job_ids: oldIds }),
        });
        if (runRef.current !== run) return;
        const tasks = verdict.tasks || [];
        const note = verdict.kind === "task" ? "灯灯分成两项来答" : "灯灯把后一句并进上一问";
        bubbles = tasks.map((task, index) => ({
          id: `pending-${run}-${index}`,
          role: "assistant",
          text: thinkingLine(),
          question: text,
          team: null,
          mood: "thinking",
          trace: [{ kind: "thought", text: index === 0 ? note : "灯灯再答后一项" }],
          task,
        }));
        setMessages((rows) => {
          const next = rows.slice();
          while (next.length && next[next.length - 1].role === "assistant" && next[next.length - 1].mood === "thinking") next.pop();
          next.push({ role: "user", text });
          bubbles.forEach((bubble) => next.push(bubble));
          return next;
        });
        inflightRef.current.question = verdict.kind === "condition" ? (tasks[0] || text) : text;
        await Promise.all(bubbles.map((bubble) => askJob({
          kind: kindFor(bubble.task),
          question: bubble.task,
          bubbleId: bubble.id,
          sid,
          chatId,
          run,
          note: bubble.trace[0].text,
        })));
      } catch (error) {
        if (bubbles[0]) patchById(bubbles[0].id, { text: `❌ ${error.message}`, mood: "cry" });
        else patchLast({ text: `❌ ${error.message}`, mood: "cry" });
      } finally {
        if (inflightRef.current?.run === run) {
          inflightRef.current = null;
          setBusy(false);
        }
      }
      return;
    }
    const run = ++runRef.current;
    const bubbleId = `pending-${run}`;
    setBusy(true);
    inflightRef.current = { run, question: text, jobIds: [], mode, sid: sessionId };
    setMessages((rows) => [...rows, { role: "user", text }, { id: bubbleId, role: "assistant", text: thinkingLine(), question: text, team: null, mood: "thinking" }]);
    try {
      const chat = await ensureServerChat(text.slice(0, 18));
      if (runRef.current !== run) return;
      const chatId = chat.id;
      const sid = chat.sessionId || sessionId;
      inflightRef.current.sid = sid;
      if (auth.kind === "guest" && !activeId) setActiveId(chatId);
      await remember(chatId, "user", text);
      await askJob({
        kind: mode === "search" ? "search" : "team",
        question: text,
        bubbleId,
        sid,
        chatId,
        run,
        note: "",
      });
    } catch (error) {
      if (runRef.current === run) patchById(bubbleId, { text: `❌ ${error.message}`, mood: "cry" });
    } finally {
      if (inflightRef.current?.run === run) {
        inflightRef.current = null;
        setBusy(false);
      }
    }
  }

  async function changePassword() {
    setPasswordForm((form) => ({ ...form, message: "" }));
    try {
      const result = await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          username: auth.username,
          old_password: passwordForm.old,
          new_password: passwordForm.next,
        }),
      });
      if (!result.success) throw new Error(result.message);
      setPasswordForm((form) => ({ ...form, message: "密码已更新" }));
    } catch (error) {
      setPasswordForm((form) => ({ ...form, message: error.message }));
    }
  }

  async function becomeUser() {
    setUpgrade((form) => ({ ...form, message: "" }));
    try {
      const result = await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({ username: upgrade.username, password: upgrade.password }),
      });
      if (!result.success) throw new Error(result.message);
      const created = await api(`/conversations?user_id=${result.user_id}`, {
        method: "POST",
        body: JSON.stringify({ title: "游客对话" }),
      });
      for (const item of messages) {
        await api(`/conversations/${created.id}/messages`, {
          method: "POST",
          body: JSON.stringify({ user_id: result.user_id, role: item.role, content: item.text || "" }),
        });
      }
      onEnter({ kind: "user", username: result.username, userId: result.user_id });
    } catch (error) {
      setUpgrade((form) => ({ ...form, message: error.message }));
    }
  }

  return (
    <div className="flex h-dvh min-h-0 flex-col overflow-hidden lg:flex-row">
      <div className="viewport-wall viewport-wall--app" aria-hidden="true" />
      <aside className={`${sidebar ? "flex" : "hidden"} relative z-10 h-[38vh] min-h-0 w-full shrink-0 flex-col p-3 lg:h-full lg:w-72`}>
        <Frame variant="sidebar" className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3">
          <IconButton id="icon-new-chat" icon={UserPlus} label="新对话" size={48} onClick={newChat} />
          <div className="mt-2 grid min-h-0 flex-1 gap-2 overflow-y-auto">
            {chats.map((chat) => (
              <button key={chat.id} type="button" className="icon-pop flex items-center gap-2 rounded-2xl bg-sprout/70 px-2 py-2 text-left text-sm font-bold" onClick={() => openChat(chat)}>
                <PawPrint size={16} />
                <span className="truncate">{chat.title || "对话"}</span>
              </button>
            ))}
          </div>
        </Frame>
      </aside>
      <section className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center justify-between gap-2 px-3 py-3">
          <IconButton id="icon-history" icon={Footprints} label={sidebar ? "收起" : "历史"} size={32} onClick={() => setSidebar((open) => !open)} />
          <div className="text-center">
            <strong className="block text-lg">洛克王国智能助手</strong>
            <span className="rounded-full bg-sun px-3 py-0.5 text-xs font-bold">{modeLabel}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-sm font-bold sm:inline">{auth.username || "游客"}</span>
            <IconButton id="icon-settings" icon={Settings} label="设置" size={32} onClick={() => setSettings((open) => !open)} />
            <IconButton id="icon-logout" icon={LogOut} label="退出" size={32} onClick={onLeave} />
          </div>
        </header>
        {settings ? (
          <Frame className="mx-3 mb-2 shrink-0 p-3">
            {auth.kind === "user" ? (
              <div className="grid gap-2">
                <h2 className="font-bold">修改密码</h2>
                <input className="rounded-full border-4 border-wood px-3 py-2" type="password" placeholder="旧密码" value={passwordForm.old} onChange={(event) => setPasswordForm((form) => ({ ...form, old: event.target.value }))} />
                <input className="rounded-full border-4 border-wood px-3 py-2" type="password" placeholder="新密码，至少 6 位" value={passwordForm.next} onChange={(event) => setPasswordForm((form) => ({ ...form, next: event.target.value }))} />
                <IconButton id="icon-settings" icon={Settings} label="更新" size={40} onClick={changePassword} />
                <p className="text-sm">{passwordForm.message}</p>
              </div>
            ) : (
              <div className="grid gap-2">
                <h2 className="font-bold">转为注册</h2>
                <p className="text-sm">游客不能改密码。注册后会留下当前这段对话。</p>
                <input className="rounded-full border-4 border-wood px-3 py-2" placeholder="用户名" value={upgrade.username} onChange={(event) => setUpgrade((form) => ({ ...form, username: event.target.value }))} />
                <input className="rounded-full border-4 border-wood px-3 py-2" type="password" placeholder="密码，至少 6 位" value={upgrade.password} onChange={(event) => setUpgrade((form) => ({ ...form, password: event.target.value }))} />
                <IconButton id="icon-new-chat" icon={UserPlus} label="注册并保留对话" size={40} onClick={becomeUser} />
                <p className="text-sm">{upgrade.message}</p>
              </div>
            )}
          </Frame>
        ) : null}
        <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pb-3">
          {!messages.length && mode !== "battle" ? (
            <div className="grid place-items-center py-10 text-center">
              <GameIcon id="empty-mascot" icon={PawPrint} size={72} />
              <p className="mt-2 font-bold">从下面选一个功能，再用一句话开始。</p>
            </div>
          ) : null}
          {messages.map((item, index) => (
            <ChatBubble
              key={item.id || index}
              message={item}
              onTrialFinish={finishTrial}
              onRevise={reviseTeam}
              onConfirmWrite={confirmWrite}
              onRejectWrite={rejectWrite}
            />
          ))}
          {mode === "battle" ? (
            <BattleBox
              onLog={(text) => { if (text) setMessages((rows) => [...rows, { role: "assistant", text, mood: "normal" }]); }}
              onOrder={(question, answer, mood) => {
                if (!question) return;
                setMessages((rows) => [
                  ...rows,
                  { role: "user", text: question },
                  { role: "assistant", text: answer || "灯灯没听懂小洛克的意思。", mood: mood || "cry" },
                ]);
              }}
            />
          ) : null}
        </div>
        <footer className="shrink-0 px-3 pb-4">
          <div className="mb-2 flex justify-around">
            {modes.map((item) => (
              <IconButton key={item.id} id={item.iconId} icon={item.icon} label={item.label} size={56} active={mode === item.id} onClick={() => setMode(item.id)} />
            ))}
          </div>
          {mode !== "battle" ? (
            <form className="flex items-end gap-2" onSubmit={send}>
              {mode === "search" ? (
                <IconButton id="icon-web-search" icon={Globe} label="联网搜寻" size={48} active={useWeb} onClick={() => setUseWeb((on) => !on)} />
              ) : null}
              <textarea
                rows={2}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder={busy ? "思考时可以补一句条件，或另起一项任务" : (mode === "search" ? "例如：板块 C，或水灵" : "例如：以水灵为核心，偏防守")}
                className="min-w-0 flex-1 rounded-[1.4rem] border-4 border-wood bg-cream px-4 py-2"
              />
              <IconButton id="icon-send" icon={Send} label="发送" size={48} type="submit" />
            </form>
          ) : null}
        </footer>
      </section>
    </div>
  );
}
