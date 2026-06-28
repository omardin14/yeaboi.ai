//! yeaboi.ai desktop (Tauri shell over the `yb-*` engine).
//!
//! A background collector thread owns the [`Engine`] + a `yb-proc` [`Sampler`],
//! builds a real [`Snapshot`] every tick, stores the latest in shared state
//! (so [`get_snapshot`] answers on demand) and streams each one to the frontend
//! as a `snapshot-update` event. Commands cover the monitor write paths
//! ([`kill_session`], [`free_port`]) and the PR loop ([`list_prs`]/[`pr_diff`]/
//! [`merge_pr`]/[`comment_pr`]/[`open_pr`]/[`sync_branch`]).

use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Emitter, State};
use yb_core::{CollectOptions, Engine, Snapshot, Totals};

/// Event name carrying each new snapshot to the frontend.
const SNAPSHOT_EVENT: &str = "snapshot-update";

/// Event name carrying a fatal collector failure to the frontend, so the UI can
/// tell the user the live view has stopped rather than silently freezing.
const SNAPSHOT_ERROR_EVENT: &str = "snapshot-error";

/// How often the collector rebuilds a snapshot. Transcript tailing is
/// incremental, so each tick after the first is cheap.
const TICK: Duration = Duration::from_millis(1500);

/// Latest snapshot, shared between the collector thread and the command handler.
type SharedSnapshot = Arc<Mutex<Snapshot>>;

/// An empty snapshot to seed shared state before the first collect completes.
fn empty_snapshot() -> Snapshot {
    Snapshot {
        generated_at_ms: 0,
        projects: Vec::new(),
        sessions: Vec::new(),
        totals: Totals::default(),
        warnings: Vec::new(),
    }
}

/// Lock the shared snapshot, recovering (with a logged breadcrumb) if a prior
/// holder panicked while holding it. Clears the poison so the hot path doesn't
/// run the recovery arm on every subsequent tick.
fn lock_recovering(shared: &SharedSnapshot) -> std::sync::MutexGuard<'_, Snapshot> {
    shared.lock().unwrap_or_else(|poisoned| {
        eprintln!("snapshot state lock was poisoned (a prior holder panicked); recovering");
        shared.clear_poison();
        poisoned.into_inner()
    })
}

/// Read the current snapshot from shared state.
fn snapshot_of(shared: &SharedSnapshot) -> Snapshot {
    lock_recovering(shared).clone()
}

/// Frontend → Rust: fetch the current snapshot on demand.
#[tauri::command]
fn get_snapshot(state: State<'_, SharedSnapshot>) -> Snapshot {
    snapshot_of(&state)
}

/// Frontend → Rust: SIGTERM a session by pid.
///
/// Guarded twice over: we only signal a pid we currently track as a live
/// (non-`Dead`) session — so a stale/forged pid from the UI can't be used to
/// kill an arbitrary process — and `yb_proc` itself refuses pid ≤ 1. Returns
/// `Err(String)` (a rejected JS promise) the frontend surfaces as an error.
#[tauri::command]
fn kill_session(pid: u32, state: State<'_, SharedSnapshot>) -> Result<(), String> {
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
fn free_port(pid: u32, state: State<'_, SharedSnapshot>) -> Result<(), String> {
    let snapshot = snapshot_of(&state);
    if !yb_core::pid_owns_tracked_port(&snapshot.sessions, pid) {
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
        let base = repo.default_base().map_err(|e| e.to_string())?;
        repo.push_current().map_err(|e| e.to_string())?;
        yb_git::Gh::new(&cwd)
            .pr_create(&base)
            .map_err(|e| e.to_string())
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let shared: SharedSnapshot = Arc::new(Mutex::new(empty_snapshot()));

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(shared.clone())
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
            abort_rebase
        ])
        .setup(move |app| {
            // Minimal tray with a placeholder tooltip. A later slice renders live
            // status (busy count · $today · blocked) and a click-to-open menu.
            let icon = app
                .default_window_icon()
                .cloned()
                .ok_or("bundled default window icon missing")?;
            tauri::tray::TrayIconBuilder::with_id("yeaboi-tray")
                .tooltip("yeaboi.ai")
                .icon(icon)
                .build(app)?;

            spawn_collector(app.handle().clone(), shared.clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        // fatal: the Tauri event loop failed to start — nothing to recover to.
        .expect("error while running tauri application");
}

/// Spawn the collector loop on a dedicated OS thread. Building the engine and
/// sampler *inside* the thread keeps the (non-`Send`) collectors thread-local.
fn spawn_collector(handle: tauri::AppHandle, shared: SharedSnapshot) {
    std::thread::spawn(move || {
        let mut engine = Engine::with_default_sources(CollectOptions::default());
        let mut sampler = yb_proc::Sampler::new();
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

            *lock_recovering(&shared) = snap.clone();

            if let Err(err) = handle.emit(SNAPSHOT_EVENT, &snap) {
                report_stream_death(&handle, &format!("snapshot stream failed: {err}"));
                break;
            }
            std::thread::sleep(TICK);
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
