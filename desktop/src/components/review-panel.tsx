import { useEffect, useRef, useState } from "react";
import type { UnlistenFn } from "@tauri-apps/api/event";
import type { Finding } from "@/lib/bindings/Finding";
import type { Severity } from "@/lib/bindings/Severity";
import type { AgentProgress } from "@/lib/bindings/AgentProgress";
import { cancelReview, reviewPr, subscribeReviewProgress } from "@/lib/api";
import { Banner } from "@/components/banner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { severityBadgeClass } from "@/lib/format";

const SEVERITY_ORDER: Severity[] = ["Critical", "Important", "Suggestion", "Info"];

function progressLine(p: AgentProgress): string {
  const prefix = `${p.provider} · ${p.category}`;
  if ("Done" in p.status) {
    return `${prefix} — ${p.status.Done} finding(s)`;
  }
  return `${prefix} — failed: ${p.status.Failed}`;
}

/** Runs a multi-agent review for one PR and shows progress + findings. */
export function ReviewPanel({ cwd, number }: { cwd: string; number: number }) {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<AgentProgress[]>([]);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The active progress subscription + whether a review is in flight, held in
  // refs so the unmount cleanup can tear both down regardless of render timing.
  const unlistenRef = useRef<UnlistenFn | undefined>(undefined);
  const runningRef = useRef(false);

  // On unmount (e.g. selecting another PR mid-review), unsubscribe and cancel
  // the in-flight review so the backend isn't left running with no listener.
  useEffect(() => {
    return () => {
      unlistenRef.current?.();
      unlistenRef.current = undefined;
      if (runningRef.current) {
        void cancelReview().catch(console.error);
      }
    };
  }, []);

  async function start() {
    setRunning(true);
    runningRef.current = true;
    setProgress([]);
    setFindings(null);
    setError(null);
    try {
      unlistenRef.current = await subscribeReviewProgress((p) =>
        setProgress((cur) => [...cur, p]),
      );
      setFindings(await reviewPr(cwd, number));
    } catch (e) {
      setError(`Review failed: ${e}`);
    } finally {
      unlistenRef.current?.();
      unlistenRef.current = undefined;
      runningRef.current = false;
      setRunning(false);
    }
  }

  return (
    <div className="mt-3">
      <div className="mb-2 flex items-center gap-2">
        <Button
          variant="primary"
          disabled={running}
          onClick={() => void start()}
        >
          {running ? "Reviewing…" : "Review with agents"}
        </Button>
        {running && (
          <Button onClick={() => void cancelReview().catch(console.error)}>
            Cancel
          </Button>
        )}
      </div>

      {error && <Banner kind="error">{error}</Banner>}

      {progress.length > 0 && (
        <ul className="mb-3 space-y-0.5 text-xs text-ink-muted">
          {progress.map((p, i) => (
            <li key={`${p.provider}-${p.category}-${i}`}>
              <span className="text-busy">✓</span> {progressLine(p)}
            </li>
          ))}
        </ul>
      )}

      {findings != null &&
        (findings.length === 0 ? (
          <p className="text-xs text-ink-muted">No findings — looks clean.</p>
        ) : (
          <div className="space-y-3">
            {SEVERITY_ORDER.map((sev) => {
              const group = findings.filter((f) => f.severity === sev);
              if (group.length === 0) return null;
              return (
                <div key={sev}>
                  <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
                    {sev} ({group.length})
                  </h4>
                  <ul className="space-y-2">
                    {group.map((f, i) => (
                      <Card key={`${sev}-${i}`} tone="outline" pad="sm" className="!rounded-lg">
                        <div className="flex items-baseline gap-2">
                          <Badge tone={severityBadgeClass(f.severity)} className="uppercase">
                            {f.category}
                          </Badge>
                          <span className="text-sm text-ink">{f.title}</span>
                          {f.file && (
                            <span className="font-mono text-xs text-ink-faint">
                              {f.file}
                              {f.line != null ? `:${f.line}` : ""}
                            </span>
                          )}
                          <span className="ml-auto text-[10px] text-ink-faint">{f.provider}</span>
                        </div>
                        {f.body && <p className="mt-1 text-xs text-ink-muted">{f.body}</p>}
                      </Card>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        ))}
    </div>
  );
}
