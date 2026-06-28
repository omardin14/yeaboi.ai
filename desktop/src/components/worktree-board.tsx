import { useCallback, useEffect, useState } from "react";
import type { Project } from "@/lib/bindings/Project";
import type { Worktree } from "@/lib/bindings/Worktree";
import {
  createWorktree,
  listWorktrees,
  pruneWorktrees,
  removeWorktree,
  startWorktreeServices,
  stopWorktreeServices,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Banner } from "@/components/banner";

/**
 * The worktree board: pick a project, see its worktrees, create one, run/stop
 * its services, or remove it — all via the `yb-worktree` Tauri commands.
 */
export function WorktreeBoard({ projects }: { projects: Project[] }) {
  const [repo, setRepo] = useState<string>(projects[0]?.root ?? "");
  const [worktrees, setWorktrees] = useState<Worktree[] | null>(null);
  const [name, setName] = useState("");
  const [removeTarget, setRemoveTarget] = useState<Worktree | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!repo && projects[0]) setRepo(projects[0].root);
  }, [projects, repo]);

  const refresh = useCallback(async (r: string) => {
    if (!r) return;
    setError(null);
    setWorktrees(null);
    try {
      setWorktrees(await listWorktrees(r));
    } catch (e) {
      setError(`Could not list worktrees: ${e}`);
      setWorktrees([]);
    }
  }, []);

  useEffect(() => {
    void refresh(repo);
  }, [repo, refresh]);

  async function run(action: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(ok);
      await refresh(repo);
    } catch (e) {
      setError(`${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function doCreate() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setName("");
    await run(() => createWorktree(repo, trimmed), `Created “${trimmed}”.`);
  }

  async function doRemove() {
    const target = removeTarget;
    setRemoveTarget(null);
    if (!target) return;
    await run(() => removeWorktree(repo, target.name), `Removed “${target.name}”.`);
  }

  if (projects.length === 0) {
    return <p className="text-sm text-zinc-500">No projects to manage worktrees for yet.</p>;
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
        <input
          aria-label="New worktree name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void doCreate()}
          placeholder="new-worktree-name"
          className="w-48 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-200"
        />
        <button
          type="button"
          disabled={busy || !name.trim()}
          onClick={() => void doCreate()}
          className="rounded bg-sky-600 px-2 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          Create
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void run(() => pruneWorktrees(repo), "Pruned merged worktrees.")}
          className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
        >
          Prune merged
        </button>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="notice">{notice}</Banner>}

      {worktrees == null ? (
        <p className="text-sm text-zinc-500">Loading worktrees…</p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <tbody>
            {worktrees.map((wt) => (
              <tr key={wt.path} className="border-b border-zinc-900 last:border-0">
                <td className="py-1.5 pr-3 font-medium text-zinc-200">
                  {wt.is_main ? <span className="text-zinc-500">{wt.name}</span> : wt.name}
                </td>
                <td className="py-1.5 pr-3 font-mono text-xs text-zinc-400">{wt.branch}</td>
                <td className="py-1.5 pr-3">
                  <span className="rounded bg-zinc-800 px-1 font-mono text-xs text-sky-300">
                    :{wt.port}
                  </span>
                </td>
                <td className="max-w-xs truncate py-1.5 pr-3 font-mono text-xs text-zinc-600" title={wt.path}>
                  {wt.path}
                </td>
                <td className="py-1.5 text-right">
                  {!wt.is_main && (
                    <span className="flex justify-end gap-1">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void run(
                            () => startWorktreeServices(repo, wt.name),
                            `Started services for “${wt.name}”.`,
                          )
                        }
                        className="rounded px-1.5 py-0.5 text-xs text-zinc-400 hover:bg-zinc-800 disabled:opacity-50"
                      >
                        start
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void run(
                            () => stopWorktreeServices(repo, wt.name),
                            `Stopped services for “${wt.name}”.`,
                          )
                        }
                        className="rounded px-1.5 py-0.5 text-xs text-zinc-400 hover:bg-zinc-800 disabled:opacity-50"
                      >
                        stop
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        aria-label={`Remove worktree ${wt.name}`}
                        onClick={() => setRemoveTarget(wt)}
                        className="rounded px-1.5 py-0.5 text-xs text-rose-400 hover:bg-rose-500/10 disabled:opacity-50"
                      >
                        remove
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {removeTarget && (
        <ConfirmDialog
          open
          title={`Remove worktree “${removeTarget.name}”?`}
          confirmLabel="Remove"
          danger
          onConfirm={() => void doRemove()}
          onCancel={() => setRemoveTarget(null)}
        >
          <p>
            Runs teardown, deletes the worktree directory, and removes branch{" "}
            <span className="font-mono">{removeTarget.branch}</span>.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
