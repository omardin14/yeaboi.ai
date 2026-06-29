import type { Port } from "@/lib/bindings/Port";

const CHIP_CLS = "rounded-md bg-surface-sunken px-1.5 font-mono text-xs text-idle";

/** A single listening-port chip; a button when it can be freed. */
export function PortChip({
  port,
  onFreePort,
}: {
  port: Port;
  onFreePort?: (port: Port) => void;
}) {
  const label = `:${port.number}`;
  const title = `pid ${port.pid} · ${port.state}`;
  if (!onFreePort) {
    return (
      <span title={title} className={CHIP_CLS}>
        {label}
      </span>
    );
  }
  return (
    <button
      type="button"
      aria-label={`Free port ${port.number}`}
      title={`Free ${label} (${title})`}
      onClick={(e) => {
        e.stopPropagation();
        onFreePort(port);
      }}
      className={`${CHIP_CLS} transition-colors hover:bg-danger-fill hover:text-danger`}
    >
      {label}
    </button>
  );
}

/** A wrapping row of port chips. */
export function PortChips({
  ports,
  onFreePort,
}: {
  ports: Port[];
  onFreePort?: (port: Port) => void;
}) {
  return (
    <span className="flex flex-wrap gap-1">
      {ports.map((p) => (
        <PortChip key={`${p.pid}:${p.number}`} port={p} onFreePort={onFreePort} />
      ))}
    </span>
  );
}
