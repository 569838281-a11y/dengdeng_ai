import { useState } from "react";

export function GameIcon({ id, icon: Icon, size = 24, className = "" }) {
  const [failed, setFailed] = useState(false);
  const name = String(id || "").replace(/\.png$/i, "");
  if (!name || failed || !Icon) {
    return Icon ? <Icon size={size} strokeWidth={2} className={className} aria-hidden="true" /> : null;
  }
  return (
    <img
      src={`/ui/${name}.png`}
      alt=""
      width={size}
      height={size}
      style={{ width: size, height: size }}
      className={`object-contain ${className}`}
      onError={() => setFailed(true)}
    />
  );
}
