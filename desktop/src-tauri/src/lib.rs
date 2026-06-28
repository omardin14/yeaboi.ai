//! yeaboi.ai desktop (Tauri shell over the `yb-*` engine).
//!
//! A background collector thread owns the [`Engine`] + a `yb-proc` [`Sampler`],
//! builds a real [`Snapshot`] every tick, stores the latest in shared state
//! (so [`get_snapshot`] answers on demand) and streams each one to the frontend
//! as a `snapshot-update` event. Commands cover the monitor write paths
//! ([`kill_session`], [`free_port`]) and the PR loop ([`list_prs`]/[`pr_diff`]/
//! [`merge_pr`]/[`comment_pr`]/[`open_pr`]/[`sync_branch`]).

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use tauri::{Emitter, State};
use tauri_plugin_notification::NotificationExt;
use tokio::sync::watch;
use yb_core::{
    CollectOptions, Engine, SessionEventKind, Snapshot, Totals, TranscriptEvent, detect_events,
};

/// Event name carrying each new snapshot to the frontend.
const SNAPSHOT_EVENT: &str = "snapshot-update";

/// Event name carrying a fatal collector failure to the frontend, so the UI can
/// tell the user the live view has stopped rather than silently freezing.
const SNAPSHOT_ERROR_EVENT: &str = "snapshot-error";

/// Tray icon id.
const TRAY_ID: &str = "yeaboi-tray";

/// Upper bound on a collect tick; the fs-watch wakes it earlier on a change.
const TICK: Duration = Duration::from_millis(1500);

/// The latest snapshot, published over a `watch` channel: the collector thread
/// holds the sender, the command handlers read the receiver from Tauri state.
type SnapshotRx = watch::Receiver<Snapshot>;

/// An empty snapshot to seed the channel before the first collect completes.
fn empty_snapshot() -> Snapshot {
    Snapshot {
        generated_at_ms: 0,
        projects: Vec::new(),
        sessions: Vec::new(),
        orphan_ports: Vec::new(),
        totals: Totals::default(),
        warnings: Vec::new(),
    }
}

/// Read the current snapshot from the watch channel.
fn snapshot_of(state: &SnapshotRx) -> Snapshot {
    state.borrow().clone()
}

/// Frontend → Rust: fetch the current snapshot on demand.
#[tauri::command]
fn get_snapshot(state: State<'_, SnapshotRx>) -> Snapshot {
    snapshot_of(&state)
}

/// Frontend → Rust: SIGTERM a session by pid.
///
/// Guarded twice over: we only signal a pid we currently track as a live
/// (non-`Dead`) session — so a stale/forged pid from the UI can't be used to
/// kill an arbitrary process — and `yb_proc` itself refuses pid ≤ 1. Returns
/// `Err(String)` (a rejected JS promise) the frontend surfaces as an error.
#[tauri::command]
fn kill_session(pid: u32, state: State<'_, SnapshotRx>) -> Result<(), String> {
    let snapshot = snapshot_of(&state);
    if !yb_core::pid_is_live_session(&snapshot.sessions, pid) {
        return Err(format!(
            "pid {pid} is not a live session yeaboi is tracking — refusing to signal it"
        ));
    }
    yb_proc::actions::sigterm(pid).map_err(|e| e.to_string())
}

/// Frontend → Rust: free a listening port by SIGTERM-ing the process holding it.
///
/// Guarded like [`kill_session`]: we only signal a pid that currently holds a
/// port attributed to a tracked session (its subtree) — so a forged pid can't
/// be laundered through this command — and `yb_proc` refuses pid ≤ 1.
#[tauri::command]
fn free_port(pid: u32, state: State<'_, SnapshotRx>) -> Result<(), String> {
    let snapshot = snapshot_of(&state);
    // A tracked-session port, or an orphan port we surfaced — both are ours to free.
    let is_orphan = snapshot.orphan_ports.iter().any(|p| p.pid == pid);
    if !yb_core::pid_owns_tracked_port(&snapshot.sessions, pid) && !is_orphan {
        return Err(format!(
            "pid {pid} does not hold a port yeaboi is tracking — refusing to signal it"
        ));
    }
    yb_proc::actions::sigterm(pid).map_err(|e| e.to_string())
}

