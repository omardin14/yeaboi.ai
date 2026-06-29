import type { ButtonHTMLAttributes } from "react";
import { cx } from "@/components/ui/cx";

type Variant = "primary" | "outline" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-burgundy text-on-burgundy hover:bg-burgundy-bright border border-transparent",
  outline:
    "border border-line-strong text-ink-soft hover:bg-surface-sunken bg-transparent",
  ghost: "border border-transparent text-ink-muted hover:bg-surface-sunken",
  danger:
    "bg-danger text-on-burgundy hover:opacity-90 border border-transparent",
};

const SIZE: Record<Size, string> = {
  sm: "px-2 py-1 text-xs",
  md: "px-3 py-1.5 text-sm",
};

/** The one button. Variants map to the burgundy/earth palette; tokens only. */
export function Button({
  variant = "outline",
  size = "sm",
  className,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
}) {
  return (
    <button
      type={type}
      className={cx(
        "inline-flex items-center justify-center gap-1 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    />
  );
}
