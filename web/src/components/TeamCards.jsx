import { useState } from "react";
import { Portrait } from "../ui/Portrait";

function skillLabel(skill) {
  return skill.raw || skill.name || "";
}

export function TeamCards({ team, onRevise }) {
  const [members, setMembers] = useState(team.members || []);
  const [item, setItem] = useState(team.item || "");
  const [draftSkill, setDraftSkill] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  function moveMember(from, to) {
    if (from === to || to < 0 || to >= members.length) return;
    const next = members.slice();
    const [row] = next.splice(from, 1);
    next.splice(to, 0, row);
    setMembers(next);
  }

  function moveSkill(fromMember, skillIndex, toMember) {
    if (fromMember === toMember) return;
    const next = members.map((member) => ({ ...member, skills: (member.skills || []).slice() }));
    const [skill] = next[fromMember].skills.splice(skillIndex, 1);
    if (!skill) return;
    next[toMember].skills = [...(next[toMember].skills || []), skill].slice(0, 4);
    setMembers(next);
  }

  function addSkill(toMember, name) {
    const label = name.trim();
    if (!label) return;
    const next = members.map((member) => ({ ...member, skills: (member.skills || []).slice() }));
    next[toMember].skills = [...next[toMember].skills, { name: label, raw: label }].slice(0, 4);
    setMembers(next);
    setDraftSkill("");
  }

  function setBlood(index, blood) {
    const next = members.slice();
    next[index] = { ...next[index], blood };
    setMembers(next);
  }

  async function commit() {
    if (!onRevise) return;
    setBusy(true);
    setNote("");
    try {
      const result = await onRevise({ members, item, reason: team.reason || "" });
      const issues = result?.issues || [];
      setNote(issues.length ? issues.join("；") : "灯灯收下了这套改动。");
    } catch (error) {
      setNote(error.message || "这套还没交上去。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="team-sheet mt-2 overflow-x-auto">
      <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b-2 border-grass text-grass-deep">
            <th className="px-2 py-1 font-bold">图片</th>
            <th className="px-2 py-1 font-bold">精灵</th>
            <th className="px-2 py-1 font-bold">血脉</th>
            <th className="px-2 py-1 font-bold">四招</th>
            <th className="px-2 py-1 font-bold">道具</th>
          </tr>
        </thead>
        <tbody>
          {members.map((member, index) => (
            <tr
              key={`${member.name}-${index}`}
              className="border-b border-grass/40 align-top"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const raw = event.dataTransfer.getData("text/plain");
                if (!raw) return;
                const payload = JSON.parse(raw);
                if (payload.kind === "member") moveMember(payload.index, index);
                if (payload.kind === "skill") moveSkill(payload.from, payload.index, index);
                if (payload.kind === "new-skill") addSkill(index, payload.name);
              }}
            >
              <td className="px-2 py-2">
                <div
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData("text/plain", JSON.stringify({ kind: "member", index }));
                  }}
                  className="cursor-grab"
                >
                  <Portrait
                    name={member.name}
                    fallback="dengdeng"
                    alt={member.name}
                    className="h-16 w-16 rounded-xl bg-sky/40"
                  />
                </div>
              </td>
              <td className="px-2 py-2 font-bold">{member.name}</td>
              <td className="px-2 py-2">
                <input
                  className="w-24 rounded border border-grass/50 bg-cream px-1"
                  value={member.blood || ""}
                  onChange={(event) => setBlood(index, event.target.value)}
                />
              </td>
              <td className="px-2 py-2">
                <div className="flex flex-wrap gap-1">
                  {(member.skills || []).map((skill, skillIndex) => (
                    <span
                      key={`${skillLabel(skill)}-${skillIndex}`}
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData(
                          "text/plain",
                          JSON.stringify({ kind: "skill", from: index, index: skillIndex }),
                        );
                      }}
                      className="cursor-grab rounded-full border border-grass px-2"
                    >
                      {skillLabel(skill)}
                    </span>
                  ))}
                </div>
              </td>
              <td className="px-2 py-2">{index === 0 ? (
                <input
                  className="w-24 rounded border border-grass/50 bg-cream px-1"
                  value={item}
                  onChange={(event) => setItem(event.target.value)}
                />
              ) : item || "未提供"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <input
          className="rounded border border-grass/50 bg-cream px-2 py-1"
          placeholder="拖一招到某只身上"
          value={draftSkill}
          onChange={(event) => setDraftSkill(event.target.value)}
        />
        <span
          draggable={Boolean(draftSkill.trim())}
          onDragStart={(event) => {
            event.dataTransfer.setData("text/plain", JSON.stringify({ kind: "new-skill", name: draftSkill }));
          }}
          className="cursor-grab rounded-full border border-honey px-2"
        >
          {draftSkill.trim() || "新招"}
        </span>
        <button type="button" className="rounded-full border-2 border-grass px-3 py-1" disabled={busy} onClick={commit}>
          {busy ? "灯灯在核对" : "交给灯灯核对"}
        </button>
        {note ? <span>{note}</span> : null}
      </div>
    </div>
  );
}
