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
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/empty-state";

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
        <Input
          aria-label="New worktree name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void doCreate()}
          placeholder="new-worktree-name"
          className="w-48"
        />
        <Button variant="primary" disabled={busy || !name.trim()} onClick={() => void doCreate()}>
          Create
        </Button>
        <Button
          disabled={busy}
          onClick={() => void run(() => pruneWorktrees(repo), "Pruned merged worktrees.")}
        >
          Prune merged
        </Button>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="notice">{notice}</Banner>}

      {worktrees == null ? (
        <p className="text-sm text-ink-muted">Loading worktrees…</p>
      ) : worktrees.length === 0 ? (
        <EmptyState glyph="⑂" title="No worktrees" hint="Create one above to spin up an isolated branch + dev port." />
      ) : (
        <Card pad="none" className="overflow-hidden">
          {worktrees.map((wt, i) => (
            <div
              key={wt.path}
              className={`flex items-center gap-3 px-4 py-2 text-sm ${i > 0 ? "border-t border-line" : ""}`}
            >
              <span className="w-40 shrink-0 truncate font-medium text-ink">
                {wt.is_main ? (
                  <span className="text-ink-muted">{wt.name} </span>
                ) : (
                  wt.name
                )}
                {wt.is_main && (
                  <span className="ml-1 rounded-md bg-surface-sunken px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-faint">
                    home
                  </span>
                )}
              </span>
              <span className="w-40 shrink-0 truncate font-mono text-xs text-ink-muted">
                {wt.branch}
              </span>
              <span className="rounded-md bg-surface-sunken px-1.5 font-mono text-xs text-idle">
                :{wt.port}
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-faint" title={wt.path}>
                {wt.path}
              </span>
              {!wt.is_main && (
                <span className="flex shrink-0 justify-end gap-1">
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => startWorktreeServices(repo, wt.name),
                        `Started services for “${wt.name}”.`,
                      )
                    }
                  >
                    start
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => stopWorktreeServices(repo, wt.name),
                        `Stopped services for “${wt.name}”.`,
                      )
                    }
                  >
                    stop
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={busy}
                    aria-label={`Remove worktree ${wt.name}`}
                    onClick={() => setRemoveTarget(wt)}
                    className="text-danger hover:bg-danger-fill"
                  >
                    remove
                  </Button>
                </span>
              )}
            </div>
          ))}
        </Card>
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