// ---- PR loop (yb-git over gh/git) -------------------------------------------
//
// These shell out to `gh`/`git` (network, seconds), so each runs on the blocking
// pool via `spawn_blocking` to keep the snapshot stream + UI responsive. They
// target a repo by `cwd` (the selected project's root).

/// Flatten a `spawn_blocking` join + the inner result into one `Result<_, String>`.
async fn blocking<T, F>(f: F) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, String> + Send + 'static,
{
    match tauri::async_runtime::spawn_blocking(f).await {
        Ok(inner) => inner,
        Err(join) => Err(format!("background task failed: {join}")),
    }
}

#[tauri::command]
async fn list_prs(cwd: String) -> Result<Vec<yb_git::PullRequest>, String> {
    blocking(move || yb_git::Gh::new(cwd).pr_list(50).map_err(|e| e.to_string())).await
}

#[tauri::command]
async fn pr_diff(cwd: String, number: u64) -> Result<String, String> {
    blocking(move || {
        yb_git::Gh::new(cwd)
            .pr_diff(number)
            .map_err(|e| e.to_string())
    })
    .await
}

#[tauri::command]
async fn merge_pr(cwd: String, number: u64, method: yb_git::MergeMethod) -> Result<(), String> {
    blocking(move || {
        yb_git::Gh::new(cwd)
            .pr_merge(number, method)
            .map_err(|e| e.to_string())
    })
    .await
}

#[tauri::command]
async fn comment_pr(cwd: String, number: u64, body: String) -> Result<(), String> {
    blocking(move || {
        yb_git::Gh::new(cwd)
            .pr_comment(number, &body)
            .map_err(|e| e.to_string())
    })
    .await
}

/// Push the current branch and open a PR against the repo's default branch;
/// returns the PR URL.
#[tauri::command]
async fn open_pr(cwd: String) -> Result<String, String> {
    blocking(move || {
        let repo = yb_git::GitRepo::new(&cwd);
        let gh = yb_git::Gh::new(&cwd);
        let branch = repo.current_branch().map_err(|e| e.to_string())?;
        // Don't create a duplicate — return the existing PR's URL if there is one.
        if let Some(existing) = gh.find_existing(&branch).map_err(|e| e.to_string())? {
            return Ok(existing.url);
        }
        let base = repo.default_base().map_err(|e| e.to_string())?;
        repo.push_current().map_err(|e| e.to_string())?;
        gh.pr_create(&base).map_err(|e| e.to_string())
    })
    .await
}

/// Rebase the repo's current branch onto its default branch.
#[tauri::command]
async fn sync_branch(cwd: String) -> Result<yb_git::RebaseOutcome, String> {
    blocking(move || {
        let repo = yb_git::GitRepo::new(cwd);
        let base = repo.default_base().map_err(|e| e.to_string())?;
        repo.rebase_onto(&base).map_err(|e| e.to_string())
    })
    .await
}

/// Abort an in-progress rebase (e.g. after [`sync_branch`] hit conflicts).
#[tauri::command]
async fn abort_rebase(cwd: String) -> Result<(), String> {
    blocking(move || {
        yb_git::GitRepo::new(cwd)
            .rebase_abort()
            .map_err(|e| e.to_string())
    })
    .await
}

/// Continue an in-progress rebase after the user resolved conflicts in-editor.
#[tauri::command]
async fn continue_rebase(cwd: String) -> Result<yb_git::RebaseOutcome, String> {
    blocking(move || {
        yb_git::GitRepo::new(cwd)
            .rebase_continue()
            .map_err(|e| e.to_string())
    })
    .await
}

/// The working diff (`git diff HEAD`) for a session's directory.
#[tauri::command]
async fn working_diff(cwd: String) -> Result<String, String> {
    blocking(move || {
        yb_git::GitRepo::new(cwd)
            .working_diff()
            .map_err(|e| e.to_string())
    })
    .await
}

/// A session's transcript timeline for replay (most recent entries).
#[tauri::command]
async fn session_transcript(session_id: String) -> Result<Vec<TranscriptEvent>, String> {
    blocking(move || yb_core::transcript_events(&session_id, 500).map_err(|e| e.to_string())).await
}

// ---- worktrees (yb-worktree) ------------------------------------------------

