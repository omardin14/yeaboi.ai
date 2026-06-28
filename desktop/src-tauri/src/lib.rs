//! yeaboi.ai desktop (Tauri shell over the `yb-*` engine).
//!
//! A background collector thread owns the [`Engine`] + a `yb-proc` [`Sampler`],
//! builds a real [`Snapshot`] every tick, stores the latest in shared state
//! (so [`get_snapshot`] answers on demand) and streams each one to the frontend
//! as a `snapshot-update` event. Read-only — mutations (kill / free-port) and
//! port collection land in the next slice.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Emitter, State};
use yb_core::{CollectOptions, Engine, Snapshot, Totals};

/// Event name carrying each new snapshot to the frontend.
const SNAPSHOT_EVENT: &str = "snapshot-update";

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

/// Read a `Mutex` guard's value, recovering (rather than panicking) if a prior
/// holder panicked while holding the lock.
fn snapshot_of(shared: &SharedSnapshot) -> Snapshot {
    match shared.lock() {
        Ok(guard) => guard.clone(),
        Err(poisoned) => poisoned.into_inner().clone(),
    }
}

/// Frontend → Rust: fetch the current snapshot on demand.
#[tauri::command]
fn get_snapshot(state: State<'_, SharedSnapshot>) -> Snapshot {
    snapshot_of(&state)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let shared: SharedSnapshot = Arc::new(Mutex::new(empty_snapshot()));

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![get_snapshot])
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
            let proc = sampler.sample();
            let snap = engine.collect(&proc);

            match shared.lock() {
                Ok(mut guard) => *guard = snap.clone(),
                Err(poisoned) => *poisoned.into_inner() = snap.clone(),
            }

            if let Err(err) = handle.emit(SNAPSHOT_EVENT, &snap) {
                // The only data pipeline just died — be loud rather than
                // silently freezing the UI.
                eprintln!("snapshot emit failed, stopping stream: {err}");
                break;
            }
            std::thread::sleep(TICK);
        }
    });
}
