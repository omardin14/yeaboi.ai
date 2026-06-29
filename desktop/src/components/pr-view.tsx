import { useCallback, useEffect, useState } from "react";
import type { Project } from "@/lib/bindings/Project";
import type { PullRequest } from "@/lib/bindings/PullRequest";
import type { MergeMethod } from "@/lib/bindings/MergeMethod";
import {
  abortRebase,
  commentPr,
  continueRebase,
  listPrs,
  mergePr,
  openPr,
  prDiff,
  syncBranch,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Banner } from "@/components/banner";
import { ReviewPanel } from "@/components/review-panel";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { cx } from "@/components/ui/cx";
import { prStateBadgeClass } from "@/lib/format";

function StateBadge({ state }: { state: string }) {
  return <Badge tone={prStateBadgeClass(state)}>{state}</Badge>;
}

/**
 * The PR loop: pick a project, list its PRs, view a diff, and act (merge /
 * comment / open / sync) — each going through the `gh`/`git` Tauri commands.
 */
export function PrView({ projects }: { projects: Project[] }) {
  const [repo, setRepo] = useState<string>(projects[0]?.root ?? "");
  const [prs, setPrs] = useState<PullRequest[] | null>(null);
  const [selected, setSelected] = useState<PullRequest | null>(null);
  const [diff, setDiff] = useState<string>("");
  const [method, setMethod] = useState<MergeMethod>("Squash");
  const [comment, setComment] = useState<string>("");
  const [confirmMerge, setConfirmMerge] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Files left conflicted by a paused rebase; drives the "Abort rebase" affordance.
  const [conflicts, setConflicts] = useState<string[] | null>(null);

  // Adopt the first project once the snapshot arrives, if none chosen yet.
  useEffect(() => {
    if (!repo && projects[0]) setRepo(projects[0].root);
  }, [projects, repo]);

  const refresh = useCallback(async (r: string) => {
    if (!r) return;
    setError(null);
    setNotice(null);
    setPrs(null);
    setSelected(null);
    setDiff("");
    try {
      setPrs(await listPrs(r));
    } catch (e) {
      setError(`Could not list PRs: ${e}`);
      setPrs([]);
    }
  }, []);

  useEffect(() => {
    void refresh(repo);
  }, [repo, refresh]);

  async function selectPr(pr: PullRequest) {
    setSelected(pr);
    setDiff("");
    try {
      setDiff(await prDiff(repo, pr.number));
    } catch (e) {
      setError(`Could not load diff for #${pr.number}: ${e}`);
    }
  }

  async function doMerge() {
    if (!selected) return;
    setConfirmMerge(false);
    setBusy(true);
    setError(null);
    try {
      await mergePr(repo, selected.number, method);
      await refresh(repo); // refresh clears banners, so set the notice after
      setNotice(`Merged #${selected.number}.`);
    } catch (e) {
      setError(`Failed to merge #${selected.number}: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function doComment() {
    if (!selected || !comment.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await commentPr(repo, selected.number, comment.trim());
      setNotice(`Commented on #${selected.number}.`);
      setComment("");
    } catch (e) {
      setError(`Failed to comment on #${selected.number}: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function doOpen() {
    setConfirmOpen(false);
    setBusy(true);
    setError(null);
    try {
      const url = await openPr(repo);
      await refresh(repo); // refresh clears banners, so set the notice after
      setNotice(`Opened PR: ${url}`);
    } catch (e) {
      setError(`Failed to open a PR: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function doSync() {
    setBusy(true);
    setError(null);
    setNotice(null);
    setConflicts(null);
    try {
      const outcome = await syncBranch(repo);
      if (outcome === "Clean") {
        setNotice("Rebased onto the default branch cleanly.");
      } else {
        setConflicts(outcome.Conflicts);
        setError(
          `Rebase paused on conflicts: ${outcome.Conflicts.join(", ")}. Resolve in your editor and continue, or abort.`,
        );
      }
    } catch (e) {
      setError(`Sync failed: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function doAbort() {
    setBusy(true);
    try {
      await abortRebase(repo);
      setConflicts(null);
      setError(null);
      setNotice("Rebase aborted.");
    } catch (e) {
      setError(`Failed to abort the rebase: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function doContinue() {
    setBusy(true);
    try {
      const outcome = await continueRebase(repo);
      if (outcome === "Clean") {
        setConflicts(null);
        setError(null);
        setNotice("Rebase completed.");
      } else {
        setConflicts(outcome.Conflicts);
        setError(`Still conflicted: ${outcome.Conflicts.join(", ")}. Resolve and continue.`);
      }
    } catch (e) {
      setError(`Failed to continue the rebase: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  if (projects.length === 0) {
    return <EmptyState title="No projects yet" hint="Projects show up here once a session is running." />;
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select
          aria-label="Project"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.root}>
              {p.name}
            </option>
          ))}
        </Select>
        <Button onClick={() => void refresh(repo)}>Refresh</Button>
        <Button disabled={busy} onClick={() => void doSync()}>
          Sync (rebase)
        </Button>
        {conflicts && conflicts.length > 0 && (
          <>
            <Button variant="outline" disabled={busy} onClick={() => void doContinue()}>
              Continue rebase
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => void doAbort()}
              className="text-danger hover:bg-danger-fill"
            >
              Abort rebase
            </Button>
          </>
        )}
        <Button variant="primary" disabled={busy} onClick={() => setConfirmOpen(true)}>
          Open PR
        </Button>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="notice">{notice}</Banner>}

      {prs == null ? (
        <p className="text-sm text-ink-muted">Loading PRs…</p>
      ) : prs.length === 0 ? (
        <EmptyState glyph="⌥" title="No pull requests" hint="Open one with the Open PR button above." />
      ) : (
        <Card pad="none" className="overflow-hidden">
          {prs.map((pr, i) => (
            <button
              key={pr.number}
              type="button"
              onClick={() => void selectPr(pr)}
              className={cx(
                "flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors hover:bg-surface-raised",
                i > 0 && "border-t border-line",
                selected?.number === pr.number && "bg-surface-raised",
              )}
            >
              <span className="font-mono text-xs text-ink-faint">#{pr.number}</span>
              <StateBadge state={pr.state} />
              <span className="min-w-0 flex-1 truncate text-ink">
                {pr.title}
                {pr.is_draft && <span className="ml-1 text-xs text-ink-faint">(draft)</span>}
              </span>
              <span className="shrink-0 font-mono text-xs text-ink-faint">
                {pr.head} → {pr.base}
              </span>
            </button>
          ))}
        </Card>
      )}

      {selected && (
        <div className="mt-5 border-t border-line pt-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">
              #{selected.number} {selected.title}
            </h3>
            {selected.state === "OPEN" && (
              <>
                <Select
                  aria-label="Merge method"
                  value={method}
                  onChange={(e) => setMethod(e.target.value as MergeMethod)}
                >
                  <option value="Squash">Squash</option>
                  <option value="Merge">Merge</option>
                  <option value="Rebase">Rebase</option>
                </Select>
                <Button variant="primary" disabled={busy} onClick={() => setConfirmMerge(true)}>
                  Merge
                </Button>
              </>
            )}
          </div>

          {selected.state === "OPEN" && (
            <div className="mb-3 flex gap-2">
              <Input
                aria-label="Comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Comment on this PR…"
                className="flex-1"
              />
              <Button disabled={busy || !comment.trim()} onClick={() => void doComment()}>
                Comment
              </Button>
            </div>
          )}

          <Card tone="sunken" pad="sm" className="max-h-96 overflow-auto">
            <pre className="text-xs leading-relaxed text-ink-soft">
              {diff || "Loading diff…"}
            </pre>
          </Card>

          <ReviewPanel cwd={repo} number={selected.number} />
        </div>
      )}

      <ConfirmDialog
        open={confirmMerge}
        title={`Merge #${selected?.number}?`}
        confirmLabel={method === "Merge" ? "Merge" : `${method} & merge`}
        danger
        onConfirm={() => void doMerge()}
        onCancel={() => setConfirmMerge(false)}
      >
        <p>
          {method} and merge <span className="font-mono">#{selected?.number}</span>{" "}
          into <span className="font-mono">{selected?.base}</span>.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirmOpen}
        title="Open a pull request?"
        confirmLabel="Push & open"
        onConfirm={() => void doOpen()}
        onCancel={() => setConfirmOpen(false)}
      >
        <p>Pushes the current branch and opens a PR against main (fills from commits).</p>
      </ConfirmDialog>
    </div>
  );
}
