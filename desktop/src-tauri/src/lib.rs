//! yeaboi.ai desktop (Tauri shell over the `yb-*` engine).
//!
//! A background collector thread owns the [`Engine`] + a `yb-proc` [`Sampler`],
//! builds a real [`Snapshot`] every tick, stores the latest in shared state
//! (so [`get_snapshot`] answers on demand) and streams each one to the frontend
//! as a `snapshot-update` event. The one write path so far is [`kill_session`]
//! (SIGTERM, guarded); port collection + free-port land in a later slice.

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
    let tracked = snapshot_of(&state)
        .sessions
        .iter()
        .any(|s| s.pid == Some(pid) && s.status != yb_core::ActivityStatus::Dead);
    if !tracked {
        return Err(format!(
            "pid {pid} is not a live session yeaboi is tracking — refusing to signal it"
        ));
    }
    yb_proc::actions::sigterm(pid).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let shared: SharedSnapshot = Arc::new(Mutex::new(empty_snapshot()));

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![get_snapshot, kill_session])
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
                engine.collect(&proc)
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

/// Tell the frontend (and the logs) that live updates have stopped. The error
/// event is best-effort — if even that fails, the channel is gone and there's
/// nothing left to do but log.
fn report_stream_death(handle: &tauri::AppHandle, message: &str) {
    eprintln!("collector stream stopped: {message}");
    if let Err(err) = handle.emit(SNAPSHOT_ERROR_EVENT, message) {
        eprintln!("could not deliver snapshot-error to the UI: {err}");
    }
}
