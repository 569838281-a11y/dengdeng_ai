function sparkleCursor(fill) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
    <circle cx="16" cy="16" r="14" fill="${fill}" stroke="#2F9B64" stroke-width="2"/>
    <path d="M16 6l1.4 5.2L22.6 13 17.4 14.4 16 19.6 14.6 14.4 9.4 13l5.2-1.8L16 6z" fill="#FFF8E7"/>
    <circle cx="23" cy="8" r="1.4" fill="#FFE27A"/>
  </svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function probe(url) {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(true);
    image.onerror = () => resolve(false);
    image.src = url;
  });
}

export async function installCursors() {
  const root = document.documentElement;
  const [hasDefault, hasPointer] = await Promise.all([
    probe("/ui/cursor-default.png"),
    probe("/ui/cursor-pointer.png"),
  ]);
  if (!hasDefault) {
    root.style.setProperty("--cursor-default", `url("${sparkleCursor("#7BC67E")}") 16 16, auto`);
  }
  if (!hasPointer) {
    root.style.setProperty("--cursor-pointer", `url("${sparkleCursor("#F5C451")}") 16 16, pointer`);
  }
}
