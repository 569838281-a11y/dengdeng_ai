import { useEffect, useRef, useState } from "react";
import { Droplets, Flame, Heart, Shield, Snowflake, Sparkles, Sword, Wind, Zap } from "lucide-react";
import { api } from "../api";
import { Frame } from "../ui/Frame";
import { GameIcon } from "../ui/GameIcon";
import { IconButton } from "../ui/IconButton";
import { Portrait } from "../ui/Portrait";

const bloods = ["初始血脉", "首领血脉", ..."普通、草、火、水、光、地、冰、龙、电、毒、虫、武、翼、萌、幽、恶、机械、幻".split("、").map((name) => `${name}血脉`)];
const typeColor = {
  普通: "#c9a36a",
  草: "#7bc67e",
  火: "#f07178",
  水: "#5bb8f2",
  光: "#ffe27a",
  地: "#c9a36a",
  冰: "#d7f4ff",
  龙: "#7d6bff",
  电: "#f5c451",
  毒: "#b57bff",
  虫: "#9ccc65",
  武: "#e07a3d",
  翼: "#8fd6ff",
  萌: "#ffb7d5",
  幽: "#6d5b8a",
  恶: "#5c5346",
  机械: "#8aa0b4",
  幻: "#d7a4ff",
};
const items = [
  { name: "愿力强化", id: "item-will", icon: Sparkles },
  { name: "进化之力", id: "item-evolve", icon: Zap },
  { name: "光合治愈", id: "item-heal", icon: Heart },
];

function emptySide() {
  return { name: "", skills: ["", "", "", ""], blood: "初始血脉", item: "光合治愈", options: [] };
}

function pct(current, max) {
  if (!max) return "0%";
  return `${Math.max(0, Math.min(100, (current / max) * 100))}%`;
}

function buffIcon(label) {
  if (/物攻|魔攻|威力/.test(label)) return ["status-atk-up", Sword];
  if (/物防|魔防/.test(label)) return ["status-def-up", Shield];
  if (/速度/.test(label)) return ["status-spd-up", Wind];
  return ["status-atk-up", Sparkles];
}

function ailmentIcon(label) {
  if (label.startsWith("中毒")) return ["status-poison", Droplets];
  if (label.startsWith("灼烧")) return ["status-burn", Flame];
  if (label.startsWith("冻结")) return ["status-freeze", Snowflake];
  return ["status-poison", Droplets];
}

function Meter({ kind, value, max }) {
  return (
    <div className="ui-frame ui-frame--hp h-4 overflow-hidden bg-cream/80">
      <span
        className={`relative z-10 block h-full ${kind === "hp" ? "bg-hp" : "bg-energy"}`}
        style={{ width: pct(value, max) }}
      />
    </div>
  );
}

function Tags({ buffs = [], ailments = [] }) {
  if (!buffs.length && !ailments.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {buffs.map((item) => {
        const [id, icon] = buffIcon(item);
        return (
          <span key={item} className="inline-flex items-center gap-1 rounded-full bg-sprout px-2 py-0.5 text-[11px] font-bold">
            <GameIcon id={id} icon={icon} size={14} />
            {item}
          </span>
        );
      })}
      {ailments.map((item) => {
        const [id, icon] = ailmentIcon(item);
        return (
          <span key={item} className="inline-flex items-center gap-1 rounded-full bg-ailment/30 px-2 py-0.5 text-[11px] font-bold">
            <GameIcon id={id} icon={icon} size={14} />
            {item}
          </span>
        );
      })}
    </div>
  );
}

function Fighter({ side, align, compact = false, acting = false }) {
  const color = typeColor[String(side.blood || "").replace("血脉", "")] || "#7bc67e";
  const motion = acting ? (align === "right" ? "arena-lunge-back" : "arena-lunge-fore") : "";
  return (
    <div className={`max-w-56 ${align === "right" ? "ml-auto text-right" : ""} ${motion}`}>
      <Portrait
        name={side.photo_name || side.name}
        form={side.boss ? "boss" : "base"}
        alt={side.display_name || side.name}
        className={compact ? "h-24 w-full" : "h-36 w-full lg:h-52"}
      />
      <strong className="block">{side.display_name || side.name}</strong>
      <small className="block">
        <i className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: color }} />
        {side.trait}
      </small>
      <Meter kind="hp" value={side.hp} max={side.max_hp} />
      <Tags buffs={side.buffs} ailments={side.ailments} />
      <Meter kind="en" value={side.energy} max={side.max_energy} />
      <small>
        生命 {Math.round(side.hp)} / 能量 {side.energy}
        {side.stats ? ` / 魔防 ${Math.round(side.stats.special_defense)}` : ""}
      </small>
    </div>
  );
}

