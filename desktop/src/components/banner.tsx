import type { ReactNode } from "react";

/** A small inline status banner — brick for errors, forest for notices. */
export function Banner({
  kind,
  children,
}: {
  kind: "error" | "notice";
  children: ReactNode;
}) {
  const cls =
    kind === "error"
      ? "border-danger-ring bg-danger-fill text-danger"
      : "border-busy-ring bg-busy-fill text-busy";
  return (
    <div className={`mb-4 rounded-lg border px-3 py-2 text-sm ${cls}`}>
      {children}
    </div>
  );
}
