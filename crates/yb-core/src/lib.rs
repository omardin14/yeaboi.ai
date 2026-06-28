//! Core domain model + read-only collectors for yeaboi.ai.
//!
//! Presentation-agnostic: no UI, no `tauri`, no `sysinfo`, no subprocess
//! spawning. Both the Tauri desktop app and the headless CLI consume the same
//! [`Snapshot`], built by [`Engine::collect`] from the local data Claude/Codex
//! already write to disk.
//!
//! The OS process table is supplied from the outside as a [`ProcTable`] (filled
//! by `yb-proc`) so this crate never depends upward on an OS-specific crate.
//!
//! TypeScript types are generated from the model via `ts-rs` under the `ts`
//! feature (enabled only when regenerating bindings, e.g.
//! `cargo test -p yb-core --features ts`). The headless CLI never enables it.

pub mod adapters;
pub mod engine;
pub mod fswatch;
pub mod model;
pub mod project;
pub(crate) mod util;

pub use fswatch::DirtyWatcher;

pub use engine::{
    CollectOptions, Engine, SessionEvent, SessionEventKind, detect_events, pid_is_live_session,
    pid_owns_tracked_port,
};

/// Read a session's transcript timeline from `$HOME/.claude` for replay
/// (most recent `limit` entries). Empty if `$HOME` is unset.
pub fn transcript_events(session_id: &str, limit: usize) -> Vec<TranscriptEvent> {
    match std::env::var_os("HOME") {
        Some(home) => adapters::claude::transcript_events(
            &std::path::Path::new(&home).join(".claude"),
            session_id,
            limit,
        ),
        None => Vec::new(),
    }
}
pub use model::{
    ActivityStatus, ContextUsage, HostApp, Port, ProcStats, ProcTable, Project, Provider, Session,
    Snapshot, Totals, TranscriptEvent,
};

/// Errors surfaced by the collector path. Most failures are *per-source* and
/// degrade to a `Snapshot.warnings` entry rather than failing the whole tick;
/// this type is for the few hard failures (e.g. a malformed home directory).
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("io error reading {path}: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },

    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

/// Convenience result alias for the crate.
pub type Result<T> = std::result::Result<T, Error>;

/// Current Unix time in milliseconds (`0` if the clock predates the epoch — a
/// documented, harmless fallback; the UI shows "—" when `generated_at_ms == 0`).
pub fn now_ms() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

impl Snapshot {
    /// Deterministic sample snapshot (fixed time 0) used by the desktop shell
    /// until it renders live data. Kept tiny — it only has to type-check the
    /// Rust↔TS seam.
    pub fn stub() -> Self {
        let session = Session {
            id: "stub-1".to_string(),
            pid: Some(1234),
            project_id: "yeaboi.ai".to_string(),
            provider: Provider::Claude,
            host_app: HostApp::Cli,
            cwd: "/Users/dinho/Documents/ai-manager".to_string(),
            name: Some("ai-manager".to_string()),
            model: Some("claude-opus-4-8".to_string()),
            status: ActivityStatus::Busy,
            branch: Some("main".to_string()),
            started_at_ms: 0,
            updated_at_ms: 0,
            context: Some(ContextUsage::new(144_593, 200_000)),
            last_prompt: Some("stub prompt".to_string()),
            sub_agent_count: 0,
            awaiting_permission: false,
            proc_stats: None,
            ports: Vec::new(),
        };
        let project = Project {
            id: "yeaboi.ai".to_string(),
            name: "yeaboi.ai".to_string(),
            root: "/Users/dinho/Documents/ai-manager".to_string(),
            remote: None,
            session_ids: vec![session.id.clone()],
            busy_count: 1,
            session_count: 1,
        };
        Snapshot {
            generated_at_ms: 0,
            totals: Totals {
                session_count: 1,
                busy_count: 1,
                project_count: 1,
            },
            projects: vec![project],
            sessions: vec![session],
            orphan_ports: Vec::new(),
            warnings: Vec::new(),
        }
    }

    /// Same sample, stamped with the current wall-clock time so the desktop
    /// event stream visibly updates each tick.
    pub fn stub_now() -> Self {
        Snapshot {
            generated_at_ms: now_ms(),
            ..Self::stub()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stub_has_one_session_and_project() {
        let s = Snapshot::stub();
        assert_eq!(s.sessions.len(), 1);
        assert_eq!(s.projects.len(), 1);
        assert_eq!(s.generated_at_ms, 0);
    }

    #[test]
    fn stub_round_trips_through_json() {
        let s = Snapshot::stub();
        let json = serde_json::to_string(&s).expect("serialize");
        let back: Snapshot = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(s, back);
    }
}
