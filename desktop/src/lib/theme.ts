// Light "Parchment" is the default; "noir" is the Burgundy Noir dark variant.
// The choice is written to <html data-theme> (read by the CSS token layer) and
// persisted so it survives reloads.

import { useEffect, useState } from "react";

export type Theme = "light" | "noir";

const KEY = "yb-theme";

function read(): Theme {
  try {
    return localStorage.getItem(KEY) === "noir" ? "noir" : "light";
  } catch {
    return "light";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "noir") root.setAttribute("data-theme", "noir");
  else root.removeAttribute("data-theme");
}

/** Theme state bound to <html data-theme> + localStorage, with a toggle. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(read);

  useEffect(() => {
    apply(theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // Persistence is best-effort; the in-memory choice still applies.
    }
  }, [theme]);

  return {
    theme,
    toggle: () => setTheme((t) => (t === "noir" ? "light" : "noir")),
  };
}
