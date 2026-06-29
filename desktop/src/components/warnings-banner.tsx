/**
 * Renders non-fatal collector degradations (the snapshot's `warnings`) in an
 * ochre banner. Nothing renders when there are none — this is the primary
 * channel telling the user the monitor is partially blind.
 */
export function WarningsBanner({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="mb-4 rounded-lg border border-needs-ring bg-needs-fill px-3 py-2 text-xs text-needs">
      {warnings.map((w) => (
        <div key={w}>{w}</div>
      ))}
    </div>
  );
}
