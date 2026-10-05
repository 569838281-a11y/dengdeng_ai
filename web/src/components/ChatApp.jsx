import { useEffect, useState } from "react";
import { Footprints, Globe, LogOut, PawPrint, Search, Send, Settings, Swords, UserPlus, Users } from "lucide-react";
import { api, parseTeam } from "../api";
import { Frame } from "../ui/Frame";
import { GameIcon } from "../ui/GameIcon";
import { IconButton } from "../ui/IconButton";
import { BattleBox } from "./BattleBox";
import { ChatBubble } from "./ChatBubble";
import { RagFlow } from "./RagFlow";

const modes = [
  { id: "team", label: "智能配队", iconId: "icon-mode-team", icon: Users },
  { id: "search", label: "检索信息", iconId: "icon-mode-search", icon: Search },
  { id: "battle", label: "模拟对战", iconId: "icon-mode-battle", icon: Swords },
];
const storageKey = "roco-guest-chats";

const thinkingLines = [
  "灯灯记得好像在书中看到过这个知识点呀，让灯灯来好好想一想...",
  "噔噔！让冰雪聪明的灯灯来帮你出个主意吧！",
  "噔噔，噔噔，噔噔！灵感到底在哪里呀！",
];

function thinkingLine() {
  return thinkingLines[Math.floor(Math.random() * thinkingLines.length)];
}

