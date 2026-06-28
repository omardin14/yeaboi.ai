//! The collect pipeline: run the collectors, resolve each session's project,
//! join the OS process table by pid, and roll everything into a [`Snapshot`].
//!
//! The process table is passed in (filled by `yb-proc`) so this crate never
//! depends upward on an OS-specific crate. `Engine` is stateful — it keeps the
//! collectors' transcript cursors and the project-resolver cache alive across
//! ticks, which is what makes `--interval` cheap.

use std::collections::BTreeMap;

use crate::adapters::{ClaudeCollector, CodexCollector, Collector};
use crate::model::{ActivityStatus, Port, ProcTable, Project, Session, Snapshot, Totals};
use crate::now_ms;
use crate::project::ProjectResolver;

/// Knobs for a collect pass.
#[derive(Debug, Clone, Default)]
pub struct CollectOptions {
    /// Drop sessions whose pid has no live process instead of marking them
    /// [`ActivityStatus::Dead`]. Useful for a clean "what's running now" view.
    pub drop_dead: bool,
}

/// Whether `pid` belongs to a session currently tracked as live (not `Dead`).
///
/// This is the authorization check the desktop `kill_session` command runs
/// before signalling — extracted here so it's unit-testable without a running
/// Tauri app, and so the rule lives next to the model it guards.
pub fn pid_is_live_session(sessions: &[Session], pid: u32) -> bool {
    sessions
        .iter()
        .any(|s| s.pid == Some(pid) && s.status != ActivityStatus::Dead)
}

/// Owns the collectors + resolver and produces snapshots.
pub struct Engine {
    collectors: Vec<Box<dyn Collector>>,
    resolver: ProjectResolver,
    options: CollectOptions,
}

impl Engine {
    /// Build an engine from an explicit collector set.
    pub fn new(collectors: Vec<Box<dyn Collector>>, options: CollectOptions) -> Self {
        Engine {
            collectors,
            resolver: ProjectResolver::new(),
            options,
        }
    }

    /// Build an engine over the live machine's `~/.claude` + `~/.codex`.
    pub fn with_default_sources(options: CollectOptions) -> Self {
        let mut collectors: Vec<Box<dyn Collector>> = Vec::new();
        if let Some(c) = ClaudeCollector::from_home() {
            collectors.push(Box::new(c));
        }
        if let Some(c) = CodexCollector::from_home() {
            collectors.push(Box::new(c));
        }
        Engine::new(collectors, options)
    }

    /// Run one collect pass against the supplied process table and listening
    /// ports. Pass an empty `ports` slice to skip port attribution (`--no-ports`).
    pub fn collect(&mut self, proc: &ProcTable, ports: &[Port]) -> Snapshot {
        let mut sessions: Vec<Session> = Vec::new();
        let mut warnings: Vec<String> = Vec::new();

        for collector in &mut self.collectors {
            collector.collect(&mut sessions, &mut warnings);
        }

        // A resumed session leaves two `sessions/<pid>.json` files sharing one
        // sessionId; keep the most recently updated. Then order most-recent-first
        // so both the JSON and the table are deterministic and top-like.
        dedup_by_id_keep_newest(&mut sessions);
        sessions.sort_by(|a, b| {
            b.updated_at_ms
                .cmp(&a.updated_at_ms)
                .then_with(|| a.id.cmp(&b.id))
        });

        // Resolve projects + join the process table.
        // Projects are keyed in a BTreeMap so the output order is deterministic.
        let mut projects: BTreeMap<String, Project> = BTreeMap::new();

        for session in &mut sessions {
            let resolved = self.resolver.resolve(&session.cwd, &mut warnings);
            session.project_id = resolved.id.clone();
            enrich_with_proc(session, proc);
            attach_ports(session, proc, ports);

            let project = projects
                .entry(resolved.id.clone())
                .or_insert_with(|| Project {
                    id: resolved.id,
                    name: resolved.name,
                    root: resolved.root,
                    remote: resolved.remote,
                    session_ids: Vec::new(),
                    busy_count: 0,
                    session_count: 0,
                });
            project.session_ids.push(session.id.clone());
            project.session_count += 1;
            if session.status == ActivityStatus::Busy {
                project.busy_count += 1;
            }
        }

        if self.options.drop_dead {
            let dropped: std::collections::HashSet<String> = sessions
                .iter()
                .filter(|s| s.status == ActivityStatus::Dead)
                .map(|s| s.id.clone())
                .collect();
            sessions.retain(|s| s.status != ActivityStatus::Dead);
            for project in projects.values_mut() {
                project.session_ids.retain(|id| !dropped.contains(id));
                project.session_count = project.session_ids.len() as u32;
            }
            projects.retain(|_, p| p.session_count > 0);
        }

        let projects: Vec<Project> = projects.into_values().collect();
        let busy_count = sessions
            .iter()
            .filter(|s| s.status == ActivityStatus::Busy)
            .count() as u32;
        let totals = Totals {
            session_count: sessions.len() as u32,
            busy_count,
            project_count: projects.len() as u32,
        };

        Snapshot {
            generated_at_ms: now_ms(),
            projects,
            sessions,
            totals,
            warnings,
        }
    }
}

