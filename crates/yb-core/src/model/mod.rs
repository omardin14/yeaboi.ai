//! The shared domain model — the `Snapshot` contract both the headless CLI and
//! the desktop app render from. Plain data only: no IO, no OS calls, no UI.

pub mod windows;

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Which CLI a session belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub enum Provider {
    Claude,
    Codex,
}

/// Coarse activity state. `Unknown` is a real, common case — `sessions/*.json`
/// omits `status` entirely when it has never been set.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub enum ActivityStatus {
    /// Actively working a turn.
    Busy,
    /// Alive but waiting on the user.
    Idle,
    /// No live process for this pid — a stale session file.
    Dead,
    /// Liveness couldn't be determined.
    Unknown,
}

/// Which host application launched the session, derived from `entrypoint`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub enum HostApp {
    /// Terminal / headless (`entrypoint: "cli"`).
    Cli,
    /// VS Code extension (`entrypoint: "claude-vscode"`).
    VsCode,
    /// Anything else, preserving the raw entrypoint string.
    Other(String),
}

impl HostApp {
    /// Map a Claude `entrypoint` value to a host app.
    pub fn from_entrypoint(entrypoint: &str) -> Self {
        match entrypoint {
            "cli" => HostApp::Cli,
            "claude-vscode" | "vscode" => HostApp::VsCode,
            other => HostApp::Other(other.to_string()),
        }
    }
}

/// Token usage of the latest turn against the model's context window.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct ContextUsage {
    /// Tokens occupying the context window right now (input + cache create + cache read).
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub used: u64,
    /// The model's context window in tokens.
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub window: u64,
    /// `used / window`, clamped to `[0, 1]`.
    pub pct: f32,
}

impl ContextUsage {
    /// Build a usage from raw token counts, computing `pct` (window of 0 → 0%).
    pub fn new(used: u64, window: u64) -> Self {
        let pct = if window == 0 {
            0.0
        } else {
            (used as f32 / window as f32).clamp(0.0, 1.0)
        };
        ContextUsage { used, window, pct }
    }
}

/// Process metrics for a session's pid, joined in from the OS process table.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct ProcStats {
    /// Instantaneous CPU usage percentage (can exceed 100 across cores).
    pub cpu_pct: f32,
    /// Resident memory in bytes.
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub mem_bytes: u64,
    /// Seconds since the process started.
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub uptime_secs: u64,
    /// Parent pid, if known.
    #[cfg_attr(feature = "ts", ts(type = "number | null"))]
    pub ppid: Option<u32>,
}

/// A listening TCP port held by a session's process (or one of its children,
/// e.g. a dev server). Joined in from `lsof`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Port {
    /// The listening port number.
    pub number: u16,
    /// The pid holding the socket (may be a child of the session pid).
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub pid: u32,
    /// Socket state as reported by lsof (e.g. `LISTEN`).
    pub state: String,
}

/// One AI coding session.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Session {
    /// Provider session id (Claude `sessionId` / Codex `threads.id`).
    pub id: String,
    /// OS process id, when known (Codex threads have none).
    #[cfg_attr(feature = "ts", ts(type = "number | null"))]
    pub pid: Option<u32>,
    /// Id of the [`Project`] this session rolls up under.
    pub project_id: String,
    pub provider: Provider,
    pub host_app: HostApp,
    /// Working directory the session was launched in.
    pub cwd: String,
    /// Human label if the session was named.
    pub name: Option<String>,
    /// Model of the latest turn.
    pub model: Option<String>,
    pub status: ActivityStatus,
    /// Git branch reported by the transcript / thread.
    pub branch: Option<String>,
    /// Epoch ms the session started.
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub started_at_ms: u64,
    /// Epoch ms of the last observed activity.
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub updated_at_ms: u64,
    /// Context-window usage of the latest turn, if a usage line was seen.
    pub context: Option<ContextUsage>,
    /// The most recent user prompt (truncated upstream).
    pub last_prompt: Option<String>,
    /// Best-effort count of sub-agent (sidechain) activity in the transcript.
    pub sub_agent_count: u32,
    /// Best-effort: the session appears paused on a permission request (a
    /// pending tool-use with no result while not actively working).
    pub awaiting_permission: bool,
    /// Process metrics joined in by pid, when the process is live.
    pub proc_stats: Option<ProcStats>,
    /// Listening ports held by this session's process subtree.
    pub ports: Vec<Port>,
}