/// Run `f` against the worktree engine for the repo at `cwd`, on the blocking
/// pool, mapping every error to a string for the IPC boundary.
async fn with_worktrees<T, F>(cwd: String, f: F) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce(&yb_worktree::WorktreeEngine) -> Result<T, yb_worktree::WorktreeError>
        + Send
        + 'static,
{
    blocking(move || {
        let engine = yb_worktree::WorktreeEngine::discover(&cwd).map_err(|e| e.to_string())?;
        f(&engine).map_err(|e| e.to_string())
    })
    .await
}

#[tauri::command]
async fn list_worktrees(cwd: String) -> Result<Vec<yb_worktree::Worktree>, String> {
    with_worktrees(cwd, |e| e.list()).await
}

#[tauri::command]
async fn create_worktree(cwd: String, name: String) -> Result<yb_worktree::Worktree, String> {
    with_worktrees(cwd, move |e| e.create(&name)).await
}

#[tauri::command]
async fn remove_worktree(cwd: String, name: String) -> Result<(), String> {
    with_worktrees(cwd, move |e| e.remove(&name)).await
}

#[tauri::command]
async fn prune_worktrees(cwd: String) -> Result<Vec<String>, String> {
    with_worktrees(cwd, |e| e.prune_merged()).await
}

#[tauri::command]
async fn start_worktree_services(cwd: String, name: String) -> Result<(), String> {
    with_worktrees(cwd, move |e| e.start_services(&name)).await
}

#[tauri::command]
async fn stop_worktree_services(cwd: String, name: String) -> Result<(), String> {
    with_worktrees(cwd, move |e| e.stop_services(&name)).await
}

// ---- multi-agent review (yb-agent) ------------------------------------------

/// Run a multi-agent review of PR `number`: fetch its diff, fan it out across the
/// reachable agent CLIs, and emit `review-progress` per agent. Returns the merged
/// findings. Cancelable via [`cancel_review`].
#[tauri::command]
async fn review_pr(
    cwd: String,
    number: u64,
    app: tauri::AppHandle,
    cancel: State<'_, Arc<AtomicBool>>,
) -> Result<Vec<yb_agent::Finding>, String> {
    let flag = cancel.inner().clone();
    flag.store(false, Ordering::Relaxed); // fresh run
    blocking(move || {
        let diff = yb_git::Gh::new(&cwd)
            .pr_diff(number)
            .map_err(|e| e.to_string())?;
        let orchestrator = yb_agent::default_orchestrator()
            .ok_or("no agent CLI found on PATH (need `claude` or `codex`)")?;
        let findings = orchestrator.run(&diff, &flag, |progress| {
            if let Err(e) = app.emit("review-progress", &progress) {
                eprintln!("review-progress emit failed: {e}");
            }
        });
        Ok(findings)
    })
    .await
}

/// Signal an in-flight [`review_pr`] to stop.
#[tauri::command]
fn cancel_review(cancel: State<'_, Arc<AtomicBool>>) {
    cancel.store(true, Ordering::Relaxed);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let (tx, rx) = watch::channel(empty_snapshot());

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .manage(rx)
        .manage(Arc::new(AtomicBool::new(false))) // review cancel flag
        .invoke_handler(tauri::generate_handler![
            get_snapshot,
            kill_session,
            free_port,
            list_prs,
            pr_diff,
            merge_pr,
            comment_pr,
            open_pr,
            sync_branch,
            abort_rebase,
            continue_rebase,
            working_diff,
            session_transcript,
            list_worktrees,
            create_worktree,
            remove_worktree,
            prune_worktrees,
            start_worktree_services,
            stop_worktree_services,
            review_pr,
            cancel_review
        ])
        .setup(move |app| {
            let icon = app
                .default_window_icon()
                .cloned()
                .ok_or("bundled default window icon missing")?;
            tauri::tray::TrayIconBuilder::with_id(TRAY_ID)
                .tooltip("yeaboi.ai")
                .icon(icon)
                .build(app)?;

            spawn_collector(app.handle().clone(), tx);
            Ok(())
        })
        .run(tauri::generate_context!())
        // fatal: the Tauri event loop failed to start — nothing to recover to.
        .expect("error while running tauri application");
}