function freshRagSteps() {
  return [
    { id: "parse", label: "理解意图", status: "pending", detail: "" },
    { id: "lookup", label: "结构化检索", status: "pending", detail: "" },
    { id: "web", label: "联网搜寻", status: "pending", detail: "" },
    { id: "index", label: "知识索引", status: "pending", detail: "" },
    { id: "retrieve", label: "召回片段", status: "pending", detail: "" },
    { id: "generate", label: "生成回答", status: "pending", detail: "" },
    { id: "done", label: "合并结果", status: "pending", detail: "" },
  ];
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
  const [ragActive, setRagActive] = useState(false);
  const [ragSteps, setRagSteps] = useState(freshRagSteps);
  const [useWeb, setUseWeb] = useState(false);
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
    if (auth.kind !== "guest" || !activeId) return;
    const title = messages.find((item) => item.role === "user")?.text?.slice(0, 18) || "新的对话";
    setChats((rows) => {
      const next = rows.filter((item) => item.id !== activeId);
      next.unshift({ id: activeId, title, mode, messages });
      const saved = next.slice(0, 30);
      sessionStorage.setItem(storageKey, JSON.stringify(saved));
      return saved;
    });
  }, [messages, activeId, mode, auth.kind]);

  function newChat() {
    setActiveId("");
    setMessages([]);
    setMode("team");
    setRagActive(false);
    setRagSteps(freshRagSteps());
  }

  async function openChat(chat) {
    setActiveId(String(chat.id));
    setMode(chat.mode || "team");
    if (auth.kind === "guest") {
      setMessages(chat.messages || []);
      return;
    }
    const rows = await api(`/conversations/${chat.id}`);
    setMessages(rows.map((row) => ({
      role: row.role,
      text: row.content,
      team: parseTeam(row.content),
    })));
  }

  async function ensureServerChat(title) {
    if (auth.kind !== "user") {
      const id = activeId || `guest-${Date.now()}`;
      if (!activeId) setActiveId(id);
      return id;
    }
    if (activeId) return activeId;
    const created = await api(`/conversations?user_id=${auth.userId}`, {
      method: "POST",
      body: JSON.stringify({ title }),
    });
    setActiveId(String(created.id));
    setChats((rows) => [created, ...rows]);
    return String(created.id);
  }

  async function remember(chatId, role, text) {
    if (auth.kind !== "user" || !chatId) return;
    await api(`/conversations/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ user_id: auth.userId, role, content: text }),
    });
  }

  function patchLast(patch) {
    setMessages((rows) => {
      if (!rows.length) return rows;
      const next = rows.slice();
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  }

  async function send(event) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || mode === "battle") return;
    setDraft("");
    const placeholder = {
      role: "assistant",
      text: thinkingLine(),
      team: null,
      mood: "thinking",
    };
    setMessages((rows) => [...rows, { role: "user", text }, placeholder]);
    try {
      const chatId = await ensureServerChat(text.slice(0, 18));
      if (auth.kind === "guest" && !activeId) setActiveId(chatId);
      await remember(chatId, "user", text);
      if (mode === "search") {
        setRagActive(true);
        setRagSteps(freshRagSteps());
        const job = await api("/knowledge/jobs", {
          method: "POST",
          timeoutMs: 12000,
          body: JSON.stringify({
            question: text,
            session_id: sessionId,
            include_history: true,
            use_web: useWeb,
            ...(auth.userId ? { user_id: auth.userId } : {}),
          }),
        });
        if (!job.job_id) throw new Error("接口没有返回检索任务编号");
        if (job.steps) setRagSteps(job.steps.map((step) => ({ ...step })));
        let view = job;
        const deadline = Date.now() + 180000;
        while (Date.now() < deadline && !["done", "error"].includes(view.status)) {
          await new Promise((resolve) => setTimeout(resolve, 400));
          view = await api(`/knowledge/jobs/${job.job_id}`, { timeoutMs: 8000 });
          if (view.steps) setRagSteps(view.steps.map((step) => ({ ...step })));
        }
        setRagActive(false);
        if (view.steps) setRagSteps(view.steps.map((step) => ({ ...step })));
        if (view.status === "error" || view.error) {
          patchLast({ text: `❌ ${view.error || view.message || "检索失败"}`, mood: "cry" });
          setRagSteps((steps) => {
            const next = steps.map((step) => ({ ...step }));
            const running = next.find((step) => step.status === "running") || next.find((step) => step.status === "pending");
            if (running && !next.some((step) => step.status === "error")) running.status = "error";
            return next;
          });
        } else if (view.status !== "done") {
          patchLast({ text: "❌ 检索超时：任务仍在处理，请稍后重试", mood: "cry" });
        } else {
          const answer = view.answer || "";
          const hits = view.hits || [];
          const cry = !String(answer).trim() || /知识量还不够|你问的问题太难了|可爱的双灯鱼/.test(answer);
          patchLast({
            text: answer,
            hits,
            webSources: view.web_sources || [],
            mood: cry || (hits.length === 0 && !(view.web_sources || []).length) ? "cry" : "normal",
          });
        }
        await remember(chatId, "assistant", view.answer || view.error || view.message || "");
        return;
      }
      const job = await api("/agents/jobs", {
        method: "POST",
        timeoutMs: 12000,
        body: JSON.stringify({
          question: text,
          session_id: sessionId,
          include_history: true,
          ...(auth.userId ? { user_id: auth.userId } : {}),
        }),
      });
      if (!job.job_id) throw new Error("接口没有返回任务编号");
      let view = job;
      const deadline = Date.now() + 600000;
      while (Date.now() < deadline && !["done", "error"].includes(view.status)) {
        await new Promise((resolve) => setTimeout(resolve, 400));
        view = await api(`/agents/jobs/${job.job_id}`, { timeoutMs: 8000 });
      }
      if (view.status === "error" || view.error) {
        patchLast({ text: `❌ 卡在第 ${view.step_index || 2} 步：${view.error || view.message}`, mood: "cry" });
      } else if (!["done", "error"].includes(view.status)) {
        patchLast({ text: "❌ 配队超时：任务仍在处理，请稍后重试", mood: "cry" });
      } else {
        const answer = view.answer || "";
        patchLast({
          text: answer,
          team: view.team || parseTeam(view.answer),
          mood: String(answer).trim() ? "normal" : "cry",
        });
      }
      await remember(chatId, "assistant", view.answer || view.error || view.message || "");
    } catch (error) {
      patchLast({ text: `❌ ${error.message}`, mood: "cry" });
      if (mode === "search") {
        setRagActive(false);
        setRagSteps((steps) => {
          const next = steps.map((step) => ({ ...step }));
          const running = next.find((step) => step.status === "running") || next[0];
          if (running) running.status = "error";
          return next;
        });
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
        {mode === "search" ? <div className="shrink-0"><RagFlow steps={ragSteps} active={ragActive} /></div> : null}
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pb-3">
          {!messages.length && mode !== "battle" ? (
            <div className="grid place-items-center py-10 text-center">
              <GameIcon id="empty-mascot" icon={PawPrint} size={72} />
              <p className="mt-2 font-bold">从下面选一个功能，再用一句话开始。</p>
            </div>
          ) : null}
          {messages.map((item, index) => (
            <ChatBubble key={index} message={item} />
          ))}
          {mode === "battle" ? <BattleBox onLog={(text) => { if (text) setMessages((rows) => [...rows, { role: "assistant", text, mood: "normal" }]); }} /> : null}
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
                placeholder={mode === "search" ? "例如：板块 C，或水灵" : "例如：以水灵为核心，偏防守"}
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
