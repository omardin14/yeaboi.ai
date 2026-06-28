import type { ReactNode } from "react";

/** A small inline status banner — red for errors, green for notices. */
export function Banner({
  kind,
  children,
}: {
  kind: "error" | "notice";
  children: ReactNode;
}) {
  const cls =
    kind === "error"
      ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400";
  return (
    <div className={`mb-4 rounded border px-3 py-2 text-sm ${cls}`}>{children}</div>
  );
}
