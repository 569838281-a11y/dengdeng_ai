import { useState } from "react";
import { Footprints, KeyRound, LogIn, UserPlus } from "lucide-react";
import { api } from "../api";
import { Frame } from "../ui/Frame";
import { IconButton } from "../ui/IconButton";

export function AuthScreen({ onEnter }) {
  const [panel, setPanel] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setMessage("");
    if (password.length < 6 || (panel === "password" && newPassword.length < 6)) {
      setMessage("密码至少 6 位");
      return;
    }
    setBusy(true);
    try {
      if (panel === "login") {
        const result = await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        if (!result.success) throw new Error(result.message || "登录失败");
        onEnter({ kind: "user", username: result.username, userId: result.user_id });
      } else if (panel === "register") {
        const result = await api("/auth/register", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        if (!result.success) throw new Error(result.message || "注册失败");
        onEnter({ kind: "user", username: result.username, userId: result.user_id });
      } else {
        const result = await api("/auth/change-password", {
          method: "POST",
          body: JSON.stringify({ username, old_password: oldPassword, new_password: newPassword }),
        });
        if (!result.success) throw new Error(result.message || "修改失败");
        setMessage("密码已更新，请登录");
        setPanel("login");
        setPassword("");
      }
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative z-10 flex h-dvh justify-center overflow-y-auto px-4">
      <div className="viewport-wall viewport-wall--meadow" aria-hidden="true" />
      <div className="viewport-wall viewport-wall--login" aria-hidden="true" />
      <div className="meadow-dots pointer-events-none fixed inset-0 z-0 opacity-40" />
      <Frame className="relative z-10 my-auto w-full max-w-md shrink-0 p-6">
        <p className="text-sm font-bold text-wood">洛克王国</p>
        <h1 className="text-3xl font-bold text-grass-deep">洛克王国智能助手</h1>
        <p className="mt-1 text-sm">配队、查资料、试着打一场。</p>
        <div className="mt-4 flex justify-around">
          <IconButton id="icon-settings" icon={LogIn} label="登录" size={48} active={panel === "login"} onClick={() => setPanel("login")} />
          <IconButton id="icon-new-chat" icon={UserPlus} label="注册" size={48} active={panel === "register"} onClick={() => setPanel("register")} />
          <IconButton id="empty-mascot" icon={Footprints} label="游客进入" tone="sky" onClick={() => onEnter({ kind: "guest", username: "游客", userId: null })} />
        </div>
        <form className="mt-4 grid gap-3" onSubmit={submit}>
          <label className="grid gap-1 text-sm font-bold">
            用户名
            <input className="rounded-full border-4 border-wood bg-white px-3 py-2" value={username} autoComplete="username" onChange={(event) => setUsername(event.target.value)} />
          </label>
          {panel !== "password" ? (
            <label className="grid gap-1 text-sm font-bold">
              密码
              <input className="rounded-full border-4 border-wood bg-white px-3 py-2" value={password} type="password" autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} />
            </label>
          ) : (
            <>
              <label className="grid gap-1 text-sm font-bold">
                旧密码
                <input className="rounded-full border-4 border-wood bg-white px-3 py-2" value={oldPassword} type="password" onChange={(event) => setOldPassword(event.target.value)} />
              </label>
              <label className="grid gap-1 text-sm font-bold">
                新密码
                <input className="rounded-full border-4 border-wood bg-white px-3 py-2" value={newPassword} type="password" onChange={(event) => setNewPassword(event.target.value)} />
              </label>
            </>
          )}
          <IconButton
            id="icon-send"
            icon={panel === "password" ? KeyRound : LogIn}
            label={busy ? "请稍候" : panel === "register" ? "注册并进入" : panel === "password" ? "更新密码" : "登录"}
            size={48}
            disabled={busy}
            type="submit"
          />
        </form>
        <button type="button" className="mt-3 text-sm font-bold text-grass-deep underline" onClick={() => setPanel(panel === "password" ? "login" : "password")}>
          {panel === "password" ? "返回登录" : "修改密码"}
        </button>
        {message ? <p className="mt-2 text-sm text-hp">{message}</p> : null}
      </Frame>
    </main>
  );
}
