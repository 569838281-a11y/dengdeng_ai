import { Lock } from "lucide-react";
import { GameIcon } from "./GameIcon";

const tones = {
  grass: "bg-grass text-grass-deep border-grass-deep",
  honey: "bg-honey text-[#8a5a12] border-[#c9a36a]",
  sky: "bg-sky text-[#1d628c] border-[#7eb7de]",
  cream: "bg-cream text-grass-deep border-wood",
};

function circleSpec(size) {
  if (size >= 32) return { diameter: 64, glyph: 28 };
  return { diameter: 52, glyph: 24 };
}

export function IconButton({
  id,
  icon,
  label,
  size = 24,
  tone = "grass",
  disabled = false,
  active = false,
  onClick,
  type = "button",
  className = "",
}) {
  const name = String(id || "").replace(/\.png$/i, "");
  const sticker = name.startsWith("icon-");
  const { diameter, glyph } = circleSpec(size);
  const lock = disabled ? <Lock size={14} strokeWidth={2} className="absolute -right-0.5 -top-0.5 rounded-full bg-white p-0.5 text-stone-500" /> : null;

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`icon-pop inline-flex flex-col items-center gap-1 bg-transparent p-0 ${disabled ? "grayscale" : ""} ${className}`}
    >
      {sticker ? (
        <span className={`icon-sticker relative grid place-items-center ${active ? "icon-sticker--active" : ""}`}>
          <GameIcon id={id} icon={icon} size={size} />
          {lock}
        </span>
      ) : (
        <span
          className={`relative grid place-items-center overflow-hidden rounded-full border-4 shadow-[0_4px_0_rgb(47_155_100_/_0.25)] ${tones[tone] || tones.grass} ${
            disabled ? "bg-stone-300 text-stone-500 border-stone-400" : ""
          }`}
          style={{ width: diameter, height: diameter }}
        >
          <GameIcon id={id} icon={icon} size={glyph} />
          {lock}
        </span>
      )}
      {label ? <span className="max-w-24 text-center text-xs font-bold leading-tight">{label}</span> : null}
    </button>
  );
}
