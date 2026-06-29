import { forwardRef } from "react";
import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";
import { cx } from "@/components/ui/cx";

const FIELD =
  "rounded-lg border border-line-strong bg-surface-raised px-2 py-1 text-sm text-ink placeholder:text-ink-faint outline-none transition-shadow focus:border-burgundy focus:ring-2 focus:ring-burgundy/25";

/** Text input on the cream surface with a burgundy focus ring. */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cx(FIELD, className)} {...rest} />;
  },
);

/** Select with the same field treatment. */
export function Select({
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(FIELD, "pr-6", className)} {...rest}>
      {children}
    </select>
  );
}
