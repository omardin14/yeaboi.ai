//! ai-manager desktop (Tauri shell over the `aim-*` engine).
//!
//! Phase 0 proves the Rust↔frontend seam with one typed command
//! ([`get_snapshot`]) and one event (`snapshot-update`) that streams a stub
//! [`Snapshot`] every second. Phase 1 swaps the stub emitter for the real
//! collector `watch<Snapshot>` channel without changing this surface.

use std::time::Duration;

use aim_core::Snapshot;
use tauri::Emitter;

/// Event name carrying each new snapshot to the frontend.
const SNAPSHOT_EVENT: &str = "snapshot-update";

/// Frontend → Rust: fetch the current snapshot on demand.
#[tauri::command]
fn get_snapshot() -> Snapshot {
    Snapshot::stub_now()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![get_snapshot])
        .setup(|app| {
            // Minimal tray with a placeholder tooltip. Phase 1 renders live
            // status (busy count · $today · blocked) and a click-to-open menu.
            let icon = app
                .default_window_icon()
                .cloned()
                .expect("bundled default window icon");
            tauri::tray::TrayIconBuilder::with_id("aim-tray")
                .tooltip("ai-manager")
                .icon(icon)
                .build(app)?;

            // Emit a fresh snapshot every second so the UI visibly live-updates.
            // (Phase 1: replace with a tokio::sync::watch fed by the collectors.)
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    if handle.emit(SNAPSHOT_EVENT, Snapshot::stub_now()).is_err() {
                        break;
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
