import type { ReactNode } from "react";
import { cx } from "@/components/ui/cx";

type Tone = "surface" | "sunken" | "outline";

const TONE: Record<Tone, string> = {
  surface: "bg-surface border-line shadow-[0_1px_2px_rgba(42,26,18,0.06)]",
  sunken: "bg-surface-sunken border-line-strong",
  outline: "bg-transparent border-line",
};

/**
 * A rounded panel — the literal "pane" of the single pane of glass. `tone`
 * picks the surface; `pad` the inner padding. Anything else passes through.
 */
export function Card({
  tone = "surface",
  pad = "md",
  className,
  children,
}: {
  tone?: Tone;
  pad?: "none" | "sm" | "md" | "lg";
  className?: string;
  children: ReactNode;
}) {
  const padding =
    pad === "none"
      ? ""
      : pad === "sm"
        ? "p-3"
        : pad === "lg"
          ? "p-6"
          : "p-4";
  return (
    <div className={cx("rounded-2xl border", TONE[tone], padding, className)}>
      {children}
    </div>
  );
}