/// A repository the sessions roll up under. Worktrees of one repo collapse here.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Project {
    /// Stable id (repo common-dir path, or cwd for non-git sessions).
    pub id: String,
    /// Display name (repo folder name, or remote slug when available).
    pub name: String,
    /// Filesystem root of the repo (or cwd).
    pub root: String,
    /// `origin` remote URL, when the repo has one.
    pub remote: Option<String>,
    /// Sessions belonging to this project.
    pub session_ids: Vec<String>,
    pub busy_count: u32,
    pub session_count: u32,
}

/// Rolled-up counts for the header line.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Totals {
    pub session_count: u32,
    pub busy_count: u32,
    pub project_count: u32,
}

/// Immutable snapshot of everything the monitor knows at a point in time.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Snapshot {
    /// Unix epoch milliseconds when this snapshot was built.
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub generated_at_ms: u64,
    pub projects: Vec<Project>,
    pub sessions: Vec<Session>,
    /// Listening ports once owned by a session's subtree whose process is now
    /// unattributed (e.g. a dev server outliving the session that spawned it).
    pub orphan_ports: Vec<Port>,
    pub totals: Totals,
    /// Non-fatal collector degradations to surface in the UI.
    pub warnings: Vec<String>,
}

/// One entry in a session's transcript timeline (for replay).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct TranscriptEvent {
    /// `user` | `assistant` | `tool_use` | `tool_result` | `thinking` | …
    pub kind: String,
    /// A short human summary of the entry.
    pub summary: String,
}

/// Process metrics keyed by pid, plus parent→children adjacency. Produced by
/// `yb-proc` and consumed by the enrichment pass; not part of the wire contract.
#[derive(Debug, Clone, Default)]
pub struct ProcTable {
    pub by_pid: HashMap<u32, ProcStats>,
    pub children: HashMap<u32, Vec<u32>>,
}

impl ProcTable {
    /// All descendant pids of `pid` (BFS over the parent→children adjacency).
    /// `pid` itself is not included. Robust against cycles in malformed input.
    pub fn subtree(&self, pid: u32) -> Vec<u32> {
        let mut out = Vec::new();
        let mut seen = std::collections::HashSet::new();
        let mut queue = std::collections::VecDeque::new();
        queue.push_back(pid);
        seen.insert(pid);
        while let Some(p) = queue.pop_front() {
            if let Some(kids) = self.children.get(&p) {
                for &k in kids {
                    if seen.insert(k) {
                        out.push(k);
                        queue.push_back(k);
                    }
                }
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn context_usage_computes_pct() {
        // The plan's sample: 1 + 111 + 144481 tokens against a 200k window.
        let u = ContextUsage::new(1 + 111 + 144_481, 200_000);
        assert_eq!(u.used, 144_593);
        assert!((u.pct - 0.722_965).abs() < 1e-4, "pct was {}", u.pct);
    }

    #[test]
    fn context_usage_clamps_and_guards_zero_window() {
        assert_eq!(ContextUsage::new(10, 0).pct, 0.0);
        assert_eq!(ContextUsage::new(500, 100).pct, 1.0);
    }

    #[test]
    fn host_app_from_entrypoint() {
        assert_eq!(HostApp::from_entrypoint("cli"), HostApp::Cli);
        assert_eq!(HostApp::from_entrypoint("claude-vscode"), HostApp::VsCode);
        assert_eq!(
            HostApp::from_entrypoint("cursor"),
            HostApp::Other("cursor".to_string())
        );
    }

    #[test]
    fn subtree_bfs_over_synthetic_map() {
        // 1 → {2, 3}; 2 → {4}; 3 → {}; 4 → {5}
        let mut children = HashMap::new();
        children.insert(1, vec![2, 3]);
        children.insert(2, vec![4]);
        children.insert(4, vec![5]);
        let table = ProcTable {
            by_pid: HashMap::new(),
            children,
        };
        let mut sub = table.subtree(1);
        sub.sort_unstable();
        assert_eq!(sub, vec![2, 3, 4, 5]);
        assert_eq!(table.subtree(3), Vec::<u32>::new());
    }

    #[test]
    fn subtree_survives_a_cycle() {
        // 1 → 2 → 1 (malformed); must terminate.
        let mut children = HashMap::new();
        children.insert(1, vec![2]);
        children.insert(2, vec![1]);
        let table = ProcTable {
            by_pid: HashMap::new(),
            children,
        };
        assert_eq!(table.subtree(1), vec![2]);
    }
}
