import { Portrait } from "../ui/Portrait";
import { Frame } from "../ui/Frame";

export function TeamCards({ team }) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-6">
        {team.members.map((member) => (
          <Frame key={member.name} className="bg-[#fbfff8] p-2">
            <Portrait name={member.name} alt={member.name} className="h-28 w-full rounded-2xl bg-sky/40" />
            <h3 className="mt-1 text-sm font-bold">{member.name}</h3>
            <p className="text-xs">{(member.tags || []).join("、") || "未提供"}</p>
            <p className="text-xs">血脉：{member.blood || "未提供"}</p>
            <ul className="mt-1 text-xs">
              {(member.skills || []).map((skill) => (
                <li key={skill.raw || skill.name}>
                  {skill.raw || skill.name}
                  {skill.cost != null ? ` · 能耗 ${skill.cost}` : ""}
                </li>
              ))}
            </ul>
          </Frame>
        ))}
      </div>
      {team.item ? <p className="mt-2 text-sm">战斗道具：【{team.item}】</p> : null}
      {team.reason ? <p className="text-sm">选取的理由是{team.reason}</p> : null}
      {team.issues?.length ? (
        <ul className="mt-1 list-disc pl-5 text-sm text-hp">
          {team.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
