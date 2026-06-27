//! Core domain model for ai-manager.
//!
//! Presentation-agnostic: no UI, no OS-specific code. Both the Tauri desktop
//! app and the headless CLI consume the same [`Snapshot`].
//!
//! Phase 0 ships a stub `Snapshot` that proves the data contract end-to-end
//! (CLI JSON + Tauri command/event). Phase 1 replaces the stub with real
//! collectors over `~/.claude` and `~/.codex`.
//!
//! TypeScript types are generated from these structs via `ts-rs` under the
//! `ts` feature (enabled only when regenerating bindings, e.g.
//! `cargo test -p aim-core --features ts`). The headless CLI never enables it.

use serde::{Deserialize, Serialize};

/// Immutable snapshot of everything the monitor knows at a point in time.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Snapshot {
    /// Unix epoch milliseconds when this snapshot was built.
    // u64 over the wire is a JSON number; pin the TS type so it doesn't become `bigint`.
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub generated_at_ms: u64,
    /// Sessions known at this tick (stub shape in Phase 0).
    pub sessions: Vec<SessionStub>,
    /// Non-fatal collector degradations to surface in the UI.
    pub warnings: Vec<String>,
}

/// Minimal session shape for Phase 0. Phase 1 expands this into the full
/// `Session` (pid, cwd, model, context, sub-agents, ports, …).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct SessionStub {
    pub id: String,
    pub project: String,
    pub status: String,
}

impl Snapshot {
    /// Deterministic sample snapshot used by the CLI/desktop until real
    /// collectors land. `generated_at_ms` is fixed (0) for stable tests.
    pub fn stub() -> Self {
        Snapshot {
            generated_at_ms: 0,
            sessions: vec![
                SessionStub {
                    id: "stub-1".to_string(),
                    project: "ai-manager".to_string(),
                    status: "busy".to_string(),
                },
                SessionStub {
                    id: "stub-2".to_string(),
                    project: "planning-platform".to_string(),
                    status: "idle".to_string(),
                },
            ],
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

fn now_ms() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stub_has_sessions_and_fixed_time() {
        let s = Snapshot::stub();
        assert_eq!(s.sessions.len(), 2);
        assert_eq!(s.generated_at_ms, 0);
        assert!(s.warnings.is_empty());
    }

    #[test]
    fn stub_round_trips_through_json() {
        let s = Snapshot::stub();
        let json = serde_json::to_string(&s).expect("serialize");
        assert!(json.contains("\"sessions\""));
        let back: Snapshot = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(s, back);
    }
}