/// Spawn the collector loop on a dedicated OS thread. Building the engine and
/// sampler *inside* the thread keeps the (non-`Send`) collectors thread-local.
fn spawn_collector(handle: tauri::AppHandle, tx: watch::Sender<Snapshot>) {
    std::thread::spawn(move || {
        let mut engine = Engine::with_default_sources(CollectOptions::default());
        let mut sampler = yb_proc::Sampler::new();
        let watcher = claude_codex_watcher();
        let mut prev: Option<Snapshot> = None;
        // Prime CPU so the first frame carries real percentages.
        std::thread::sleep(yb_proc::min_sample_interval());

        loop {
            // Catch a panic in the data path so the monitor reports the failure
            // instead of silently freezing on its last frame — the one failure
            // mode a monitor must never have.
            let collected = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let proc = sampler.sample();
                let (ports, warn) = sample_ports();
                let mut snap = engine.collect(&proc, &ports);
                snap.warnings.extend(warn);
                snap
            }));
            let snap = match collected {
                Ok(snap) => snap,
                Err(_) => {
                    report_stream_death(&handle, "the session collector panicked");
                    break;
                }
            };

            // Fire notifications for finish/blocked transitions vs the prior frame.
            if let Some(prev) = &prev {
                notify_transitions(&handle, prev, &snap);
            }
            update_tray(&handle, &snap);

            if tx.send(snap.clone()).is_err() {
                break; // all receivers dropped — the app is shutting down
            }
            if let Err(err) = handle.emit(SNAPSHOT_EVENT, &snap) {
                report_stream_death(&handle, &format!("snapshot stream failed: {err}"));
                break;
            }
            prev = Some(snap);

            // Sleep up to a tick, but wake early when ~/.claude changes.
            if let Some(w) = &watcher {
                w.wait(TICK);
            } else {
                std::thread::sleep(TICK);
            }
        }
    });
}

/// Enumerate listening ports, degrading a failure to a snapshot warning so a
/// stuck `lsof` never blocks the live view.
fn sample_ports() -> (Vec<yb_core::Port>, Option<String>) {
    match yb_proc::ports::list() {
        Ok(ports) => (ports, None),
        Err(err) => (Vec::new(), Some(format!("ports: {err}"))),
    }
}

/// Tell the frontend (and the logs) that live updates have stopped. The error
/// event is best-effort — if even that fails, the channel is gone and there's
/// nothing left to do but log.
fn report_stream_death(handle: &tauri::AppHandle, message: &str) {
    eprintln!("collector stream stopped: {message}");
    if let Err(err) = handle.emit(SNAPSHOT_ERROR_EVENT, message) {
        eprintln!("could not deliver snapshot-error to the UI: {err}");
    }
}

/// Watch `~/.claude` + `~/.codex` so the collector wakes promptly on a change.
fn claude_codex_watcher() -> Option<yb_proc::DirtyWatcher> {
    let home = std::env::var_os("HOME")?;
    let home = std::path::Path::new(&home);
    yb_proc::DirtyWatcher::new([home.join(".claude"), home.join(".codex")])
}

/// Reflect the live counts in the tray tooltip.
fn update_tray(handle: &tauri::AppHandle, snap: &Snapshot) {
    let Some(tray) = handle.tray_by_id(TRAY_ID) else {
        return;
    };
    let t = &snap.totals;
    let tooltip = format!(
        "yeaboi.ai — {} busy · {} session(s) · {} project(s)",
        t.busy_count, t.session_count, t.project_count
    );
    if let Err(err) = tray.set_tooltip(Some(tooltip)) {
        eprintln!("tray: could not update tooltip: {err}");
    }
}

/// Fire an OS notification for each finish/blocked transition since the last frame.
fn notify_transitions(handle: &tauri::AppHandle, prev: &Snapshot, next: &Snapshot) {
    for event in detect_events(prev, next) {
        let (title, body) = match event.kind {
            SessionEventKind::Finished => ("Session finished", format!("{} is idle", event.label)),
            SessionEventKind::AwaitingPermission => (
                "Permission needed",
                format!("{} is waiting on you", event.label),
            ),
        };
        if let Err(err) = handle
            .notification()
            .builder()
            .title(title)
            .body(body)
            .show()
        {
            eprintln!("notification failed: {err}");
        }
    }
}
