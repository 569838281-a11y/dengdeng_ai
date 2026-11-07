import { useEffect, useState } from "react";
import { PawPrint } from "lucide-react";
import { photoUrl } from "../api";

export function Portrait({ name, form = "base", alt = "", className = "", fallback = "" }) {
  const [source, setSource] = useState(name);
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    setSource(name);
    setBroken(false);
  }, [name, form]);
  if (!source || broken) {
    return (
      <div className={`grid place-items-center rounded-3xl bg-sprout text-grass-deep ${className}`}>
        <PawPrint size={42} />
      </div>
    );
  }
  const shownForm = fallback && source === fallback ? "base" : form;
  return (
    <img
      src={photoUrl(source, shownForm)}
      alt={alt || source}
      className={`object-contain ${className}`}
      onError={() => {
        if (fallback && source !== fallback) {
          setSource(fallback);
          return;
        }
        setBroken(true);
      }}
    />
  );
}