function OrderBar({ onOrder }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const question = text.trim();
    if (!question || busy) return;
    setText("");
    setBusy(true);
    try {
      const result = await api("/battle/orders", {
        method: "POST",
        timeoutMs: 180000,
        body: JSON.stringify({ question }),
      });
      onOrder?.(question, result.answer || "灯灯没听懂小洛克的意思。", result.mood || "cry");
    } catch {
      onOrder?.(question, "灯灯这会儿没接上话。", "cry");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="flex items-center gap-2" onSubmit={submit}>
      <input
        className="min-w-0 flex-1 rounded-full border-4 border-wood bg-white px-3 py-2 text-grass-deep"
        placeholder="跟灯灯说一句，比如仓库里有哪些精灵"
        value={text}
        onChange={(event) => setText(event.target.value)}
        disabled={busy}
      />
      <button type="submit" disabled={busy} className="rounded-full border-4 border-wood bg-honey px-4 py-2 font-bold text-grass-deep disabled:opacity-60">
        {busy ? "灯灯在听" : "告诉灯灯"}
      </button>
    </form>
  );
}

export function BattleBox({ onLog, onOrder }) {
  const [roster, setRoster] = useState([]);
  const [battle, setBattle] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [caption, setCaption] = useState("");
  const [player, setPlayer] = useState(emptySide);
  const [enemy, setEnemy] = useState(emptySide);

  useEffect(() => {
    api("/pokemon").then(setRoster).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    let cancel = false;
    async function load(name, setSide) {
      if (!name) {
        setSide((row) => ({ ...row, options: [], skills: ["", "", "", ""] }));
        return;
      }
      const options = await api(`/pokemon/${encodeURIComponent(name)}/skills`);
      if (cancel) return;
      const usable = options.filter((skill) => skill.name !== "聚能");
      const known = new Set(usable.map((skill) => skill.name));
      setSide((row) => {
        const keep = row.skills.every((skill) => !skill || known.has(skill)) && row.skills.filter(Boolean).length === 4;
        return { ...row, options: usable, skills: keep ? row.skills : ["", "", "", ""] };
      });
    }
    load(player.name, setPlayer).catch((err) => setError(err.message));
    return () => {
      cancel = true;
    };
  }, [player.name]);

  useEffect(() => {
    let cancel = false;
    async function load() {
      if (!enemy.name) {
        setEnemy((row) => ({ ...row, options: [], skills: ["", "", "", ""] }));
        return;
      }
      const options = await api(`/pokemon/${encodeURIComponent(enemy.name)}/skills`);
      if (cancel) return;
      const usable = options.filter((skill) => skill.name !== "聚能");
      const known = new Set(usable.map((skill) => skill.name));
      setEnemy((row) => {
        const keep = row.skills.every((skill) => !skill || known.has(skill)) && row.skills.filter(Boolean).length === 4;
        return { ...row, options: usable, skills: keep ? row.skills : ["", "", "", ""] };
      });
    }
    load().catch((err) => setError(err.message));
    return () => {
      cancel = true;
    };
  }, [enemy.name]);

  function pickSkills(options, blood) {
    const pool = options.filter((skill) => skill.name !== "聚能");
    const element = blood.endsWith("血脉") ? blood.slice(0, -2) : "";
    const allowBlood = element && element !== "初始" && element !== "首领";
    const normals = pool.filter((skill) => skill.source !== "血脉");
    const bloodSkills = allowBlood ? pool.filter((skill) => skill.source === "血脉" && skill.blood_type === element) : [];
    const chosen = [];
    const bag = [...normals];
    if (bloodSkills.length && Math.random() < 0.5) {
      chosen.push(bloodSkills[Math.floor(Math.random() * bloodSkills.length)].name);
    }
    for (let index = bag.length - 1; index > 0; index -= 1) {
      const swap = Math.floor(Math.random() * (index + 1));
      [bag[index], bag[swap]] = [bag[swap], bag[index]];
    }
    for (const skill of bag) {
      if (chosen.length === 4) break;
      if (!chosen.includes(skill.name)) chosen.push(skill.name);
    }
    while (chosen.length < 4) chosen.push("");
    return chosen.slice(0, 4);
  }

  function pickBlood(mon) {
    const typed = (mon.types || []).map((name) => `${name}血脉`);
    const choices = typed.length ? [...typed, "初始血脉"] : ["初始血脉"];
    if (mon.can_boss && Math.random() < 0.2) choices.push("首领血脉");
    return choices[Math.floor(Math.random() * choices.length)];
  }

  async function fillSide(mon) {
    const options = await api(`/pokemon/${encodeURIComponent(mon.name)}/skills`);
    const usable = options.filter((skill) => skill.name !== "聚能");
    const blood = pickBlood(mon);
    const item = items[Math.floor(Math.random() * items.length)].name;
    return {
      name: mon.name,
      options: usable,
      skills: pickSkills(usable, blood),
      blood,
      item,
    };
  }

  async function autoFill() {
    if (!roster.length) return;
    setError("");
    setBusy(true);
    try {
      const left = roster[Math.floor(Math.random() * roster.length)];
      let right = roster[Math.floor(Math.random() * roster.length)];
      if (roster.length > 1) {
        while (right.name === left.name) right = roster[Math.floor(Math.random() * roster.length)];
      }
      const [playerSide, enemySide] = await Promise.all([fillSide(left), fillSide(right)]);
      setPlayer(playerSide);
      setEnemy(enemySide);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    setError("");
    setBusy(true);
    try {
      const result = await api("/battle/start", {
        method: "POST",
        timeoutMs: 20000,
        body: JSON.stringify({
          player: { name: player.name, skills: player.skills, blood: player.blood, item: player.item },
          enemy: { name: enemy.name, skills: enemy.skills, blood: enemy.blood, item: enemy.item },
        }),
      });
      setBattle(result.battle);
      setCaption(result.battle.note || "");
      onLog?.(result.narration || result.battle.note);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function send(body) {
    if (!battle || battle.over) return;
    setError("");
    try {
      const result = await api(`/battle/${battle.battle_id}/move`, {
        method: "POST",
        timeoutMs: 20000,
        body: JSON.stringify(body),
      });
      setBattle(result.battle);
      setCaption((result.lines || []).slice(-1)[0] || "");
      onLog?.(result.narration || (result.lines || []).join("\n"));
    } catch (err) {
      setError(err.message);
    }
  }

  const side = battle?.player;
  const itemLocked = !side || battle.over || (side.item_left || 0) <= 0
    || (side.item === "进化之力" && (side.blood !== "首领血脉" || !side.can_boss || side.boss))
    || (side.item === "愿力强化" && (side.blood === "初始血脉" || side.blood === "首领血脉" || (side.item_cd || 0) > 0));
  const carried = items.find((item) => item.name === side?.item) || items[2];

  function skillLocked(skill) {
    if (!battle || battle.over) return true;
    if (skill.name === "愿力冲击") return false;
    return skill.cost > battle.player.energy;
  }

  if (!battle) {
    return (
      <section className="grid gap-3">
        <p>这句话不占出招回合。</p>
        <OrderBar onOrder={onOrder} />
        <p>先选双方的精灵、正好 4 个技能、血脉和道具，确认后再开战。</p>
        <div className="grid gap-3 lg:grid-cols-2">
          {[{ key: "己方", row: player, setRow: setPlayer }, { key: "敌方", row: enemy, setRow: setEnemy }].map((entry) => (
            <Frame key={entry.key} variant="battle" className="p-3">
              <legend className="font-bold">{entry.key}</legend>
              <select className="mt-2 w-full rounded-full border-4 border-wood bg-white px-3 py-2 text-grass-deep" value={entry.row.name} onChange={(event) => entry.setRow((row) => ({ ...row, name: event.target.value }))}>
                <option value="">选择精灵</option>
                {roster.map((mon) => (
                  <option key={mon.name} value={mon.name}>{mon.name}</option>
                ))}
              </select>
              {entry.row.skills.map((skill, index) => (
                <select
                  key={index}
                  className="mt-2 w-full rounded-full border-4 border-wood bg-white px-3 py-2 text-grass-deep"
                  value={skill}
                  onChange={(event) => entry.setRow((row) => {
                    const skills = [...row.skills];
                    skills[index] = event.target.value;
                    return { ...row, skills };
                  })}
                >
                  <option value="">技能 {index + 1}</option>
                  {entry.row.options.map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.name}（{option.source}，能耗 {option.cost}）
                    </option>
                  ))}
                </select>
              ))}
              <label className="mt-2 flex items-center gap-2 text-sm font-bold">
                <i className="inline-block h-3 w-3 rounded-full" style={{ background: typeColor[entry.row.blood.replace("血脉", "")] || "#7bc67e" }} />
                {entry.row.blood}
              </label>
              <select className="mt-1 w-full rounded-full border-4 border-wood bg-white px-3 py-2 text-grass-deep" value={entry.row.blood} onChange={(event) => entry.setRow((row) => ({ ...row, blood: event.target.value }))}>
                {bloods.map((blood) => <option key={blood}>{blood}</option>)}
              </select>
              <select className="mt-2 w-full rounded-full border-4 border-wood bg-white px-3 py-2 text-grass-deep" value={entry.row.item} onChange={(event) => entry.setRow((row) => ({ ...row, item: event.target.value }))}>
                {items.map((item) => <option key={item.name}>{item.name}</option>)}
              </select>
            </Frame>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <IconButton id="icon-yijianpeizhao" icon={Sparkles} label={busy ? "配招中" : "一键配招"} size={56} disabled={busy || !roster.length} onClick={autoFill} />
          <IconButton id="icon-mode-battle" icon={Sword} label={busy ? "开战中" : "确认并开战"} size={56} disabled={busy} onClick={start} />
        </div>
        {error ? <p className="text-sm text-hp">{error}</p> : null}
      </section>
    );
  }

  return (
    <section className="grid gap-3">
      <p>这句话不占出招回合。</p>
      <OrderBar onOrder={onOrder} />
      <div className="arena-bg relative min-h-80 overflow-hidden rounded-[1.6rem] border-4 border-wood p-4">
        <Fighter side={battle.enemy} align="right" />
        <div className="mt-6">
          <Fighter side={battle.player} align="left" />
        </div>
        {caption ? <p className="relative z-10 mt-3 rounded-full bg-cream/85 px-3 py-1 text-sm font-bold">{caption}</p> : null}
      </div>
      <div className="grid grid-cols-3 justify-items-center gap-3 lg:grid-cols-6">
        {battle.player.skills.map((skill) => (
          <button key={skill.name} type="button" disabled={skillLocked(skill)} onClick={() => send({ action: "skill", skill: skill.name, item: "" })} className="icon-pop flex flex-col items-center gap-1 disabled:grayscale">
            <span className="skill-orb relative grid place-items-center overflow-hidden rounded-full border-4 border-[#c9a36a] bg-honey/80">
              <GameIcon id="skill-slot" icon={Sparkles} size={28} />
            </span>
            <span className="max-w-24 text-center text-xs font-bold leading-tight">{skill.name === "愿力冲击" ? "愿力冲击" : skill.name} · {skill.cost}</span>
          </button>
        ))}
        <IconButton id="icon-charge" icon={Zap} label="聚能 · 0" size={56} disabled={battle.over} onClick={() => send({ action: "charge", skill: "", item: "" })} />
      </div>
      <div className="flex justify-center">
        <IconButton
          id={carried.id}
          icon={carried.icon}
          label={`${battle.player.item} · 剩余 ${battle.player.item_left}${battle.player.item_cd ? ` · 冷却 ${battle.player.item_cd}` : ""}`}
          tone="grass"
          disabled={itemLocked}
          onClick={() => send({ action: "item", skill: "", item: battle.player.item })}
        />
      </div>
      {error ? <p className="text-sm text-hp">{error}</p> : null}
    </section>
  );
}

export function TrialReplay({ trial, onFinish }) {
  const frames = trial?.frames || [];
  const pace = trial?.pace_ms || 2000;
  const [index, setIndex] = useState(trial?.played ? Math.max(frames.length - 1, 0) : 0);
  const [finished, setFinished] = useState(Boolean(trial?.played));
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;

  useEffect(() => {
    if (finished || !frames.length) return undefined;
    if (index >= frames.length - 1) {
      setFinished(true);
      finishRef.current?.();
      return undefined;
    }
    const timer = setTimeout(() => setIndex((current) => current + 1), pace);
    return () => clearTimeout(timer);
  }, [finished, frames.length, index, pace]);

  const frame = frames[Math.min(index, Math.max(frames.length - 1, 0))] || null;
  const battle = frame?.battle;
  if (!battle) return null;
  const line = frame.line || trial.intro || "";
  const playerActing = line.startsWith("己方");
  const enemyActing = line.startsWith("敌方");
  return (
    <div className="arena-bg relative mt-3 overflow-hidden rounded-[1.4rem] border-4 border-wood p-3">
      <Fighter key={`enemy-${index}`} side={battle.enemy} align="right" compact acting={enemyActing} />
      <div className="mt-3">
        <Fighter key={`player-${index}`} side={battle.player} align="left" compact acting={playerActing} />
      </div>
      {line ? <p className="relative z-10 mt-3 rounded-full bg-cream/85 px-3 py-1 text-sm font-bold">{line}</p> : null}
    </div>
  );
}
