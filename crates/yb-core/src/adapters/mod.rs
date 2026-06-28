//! Read-only collectors that turn local Claude/Codex files into [`Session`]s.
//!
//! A collector emits "raw" sessions: `project_id` is left as the cwd and
//! `status`/`proc_stats` are best-effort — the [`crate::engine`] resolves the
//! real project, joins the process table, and refines liveness afterwards. A
//! collector that hits a malformed source pushes a `warnings` line and keeps
//! going; it never fails the whole tick and never swallows the error silently.

pub mod claude;
pub mod codex;

pub use claude::ClaudeCollector;
pub use codex::CodexCollector;

use crate::model::Session;

/// One source of sessions (Claude transcripts, the Codex sqlite, …).
///
/// `&mut self` because stateful collectors (e.g. transcript byte-cursors) carry
/// per-tick state so `--interval` doesn't re-read whole files each time.
pub trait Collector {
    /// Short identifier used in warning messages.
    fn name(&self) -> &'static str;

    /// Append this source's sessions to `out`; record non-fatal degradations in
    /// `warnings`.
    fn collect(&mut self, out: &mut Vec<Session>, warnings: &mut Vec<String>);
}