/// Collapse sessions that share an `id`, keeping the one with the newest
/// `updated_at_ms` (ties broken by a live pid, then by larger pid as a proxy for
/// the more recent process). Preserves first-seen order otherwise.
fn dedup_by_id_keep_newest(sessions: &mut Vec<Session>) {
    use std::collections::HashMap;
    let mut best: HashMap<String, usize> = HashMap::new();
    let mut keep = vec![true; sessions.len()];
    for i in 0..sessions.len() {
        match best.get(&sessions[i].id).copied() {
            Some(j) if !newer(&sessions[i], &sessions[j]) => {
                keep[i] = false; // existing wins
            }
            Some(j) => {
                keep[j] = false; // this one wins
                best.insert(sessions[i].id.clone(), i);
            }
            None => {
                best.insert(sessions[i].id.clone(), i);
            }
        }
    }
    let mut idx = 0;
    sessions.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

/// Is `a` a better representative of a duplicated session id than `b`?
fn newer(a: &Session, b: &Session) -> bool {
    a.updated_at_ms
        .cmp(&b.updated_at_ms)
        .then_with(|| a.pid.cmp(&b.pid))
        == std::cmp::Ordering::Greater
}

/// Attach the listening ports owned by this session's process subtree (its own
/// pid plus descendants — so a dev server spawned by the session counts). Ports
/// are sorted by number for deterministic output.
fn attach_ports(session: &mut Session, proc: &ProcTable, ports: &[Port]) {
    let Some(pid) = session.pid else {
        return;
    };
    if ports.is_empty() {
        return;
    }
    let mut owned: std::collections::HashSet<u32> = proc.subtree(pid).into_iter().collect();
    owned.insert(pid);

    let mut matched: Vec<Port> = ports
        .iter()
        .filter(|p| owned.contains(&p.pid))
        .cloned()
        .collect();
    matched.sort_by_key(|p| p.number);
    session.ports = matched;
}

/// Attach process metrics and refine liveness for a session that has a pid.
/// A live process whose status was `Unknown` becomes `Idle`; a pid with no live
/// process is `Dead` regardless of the (stale) file status. Sessions without a
/// pid (Codex threads) keep the status their collector assigned.
fn enrich_with_proc(session: &mut Session, proc: &ProcTable) {
    let Some(pid) = session.pid else {
        return;
    };
    match proc.by_pid.get(&pid) {
        Some(stats) => {
            session.proc_stats = Some(*stats);
            if session.status == ActivityStatus::Unknown {
                session.status = ActivityStatus::Idle;
            }
        }
        None => {
            session.status = ActivityStatus::Dead;
            session.proc_stats = None;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{HostApp, ProcStats, Provider};
    use std::collections::HashMap;

    /// A collector that emits a fixed session set, for engine-level tests.
    struct FakeCollector(Vec<Session>);
    impl Collector for FakeCollector {
        fn name(&self) -> &'static str {
            "fake"
        }
        fn collect(&mut self, out: &mut Vec<Session>, _warnings: &mut Vec<String>) {
            out.extend(self.0.clone());
        }
    }

    fn session(id: &str, pid: Option<u32>, cwd: &str, status: ActivityStatus) -> Session {
        Session {
            id: id.to_string(),
            pid,
            project_id: String::new(),
            provider: Provider::Claude,
            host_app: HostApp::Cli,
            cwd: cwd.to_string(),
            name: None,
            model: Some("claude-opus-4-8".to_string()),
            status,
            branch: None,
            started_at_ms: 0,
            updated_at_ms: 0,
            context: None,
            last_prompt: None,
            sub_agent_count: 0,
            proc_stats: None,
            ports: Vec::new(),
        }
    }

    fn proc_table_with(pid: u32) -> ProcTable {
        let mut by_pid = HashMap::new();
        by_pid.insert(
            pid,
            ProcStats {
                cpu_pct: 12.5,
                mem_bytes: 1024,
                uptime_secs: 60,
                ppid: Some(1),
            },
        );
        ProcTable {
            by_pid,
            children: HashMap::new(),
        }
    }

    #[test]
    fn live_pid_gets_proc_stats_and_idle_when_unknown() {
        let s = session("a", Some(42), "/tmp/nogit", ActivityStatus::Unknown);
        let mut engine = Engine::new(
            vec![Box::new(FakeCollector(vec![s]))],
            CollectOptions::default(),
        );
        let snap = engine.collect(&proc_table_with(42), &[]);

        assert_eq!(snap.sessions.len(), 1);
        let s = &snap.sessions[0];
        assert_eq!(s.status, ActivityStatus::Idle);
        assert!(s.proc_stats.is_some());
        assert_eq!(s.proc_stats.unwrap().cpu_pct, 12.5);
    }

    #[test]
    fn missing_pid_becomes_dead() {
        let s = session("a", Some(999), "/tmp/nogit", ActivityStatus::Busy);
        let mut engine = Engine::new(
            vec![Box::new(FakeCollector(vec![s]))],
            CollectOptions::default(),
        );
        let snap = engine.collect(&ProcTable::default(), &[]);
        assert_eq!(snap.sessions[0].status, ActivityStatus::Dead);
    }

    #[test]
    fn drop_dead_removes_stale_sessions_and_empty_projects() {
        let live = session("live", Some(42), "/tmp/a", ActivityStatus::Busy);
        let dead = session("dead", Some(999), "/tmp/b", ActivityStatus::Idle);
        let opts = CollectOptions { drop_dead: true };
        let mut engine = Engine::new(vec![Box::new(FakeCollector(vec![live, dead]))], opts);
        let snap = engine.collect(&proc_table_with(42), &[]);

        assert_eq!(snap.sessions.len(), 1);
        assert_eq!(snap.sessions[0].id, "live");
        // /tmp/b project had only the dead session → pruned.
        assert_eq!(snap.totals.project_count, 1);
        assert!(snap.projects.iter().all(|p| p.id != "/tmp/b"));
    }

    #[test]
    fn duplicate_session_id_keeps_newest() {
        // Same id, different pid (a resume) — only the newer one survives.
        let mut old = session("dup", Some(100), "/tmp/x", ActivityStatus::Idle);
        old.updated_at_ms = 10;
        let mut new = session("dup", Some(200), "/tmp/x", ActivityStatus::Busy);
        new.updated_at_ms = 20;
        let mut engine = Engine::new(
            vec![Box::new(FakeCollector(vec![old, new]))],
            CollectOptions::default(),
        );
        let snap = engine.collect(&proc_table_with(200), &[]);
        assert_eq!(snap.sessions.len(), 1);
        assert_eq!(snap.sessions[0].pid, Some(200));
        assert_eq!(snap.projects[0].session_ids, vec!["dup".to_string()]);
    }

    #[test]
    fn attaches_ports_owned_by_the_session_subtree() {
        use crate::model::Port;
        // Session pid 42 has child 100 (a dev server). Port 5173 is held by the
        // child, 9999 by an unrelated pid.
        let mut by_pid = HashMap::new();
        for p in [42u32, 100] {
            by_pid.insert(
                p,
                ProcStats {
                    cpu_pct: 0.0,
                    mem_bytes: 1,
                    uptime_secs: 1,
                    ppid: None,
                },
            );
        }
        let mut children = HashMap::new();
        children.insert(42u32, vec![100u32]);
        let proc = ProcTable { by_pid, children };

        let ports = vec![
            Port {
                number: 5173,
                pid: 100,
                state: "LISTEN".into(),
            },
            Port {
                number: 9999,
                pid: 777,
                state: "LISTEN".into(),
            },
        ];

        let s = session("a", Some(42), "/tmp/x", ActivityStatus::Busy);
        let mut engine = Engine::new(
            vec![Box::new(FakeCollector(vec![s]))],
            CollectOptions::default(),
        );
        let snap = engine.collect(&proc, &ports);

        let ports = &snap.sessions[0].ports;
        assert_eq!(ports.len(), 1, "only the subtree-owned port attaches");
        assert_eq!(ports[0].number, 5173);
        assert_eq!(ports[0].pid, 100);
    }

    #[test]
    fn pid_is_live_session_gate() {
        let sessions = vec![
            session("live", Some(100), "/tmp/a", ActivityStatus::Idle),
            session("dead", Some(200), "/tmp/b", ActivityStatus::Dead),
        ];
        // tracked + live → allowed
        assert!(pid_is_live_session(&sessions, 100));
        // tracked but Dead → refused
        assert!(!pid_is_live_session(&sessions, 200));
        // untracked pid → refused
        assert!(!pid_is_live_session(&sessions, 999));
    }

    #[test]
    fn duplicate_session_id_equal_timestamp_breaks_tie_on_pid() {
        // Identical updated_at_ms → the larger pid (more recent process) wins.
        let mut a = session("dup", Some(100), "/tmp/x", ActivityStatus::Idle);
        a.updated_at_ms = 50;
        let mut b = session("dup", Some(300), "/tmp/x", ActivityStatus::Idle);
        b.updated_at_ms = 50;
        let mut engine = Engine::new(
            vec![Box::new(FakeCollector(vec![a, b]))],
            CollectOptions::default(),
        );
        let snap = engine.collect(&proc_table_with(300), &[]);
        assert_eq!(snap.sessions.len(), 1);
        assert_eq!(snap.sessions[0].pid, Some(300));
    }

    #[test]
    fn rolls_sessions_into_projects_and_totals() {
        // Two sessions in the same non-git dir roll up under one project.
        let a = session("a", Some(42), "/tmp/shared", ActivityStatus::Busy);
        let b = session("b", None, "/tmp/shared", ActivityStatus::Idle);
        let mut engine = Engine::new(
            vec![Box::new(FakeCollector(vec![a, b]))],
            CollectOptions::default(),
        );
        let snap = engine.collect(&proc_table_with(42), &[]);

        assert_eq!(snap.totals.session_count, 2);
        assert_eq!(snap.totals.busy_count, 1);
        assert_eq!(snap.totals.project_count, 1);
        let p = &snap.projects[0];
        assert_eq!(p.session_count, 2);
        assert_eq!(p.busy_count, 1);
        assert_eq!(p.session_ids.len(), 2);
    }
}
