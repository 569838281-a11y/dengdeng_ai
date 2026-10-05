const BASE = "/api/v1";

export async function api(path, options = {}) {
  const { timeoutMs = 15000, headers, ...rest } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(BASE + path, {
      ...rest,
      headers: { "Content-Type": "application/json", ...(headers || {}) },
      signal: rest.signal || controller.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("接口没有在限定时间内响应。请确认 API（8000）已经启动，并重启一次后再试。");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail.join("；")
      : detail || data.message || response.statusText;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

export function photoUrl(name, form) {
  const query = form && form !== "base" ? `?form=${encodeURIComponent(form)}` : "";
  return `${BASE}/photo/${encodeURIComponent(name)}${query}`;
}

export function parseTeam(answer) {
  if (!answer || !answer.includes("队伍配置为")) return null;
  const parts = answer.split("选取的理由");
  const head = parts[0];
  const reason = parts[1] ? parts[1].replace(/^是/, "").trim() : "";
  const itemMatch = head.match(/战斗道具：【([^】]+)】/);
  const members = [];
  for (const line of head.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("- ")) continue;
    const body = trimmed.slice(2);
    const name = body.split("｜")[0].trim();
    const tags = ((body.match(/标签：([^｜]+)/) || [])[1] || "").split("、").filter(Boolean);
    const blood = ((body.match(/血脉：([^｜]+)/) || [])[1] || "").trim();
    const skillText = (body.match(/技能：(.+)$/) || [])[1] || "";
    const skills = skillText
      .split("、")
      .map((raw) => raw.trim())
      .filter(Boolean)
      .map((raw) => ({ name: raw.split("（")[0], raw, source: "" }));
    if (name) members.push({ name, tags, blood, skills });
  }
  if (!members.length) return null;
  return { members, item: itemMatch ? itemMatch[1] : "", reason, issues: [] };
}
