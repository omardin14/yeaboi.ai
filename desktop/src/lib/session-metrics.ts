// Smooths the per-tick CPU/memory readings so the Monitor stops flickering.
//
// The snapshot streams every ~1.5s and `cpu_pct` is a raw per-tick delta, so
// the bare number jumps around. We keep a short rolling history per session id
// (for a trend sparkline) plus an EMA (for a steady displayed value). State
// lives in a ref so it survives the per-frame re-renders; it's ingested once
// per snapshot frame (guarded by the frame stamp) and pruned when sessions go.

import { useEffect, useRef, useCallback } from "react";
import type { Snapshot } from "@/lib/bindings/Snapshot";

/** How many samples the sparkline remembers. */
const CAP = 16;
/** EMA window; α = 2/(N+1). Larger N = calmer/slower. */
const EMA_N = 8;
const ALPHA = 2 / (EMA_N + 1);

type Hist = {
  cpu: number[];
  mem: number[];
  emaCpu: number | null;
  emaMem: number | null;
};

export type Series = { value: number | null; history: number[] };
export type SessionMetric = { cpu: Series; mem: Series };

function push(buf: number[], v: number) {
  buf.push(v);
  if (buf.length > CAP) buf.shift();
}

function ema(prev: number | null, sample: number): number {
  return prev == null ? sample : ALPHA * sample + (1 - ALPHA) * prev;
}

/**
 * Returns a stable `getMetric(id)` accessor backed by smoothed history. Call
 * once in the Monitor; rows read it during render (one frame of lag at most,
 * imperceptible at a 1.5s cadence).
 */
export function useSessionMetrics(
  snapshot: Snapshot | null,
): (id: string) => SessionMetric | undefined {
  const histRef = useRef<Map<string, Hist>>(new Map());
  const lastFrameRef = useRef<number>(-1);

  useEffect(() => {
    if (!snapshot) return;
    // One ingest per real frame — the stamp guards StrictMode double-invokes
    // and the initial getSnapshot()+first stream frame landing on equal stamps.
    if (snapshot.generated_at_ms === lastFrameRef.current) return;
    lastFrameRef.current = snapshot.generated_at_ms;

    const hist = histRef.current;
    const live = new Set<string>();
    for (const s of snapshot.sessions) {
      live.add(s.id);
      const ps = s.proc_stats;
      // No live process (e.g. a remote Codex thread): never push 0 — that would
      // poison the average. Leave history untouched so it reads "—".
      if (!ps) continue;
      let h = hist.get(s.id);
      if (!h) {
        h = { cpu: [], mem: [], emaCpu: null, emaMem: null };
        hist.set(s.id, h);
      }
      push(h.cpu, ps.cpu_pct);
      push(h.mem, ps.mem_bytes);
      h.emaCpu = ema(h.emaCpu, ps.cpu_pct);
      h.emaMem = ema(h.emaMem, ps.mem_bytes);
    }
    // Drop history for sessions that vanished.
    for (const id of hist.keys()) {
      if (!live.has(id)) hist.delete(id);
    }
  }, [snapshot]);

  return useCallback((id: string): SessionMetric | undefined => {
    const h = histRef.current.get(id);
    if (!h) return undefined;
    return {
      cpu: { value: h.emaCpu, history: h.cpu },
      mem: { value: h.emaMem, history: h.mem },
    };
  }, []);
}
