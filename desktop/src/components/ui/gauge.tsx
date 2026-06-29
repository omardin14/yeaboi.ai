import { heatVar } from "@/lib/format";

/**
 * The signature element: an analog gauge ring for a 0–1 value (context %, cpu).
 * The arc fills proportionally and colors by the heat ramp. A `null` value
 * renders a muted, dashed "no reading" ring. Same concentric-arc shape as the
 * logo mark.
 */
export function Gauge({
  value,
  size = 22,
  title,
}: {
  value: number | null | undefined;
  size?: number;
  title?: string;
}) {
  const known = value != null && Number.isFinite(value);
  const pct = known ? Math.max(0, Math.min(1, value as number)) : 0;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      role="img"
      aria-label={title ?? (known ? `${Math.round(pct * 100)}%` : "no reading")}
      className="shrink-0 -rotate-90"
    >
      <circle
        cx="18"
        cy="18"
        r="15.5"
        fill="none"
        stroke="var(--line-strong)"
        strokeWidth="3"
        strokeDasharray={known ? undefined : "3 4"}
        pathLength={100}
      />
      {known && (
        <circle
          cx="18"
          cy="18"
          r="15.5"
          fill="none"
          stroke={heatVar(value)}
          strokeWidth="3"
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${pct * 100} 100`}
        />
      )}
    </svg>
  );
}
