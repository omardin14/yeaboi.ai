//! Codex collector: read-only queries over `~/.codex/state_5.sqlite`.
//!
//! Codex stores "threads" (not OS processes), so these sessions have no pid and
//! no live process to join — they're records of recent agent activity. We open
//! the DB strictly read-only and bound the query to recent, non-archived
//! threads. An absent DB is normal (machine never ran Codex) and yields nothing.

use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};

use super::Collector;
use crate::model::windows::context_window;
use crate::model::{ActivityStatus, ContextUsage, HostApp, Provider, Session};

/// How many recent threads to surface per tick.
const THREAD_LIMIT: usize = 200;

/// Collector over a Codex state sqlite file.
pub struct CodexCollector {
    db_path: PathBuf,
}

impl CodexCollector {
    /// Collector for an explicit sqlite path (used by tests).
    pub fn new(db_path: PathBuf) -> Self {
        CodexCollector { db_path }
    }

    /// Collector for `$HOME/.codex/state_5.sqlite`. `None` if `$HOME` is unset.
    pub fn from_home() -> Option<Self> {
        let home = std::env::var_os("HOME")?;
        Some(Self::new(
            Path::new(&home).join(".codex").join("state_5.sqlite"),
        ))
    }

    fn query(&self) -> rusqlite::Result<Vec<Session>> {
        let conn = Connection::open_with_flags(
            &self.db_path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        // Belt-and-braces: the connection is already read-only.
        conn.execute_batch("PRAGMA query_only = 1;")?;

        let mut stmt = conn.prepare(
            "SELECT id, model, git_branch, cwd, title, tokens_used, \
                    created_at_ms, updated_at_ms, first_user_message \
             FROM threads \
             WHERE archived = 0 \
             ORDER BY updated_at_ms DESC \
             LIMIT ?1",
        )?;

        let rows = stmt.query_map([THREAD_LIMIT], |row| {
            let id: String = row.get("id")?;
            let model: Option<String> = row.get("model")?;
            let git_branch: Option<String> = row.get("git_branch")?;
            let cwd: String = row.get("cwd")?;
            let title: Option<String> = row.get("title")?;
            let tokens_used: i64 = row.get("tokens_used")?;
            let created_at_ms: Option<i64> = row.get("created_at_ms")?;
            let updated_at_ms: Option<i64> = row.get("updated_at_ms")?;
            let first_user_message: Option<String> = row.get("first_user_message")?;

            let used = tokens_used.max(0) as u64;
            let context = model
                .as_deref()
                .map(|m| ContextUsage::new(used, context_window(m)));

            Ok(Session {
                id,
                pid: None,
                project_id: cwd.clone(), // placeholder; engine resolves the real project
                provider: Provider::Codex,
                host_app: HostApp::Other("codex".to_string()),
                cwd,
                name: title.filter(|t| !t.is_empty()),
                model,
                // Threads are records, not live processes — Idle is the honest default.
                status: ActivityStatus::Idle,
                branch: git_branch.filter(|b| !b.is_empty()),
                started_at_ms: created_at_ms.unwrap_or(0).max(0) as u64,
                updated_at_ms: updated_at_ms.unwrap_or(0).max(0) as u64,
                context,
                last_prompt: first_user_message
                    .filter(|m| !m.is_empty())
                    .map(|m| truncate(&m, 200)),
                sub_agent_count: 0,
                proc_stats: None,
            })
        })?;

        rows.collect()
    }
}

impl Collector for CodexCollector {
    fn name(&self) -> &'static str {
        "codex"
    }

    fn collect(&mut self, out: &mut Vec<Session>, warnings: &mut Vec<String>) {
        // No DB at all is the common case on a machine that's never run Codex.
        if !self.db_path.exists() {
            return;
        }
        match self.query() {
            Ok(mut sessions) => out.append(&mut sessions),
            Err(err) => warnings.push(format!("codex: {}: {err}", self.db_path.display())),
        }
    }
}

fn truncate(s: &str, max: usize) -> String {
    let s = s.trim();
    if s.chars().count() <= max {
        return s.to_string();
    }
    let mut out: String = s.chars().take(max).collect();
    out.push('…');
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;

    /// Minimal `threads` table holding only the columns the collector reads.
    fn make_db(path: &Path, rows: &[(&str, &str, &str, i64, i64, i64)]) {
        let conn = Connection::open(path).unwrap();
        conn.execute_batch(
            "CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                model TEXT,
                git_branch TEXT,
                cwd TEXT NOT NULL,
                title TEXT,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at_ms INTEGER,
                updated_at_ms INTEGER,
                first_user_message TEXT
            );",
        )
        .unwrap();
        for (id, model, cwd, tokens, updated, archived) in rows {
            conn.execute(
                "INSERT INTO threads (id, model, git_branch, cwd, title, tokens_used, archived, created_at_ms, updated_at_ms, first_user_message)
                 VALUES (?1, ?2, 'main', ?3, 'a title', ?4, ?7, 100, ?5, 'first message')",
                rusqlite::params![id, model, cwd, tokens, updated, archived, archived],
            )
            .unwrap();
        }
    }

    #[test]
    fn reads_recent_threads_newest_first() {
        let tmp = tempfile::tempdir().unwrap();
        let db = tmp.path().join("state.sqlite");
        make_db(
            &db,
            &[
                ("t-old", "gpt-5", "/tmp/repo", 1000, 10, 0),
                ("t-new", "gpt-5", "/tmp/repo", 5000, 20, 0),
                ("t-archived", "gpt-5", "/tmp/repo", 1, 30, 1),
            ],
        );

        let mut c = CodexCollector::new(db);
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);

        assert!(warnings.is_empty(), "warnings: {warnings:?}");
        // Archived thread excluded; newest first.
        assert_eq!(out.len(), 2);
        assert_eq!(out[0].id, "t-new");
        assert_eq!(out[1].id, "t-old");
        assert_eq!(out[0].provider, Provider::Codex);
        assert_eq!(out[0].pid, None);
        let ctx = out[0].context.unwrap();
        assert_eq!(ctx.used, 5000);
    }

    #[test]
    fn empty_db_yields_no_sessions_no_warning() {
        let tmp = tempfile::tempdir().unwrap();
        let db = tmp.path().join("state.sqlite");
        make_db(&db, &[]);

        let mut c = CodexCollector::new(db);
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);
        assert!(out.is_empty());
        assert!(warnings.is_empty());
    }

    #[test]
    fn missing_db_is_silent() {
        let mut c = CodexCollector::new(PathBuf::from("/no/such/state.sqlite"));
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);
        assert!(out.is_empty());
        assert!(warnings.is_empty());
    }
}
