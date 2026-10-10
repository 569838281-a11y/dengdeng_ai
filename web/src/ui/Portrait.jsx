import { useEffect, useState } from "react";
import { PawPrint } from "lucide-react";
import { photoUrl } from "../api";

export function Portrait({ name, form = "base", alt = "", className = "" }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [name, form]);
  if (!name || broken) {
    return (
      <div className={`grid place-items-center rounded-3xl bg-sprout text-grass-deep ${className}`}>
        <PawPrint size={42} />
      </div>
    );
  }
  return (
    <img
      src={photoUrl(name, form)}
      alt={alt || name}
      className={`object-contain ${className}`}
      onError={() => setBroken(true)}
    />
  );
}
