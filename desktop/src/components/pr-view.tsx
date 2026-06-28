import { useCallback, useEffect, useState } from "react";
import type { Project } from "@/lib/bindings/Project";
import type { PullRequest } from "@/lib/bindings/PullRequest";
import type { MergeMethod } from "@/lib/bindings/MergeMethod";
import {
  abortRebase,
  commentPr,
  listPrs,
  mergePr,
  openPr,
  prDiff,
  syncBranch,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Banner } from "@/components/banner";

const STATE_STYLES: Record<string, string> = {
  OPEN: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  MERGED: "bg-violet-500/15 text-violet-400 ring-violet-500/30",
  CLOSED: "bg-rose-500/15 text-rose-400 ring-rose-500/30",
};

function StateBadge({ state }: { state: string }) {
  const cls = STATE_STYLES[state] ?? "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}
    >
      {state}
    </span>
  );
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

  if (projects.length === 0) {
    return <p className="text-sm text-zinc-500">No projects to show PRs for yet.</p>;
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select
          aria-label="Project"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-200"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.root}>
              {p.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void refresh(repo)}
          className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
        >
          Refresh
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void doSync()}
          className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
        >
          Sync (rebase)
        </button>
        {conflicts && conflicts.length > 0 && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void doAbort()}
            className="rounded border border-rose-500/40 px-2 py-1 text-xs text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
          >
            Abort rebase
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => setConfirmOpen(true)}
          className="rounded bg-sky-600 px-2 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          Open PR
        </button>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="notice">{notice}</Banner>}

      {prs == null ? (
        <p className="text-sm text-zinc-500">Loading PRs…</p>
      ) : prs.length === 0 ? (
        <p className="text-sm text-zinc-500">No pull requests.</p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <tbody>
            {prs.map((pr) => (
              <tr
                key={pr.number}
                onClick={() => void selectPr(pr)}
                className={`cursor-pointer border-b border-zinc-900 hover:bg-zinc-900/50 ${
                  selected?.number === pr.number ? "bg-zinc-900/60" : ""
                }`}
              >
                <td className="py-1.5 pr-3 font-mono text-xs text-zinc-500">#{pr.number}</td>
                <td className="py-1.5 pr-3">
                  <StateBadge state={pr.state} />
                </td>
                <td className="py-1.5 pr-3 text-zinc-200">
                  {pr.title}
                  {pr.is_draft && <span className="ml-1 text-xs text-zinc-500">(draft)</span>}
                </td>
                <td className="py-1.5 pr-3 font-mono text-xs text-zinc-500">
                  {pr.head} → {pr.base}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <div className="mt-5 border-t border-zinc-800 pt-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-zinc-200">
              #{selected.number} {selected.title}
            </h3>
            {selected.state === "OPEN" && (
              <>
                <select
                  aria-label="Merge method"
                  value={method}
                  onChange={(e) => setMethod(e.target.value as MergeMethod)}
                  className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200"
                >
                  <option value="Squash">Squash</option>
                  <option value="Merge">Merge</option>
                  <option value="Rebase">Rebase</option>
                </select>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmMerge(true)}
                  className="rounded bg-violet-600 px-2 py-1 text-xs font-medium text-white hover:bg-violet-500 disabled:opacity-50"
                >
                  Merge
                </button>
              </>
            )}
          </div>

          {selected.state === "OPEN" && (
            <div className="mb-3 flex gap-2">
              <input
                aria-label="Comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Comment on this PR…"
                className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-200"
              />
              <button
                type="button"
                disabled={busy || !comment.trim()}
                onClick={() => void doComment()}
                className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
              >
                Comment
              </button>
            </div>
          )}

          <pre className="max-h-96 overflow-auto rounded bg-zinc-900 p-3 text-xs leading-relaxed text-zinc-300">
            {diff || "Loading diff…"}
          </pre>
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
