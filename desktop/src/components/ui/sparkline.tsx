/**
 * A whisper-quiet inline trend line — shows the *shape* of a recent series, not
 * an alarm. Normalized to `[0, max]` so a steady low value stays calmly near the
 * baseline and only real movement lifts the line. Decorative (`aria-hidden`);
 * the numeric value rendered beside it is the accessible source of truth.
 */
export function Sparkline({
  data,
  width = 52,
  height = 16,
}: {
  data: number[];
  width?: number;
  height?: number;
}) {
  if (data.length < 2) {
    // Nothing to trend yet — a flat baseline reads calmer than an empty gap.
    const y = height - 1;
    return (
      <svg width={width} height={height} aria-hidden className="shrink-0">
        <line x1={0} y1={y} x2={width} y2={y} stroke="var(--line-strong)" strokeWidth={1} />
      </svg>
    );
  }
  const max = Math.max(...data, 1);
  const pad = 1.5;
  const usable = height - pad * 2;
  const step = width / (data.length - 1);
  const points = data
    .map((v, i) => {
      const x = i * step;
      const y = pad + (usable - (Math.max(0, v) / max) * usable);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} aria-hidden className="shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke="var(--ink-faint)"
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
