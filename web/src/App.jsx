import { useEffect, useState } from "react";
import { AuthScreen } from "./components/AuthScreen";
import { ChatApp } from "./components/ChatApp";

export default function App() {
  const [auth, setAuth] = useState(null);

  useEffect(() => {
    const raw = sessionStorage.getItem("roco-auth");
    if (!raw) return;
    try {
      setAuth(JSON.parse(raw));
    } catch {
      sessionStorage.removeItem("roco-auth");
    }
  }, []);

  function enter(value) {
    sessionStorage.setItem("roco-auth", JSON.stringify(value));
    setAuth(value);
  }

  function leave() {
    sessionStorage.removeItem("roco-auth");
    setAuth(null);
  }

  if (!auth) return <AuthScreen onEnter={enter} />;
  return <ChatApp auth={auth} onLeave={leave} onEnter={enter} />;
}
