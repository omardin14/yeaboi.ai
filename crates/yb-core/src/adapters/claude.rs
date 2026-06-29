//! Claude collector: two tiers over `~/.claude`.
//!
//! * **Tier A** — parse each `sessions/<pid>.json` (small; `status` may be
//!   absent) for pid/cwd/started/updated/entrypoint/name.
//! * **Tier B** — tail each session's transcript incrementally via a byte
//!   [`TranscriptCursor`], deriving the latest model + context usage, the most
//!   recent prompt, the git branch, and a best-effort sub-agent count. The
//!   cursor only reads bytes appended since the last tick (whole-file on the
//!   first read), and resets if the file is truncated/rotated.

use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use serde::Deserialize;

use super::Collector;
use crate::model::windows::context_window;
use crate::model::{ActivityStatus, ContextUsage, HostApp, Provider, Session};

/// Collector over a `~/.claude` directory.
pub struct ClaudeCollector {
    claude_home: PathBuf,
    /// sessionId → transcript tail state, persisted across ticks.
    cursors: HashMap<String, TranscriptCursor>,
    /// model → context window, sourced from `stats-cache.json` when available.
    window_overrides: HashMap<String, u64>,
    stats_loaded: bool,
}

impl ClaudeCollector {
    /// Collector rooted at an explicit `~/.claude` path (used by tests).
    pub fn new(claude_home: PathBuf) -> Self {
        ClaudeCollector {
            claude_home,
            cursors: HashMap::new(),
            window_overrides: HashMap::new(),
            stats_loaded: false,
        }
    }

    /// Collector rooted at `$HOME/.claude`. Returns `None` if `$HOME` is unset.
    pub fn from_home() -> Option<Self> {
        let home = std::env::var_os("HOME")?;
        Some(Self::new(Path::new(&home).join(".claude")))
    }

    fn sessions_dir(&self) -> PathBuf {
        self.claude_home.join("sessions")
    }

    fn projects_dir(&self) -> PathBuf {
        self.claude_home.join("projects")
    }

    /// Context window for `model`, preferring the `stats-cache.json` value.
    fn window_for(&self, model: &str) -> u64 {
        self.window_overrides
            .get(model)
            .copied()
            .unwrap_or_else(|| context_window(model))
    }

    /// Load per-model `contextWindow` from `stats-cache.json` once. A missing
    /// file is the normal case (silent); a present-but-unreadable or corrupt
    /// file degrades to the static window table and is surfaced as a warning.
    fn ensure_stats_loaded(&mut self, warnings: &mut Vec<String>) {
        if self.stats_loaded {
            return;
        }
        self.stats_loaded = true;
        let path = self.claude_home.join("stats-cache.json");
        let text = match std::fs::read_to_string(&path) {
            Ok(t) => t,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return,
            Err(e) => {
                warnings.push(format!("claude: cannot read {}: {e}", path.display()));
                return;
            }
        };
        match serde_json::from_str::<StatsCache>(&text) {
            Ok(stats) => {
                for (model, usage) in stats.model_usage {
                    if let Some(w) = usage.context_window {
                        self.window_overrides.insert(model, w);
                    }
                }
            }
            Err(e) => {
                warnings.push(format!(
                    "claude: ignoring unparseable {} ({e}); using the static window table",
                    path.display()
                ));
            }
        }
    }
}

impl Collector for ClaudeCollector {
    fn name(&self) -> &'static str {
        "claude"
    }

    fn collect(&mut self, out: &mut Vec<Session>, warnings: &mut Vec<String>) {
        self.ensure_stats_loaded(warnings);

        let dir = self.sessions_dir();
        let entries = match std::fs::read_dir(&dir) {
            Ok(e) => e,
            Err(err) => {
                // Missing dir is normal on a machine that's never run Claude.
                if err.kind() != std::io::ErrorKind::NotFound {
                    warnings.push(format!("claude: cannot read {}: {err}", dir.display()));
                }
                return;
            }
        };

        for entry in entries {
            // Don't silently drop an unreadable directory entry (e.g. EACCES) —
            // a session would vanish with no trace.
            let entry = match entry {
                Ok(e) => e,
                Err(err) => {
                    warnings.push(format!(
                        "claude: cannot read entry in {}: {err}",
                        dir.display()
                    ));
                    continue;
                }
            };
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            match self.collect_one(&path, warnings) {
                Ok(Some(session)) => out.push(session),
                Ok(None) => {}
                Err(err) => warnings.push(format!("claude: {}: {err}", path.display())),
            }
        }
    }
}

impl ClaudeCollector {
    fn collect_one(
        &mut self,
        session_path: &Path,
        warnings: &mut Vec<String>,
    ) -> std::io::Result<Option<Session>> {
        let text = std::fs::read_to_string(session_path)?;
        // A half-written or schema-drifted file: surface as an InvalidData error
        // the caller turns into a warning.
        let raw: RawSessionFile = serde_json::from_str(&text)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;

        // Tier B: tail the transcript for model / usage / prompt / branch.
        let tail = self.tail_transcript(&raw.session_id, warnings);

        let model = tail.model.clone();
        let context = tail.used_tokens.map(|used| {
            let window = model
                .as_deref()
                .map(|m| self.window_for(m))
                .unwrap_or(200_000);
            // A turn can't occupy more than its window; if `used` exceeds it our
            // model→window table under-detected (e.g. a 1M-context Opus session
            // reporting a bare `claude-opus-4-8` id) — widen to the smallest
            // tier that actually holds `used` so the % isn't pinned at 100.
            let window = if used > window { 1_000_000 } else { window };
            ContextUsage::new(used, window)
        });

        let status = match raw.status.as_deref() {
            Some("busy") => ActivityStatus::Busy,
            Some("idle") => ActivityStatus::Idle,
            // Absent or unrecognised — the engine refines this from the proc table.
            _ => ActivityStatus::Unknown,
        };

        let updated_at_ms = raw
            .updated_at
            .or(raw.status_updated_at)
            .unwrap_or(raw.started_at);

        // Paused on a tool-use (a permission prompt is the common cause) while
        // not actively working. The engine clears this if the pid is dead.
        let awaiting_permission = tail.pending_tool_use && status != ActivityStatus::Busy;

        Ok(Some(Session {
            id: raw.session_id,
            pid: Some(raw.pid),
            project_id: raw.cwd.clone(), // placeholder; engine resolves the real project
            provider: Provider::Claude,
            host_app: HostApp::from_entrypoint(&raw.entrypoint),
            cwd: raw.cwd,
            name: raw.name,
            model,
            status,
            branch: tail.branch,
            started_at_ms: raw.started_at,
            updated_at_ms,
            context,
            last_prompt: tail.last_prompt,
            sub_agent_count: tail.sub_agent_count,
            awaiting_permission,
            proc_stats: None,
            ports: Vec::new(),
        }))
    }

    /// Read newly-appended transcript bytes for `session_id` and fold them into
    /// the persisted cursor, returning the cursor's current derived state.
    fn tail_transcript(&mut self, session_id: &str, warnings: &mut Vec<String>) -> TranscriptState {
        use std::collections::hash_map::Entry;
        // Resolve (and cache) the transcript path on first sighting.
        let projects = self.projects_dir();
        let cursor = match self.cursors.entry(session_id.to_string()) {
            Entry::Occupied(e) => e.into_mut(),
            Entry::Vacant(e) => {
                let path = find_transcript(&projects, session_id, warnings);
                e.insert(TranscriptCursor::new(path))
            }
        };

        cursor.advance(warnings);
        cursor.state.clone()
    }
}

/// Locate `<session_id>.jsonl` under any `projects/*/` subdir. Robust against
/// the cwd→dirname encoding (which we don't try to reproduce). An absent
/// `projects/` dir is normal (silent `None`); an *unreadable* one is surfaced.
fn find_transcript(
    projects_dir: &Path,
    session_id: &str,
    warnings: &mut Vec<String>,
) -> Option<PathBuf> {
    let file_name = format!("{session_id}.jsonl");
    let entries = match std::fs::read_dir(projects_dir) {
        Ok(e) => e,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return None,
        Err(e) => {
            warnings.push(format!(
                "claude: cannot read {}: {e}",
                projects_dir.display()
            ));
            return None;
        }
    };
    for entry in entries {
        let Ok(entry) = entry else { continue };
        if entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            let candidate = entry.path().join(&file_name);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

/// Read a session's transcript into a replay timeline (most recent `limit`
/// entries). A *missing* transcript is normal → empty list; a genuine read
/// failure on a transcript that exists is surfaced as an error.
pub fn transcript_events(
    claude_home: &Path,
    session_id: &str,
    limit: usize,
) -> std::io::Result<Vec<crate::model::TranscriptEvent>> {
    let projects = claude_home.join("projects");
    let Some(path) = find_transcript(&projects, session_id, &mut Vec::new()) else {
        return Ok(Vec::new());
    };
    let text = std::fs::read_to_string(&path)?;

    let mut events: Vec<crate::model::TranscriptEvent> =
        text.lines().flat_map(events_from_line).collect();
    // Keep the most recent `limit`; drain the older prefix (saturating, so a
    // short transcript never underflows).
    let drop = events.len().saturating_sub(limit);
    events.drain(0..drop);
    Ok(events)
}

/// Scan a session's transcript for the sub-agents (`Task`/`Agent` tool calls)
/// it launched — type, description, and whether the result came back yet
/// (matched by tool-call id). A missing transcript → empty.
pub fn transcript_sub_agents(
    claude_home: &Path,
    session_id: &str,
) -> std::io::Result<Vec<crate::model::SubAgent>> {
    let projects = claude_home.join("projects");
    let Some(path) = find_transcript(&projects, session_id, &mut Vec::new()) else {
        return Ok(Vec::new());
    };
    let text = std::fs::read_to_string(&path)?;

    // Calls (id, type, description) in order, and the ids whose results landed.
    let mut calls: Vec<(String, String, String)> = Vec::new();
    let mut completed: std::collections::HashSet<String> = std::collections::HashSet::new();
    for line in text.lines() {
        collect_sub_agent_line(line, &mut calls, &mut completed);
    }
    Ok(calls
        .into_iter()
        .map(|(id, kind, description)| crate::model::SubAgent {
            kind,
            description,
            // No id (older transcripts) → assume done, not perpetually "running".
            done: id.is_empty() || completed.contains(&id),
        })
        .collect())
}

fn collect_sub_agent_line(
    line: &str,
    calls: &mut Vec<(String, String, String)>,
    completed: &mut std::collections::HashSet<String>,
) {
    use serde_json::Value;
    let Ok(v) = serde_json::from_str::<Value>(line.trim()) else {
        return;
    };
    let kind = v.get("type").and_then(Value::as_str);
    let Some(blocks) = v
        .get("message")
        .and_then(|m| m.get("content"))
        .and_then(Value::as_array)
    else {
        return;
    };
    match kind {
        Some("assistant") => {
            for b in blocks {
                if b.get("type").and_then(Value::as_str) != Some("tool_use") {
                    continue;
                }
                let name = b.get("name").and_then(Value::as_str).unwrap_or("");
                if name != "Task" && name != "Agent" {
                    continue;
                }
                let id = b
                    .get("id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let input = b.get("input");
                let field = |k: &str| {
                    input
                        .and_then(|i| i.get(k))
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string()
                };
                calls.push((
                    id,
                    field("subagent_type"),
                    crate::util::truncate(&field("description"), 200),
                ));
            }
        }
        Some("user") => {
            for b in blocks {
                if b.get("type").and_then(Value::as_str) == Some("tool_result")
                    && let Some(id) = b.get("tool_use_id").and_then(Value::as_str)
                {
                    completed.insert(id.to_string());
                }
            }
        }
        _ => {}
    }
}

/// Build a single transcript event (`summary` compact, `text` full).
fn event(kind: &str, full: &str, at: &str) -> crate::model::TranscriptEvent {
    crate::model::TranscriptEvent {
        kind: kind.to_string(),
        summary: crate::util::truncate(full, 160),
        // Generously bounded so one huge tool result can't bloat the wire.
        text: crate::util::truncate(full, 4000),
        at: at.to_string(),
        model: String::new(),
        in_tokens: 0,
        out_tokens: 0,
    }
}

/// Segment one transcript line into atomic, speaker-attributed events: an
/// assistant line fans out into its text / thinking / tool-call blocks, and a
/// user line into the real prompt and/or any tool-result outputs. Everything
/// else — `system`, `last-prompt`, meta/structural lines — is dropped so the
/// reader shows only the actual conversation + tool activity.
fn events_from_line(line: &str) -> Vec<crate::model::TranscriptEvent> {
    use serde_json::Value;
    let Ok(v) = serde_json::from_str::<Value>(line.trim()) else {
        return Vec::new();
    };
    // Injected/meta lines (caveats, command echoes, hook noise) are not the
    // conversation — skip them outright.
    if v.get("isMeta").and_then(Value::as_bool) == Some(true) {
        return Vec::new();
    }
    let at = v.get("timestamp").and_then(Value::as_str).unwrap_or("");
    match v.get("type").and_then(Value::as_str) {
        Some("assistant") => assistant_events(&v, at),
        Some("user") => user_events(&v, at),
        _ => Vec::new(),
    }
}

/// Context tokens (input + both cache reads) and generated tokens for a turn.
fn turn_tokens(message: &serde_json::Value) -> (u32, u32) {
    let u = message.get("usage");
    let get = |k: &str| -> u32 {
        u.and_then(|u| u.get(k))
            .and_then(serde_json::Value::as_u64)
            .unwrap_or(0) as u32
    };
    let input =
        get("input_tokens") + get("cache_creation_input_tokens") + get("cache_read_input_tokens");
    (input, get("output_tokens"))
}

fn assistant_events(v: &serde_json::Value, at: &str) -> Vec<crate::model::TranscriptEvent> {
    use serde_json::Value;
    let message = v.get("message");
    let model = message
        .and_then(|m| m.get("model"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let (in_tokens, out_tokens) = message.map(turn_tokens).unwrap_or((0, 0));
    // Attach the turn's model/usage to the first emitted segment only.
    let tag = |e: crate::model::TranscriptEvent, first: bool| crate::model::TranscriptEvent {
        model: model.clone(),
        in_tokens: if first { in_tokens } else { 0 },
        out_tokens: if first { out_tokens } else { 0 },
        ..e
    };

    let Some(blocks) = message
        .and_then(|m| m.get("content"))
        .and_then(Value::as_array)
    else {
        return vec![tag(event("assistant", "(assistant)", at), true)];
    };
    let mut out = Vec::new();
    for b in blocks {
        let ev = match b.get("type").and_then(Value::as_str) {
            Some("text") => {
                let t = b.get("text").and_then(Value::as_str).unwrap_or("").trim();
                if t.is_empty() {
                    continue;
                }
                event("assistant", t, at)
            }
            Some("thinking") => event(
                "thinking",
                b.get("thinking").and_then(Value::as_str).unwrap_or(""),
                at,
            ),
            Some("tool_use") => {
                let name = b.get("name").and_then(Value::as_str).unwrap_or("?");
                event("tool_use", &tool_use_text(name, b.get("input")), at)
            }
            _ => continue,
        };
        let first = out.is_empty();
        out.push(tag(ev, first));
    }
    if out.is_empty() {
        out.push(tag(event("assistant", "(assistant)", at), true));
    }
    out
}

fn user_events(v: &serde_json::Value, at: &str) -> Vec<crate::model::TranscriptEvent> {
    use serde_json::Value;
    let Some(content) = v.get("message").and_then(|m| m.get("content")) else {
        return Vec::new();
    };
    if let Some(s) = content.as_str() {
        let s = s.trim();
        return if s.is_empty() {
            Vec::new()
        } else {
            vec![event("user", s, at)]
        };
    }
    let Some(blocks) = content.as_array() else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for b in blocks {
        match b.get("type").and_then(Value::as_str) {
            Some("text") => {
                let t = b.get("text").and_then(Value::as_str).unwrap_or("").trim();
                if !t.is_empty() {
                    out.push(event("user", t, at));
                }
            }
            // A tool result is the *tool* speaking, not you — its own kind, and
            // we surface the actual output instead of a "(tool result)" stub.
            Some("tool_result") => out.push(event("tool_result", &tool_result_text(b), at)),
            _ => {}
        }
    }
    out
}

/// `Bash: cargo test` style label for a tool call, falling back to pretty JSON.
fn tool_use_text(name: &str, input: Option<&serde_json::Value>) -> String {
    use serde_json::Value;
    let Some(input) = input else {
        return name.to_string();
    };
    let snippet = [
        "command",
        "description",
        "file_path",
        "path",
        "pattern",
        "url",
    ]
    .iter()
    .find_map(|k| input.get(*k).and_then(Value::as_str));
    if let Some(s) = snippet {
        return format!("{name}: {}", s.trim());
    }
    match serde_json::to_string_pretty(input) {
        Ok(p) if !p.is_empty() && p != "null" && p != "{}" => format!("{name}\n{p}"),
        _ => name.to_string(),
    }
}

/// The text a tool returned (string content, or joined text blocks).
fn tool_result_text(block: &serde_json::Value) -> String {
    use serde_json::Value;
    let joined = match block.get("content") {
        Some(Value::String(s)) => s.trim().to_string(),
        Some(Value::Array(arr)) => arr
            .iter()
            .filter_map(|c| c.get("text").and_then(Value::as_str))
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    };
    if joined.trim().is_empty() {
        "(tool result)".to_string()
    } else {
        joined.trim().to_string()
    }
}

/// Derived state accumulated from a transcript tail.
#[derive(Debug, Clone, Default)]
struct TranscriptState {
    model: Option<String>,
    used_tokens: Option<u64>,
    last_prompt: Option<String>,
    branch: Option<String>,
    sub_agent_count: u32,
    /// The last assistant turn issued a tool-use with no `user`/tool-result line
    /// after it — a proxy for "waiting" (incl. a permission prompt).
    pending_tool_use: bool,
}

/// Incremental byte cursor over one transcript file.
struct TranscriptCursor {
    path: Option<PathBuf>,
    byte_offset: u64,
    last_len: u64,
    state: TranscriptState,
    /// True once we've warned about an I/O failure on this path; reset on the
    /// next success so a permanently-unreadable file warns once, not every tick.
    warned: bool,
}

/// Prompts can be long; keep the UI line bounded.
const MAX_PROMPT_LEN: usize = 200;

impl TranscriptCursor {
    fn new(path: Option<PathBuf>) -> Self {
        TranscriptCursor {
            path,
            byte_offset: 0,
            last_len: 0,
            state: TranscriptState::default(),
            warned: false,
        }
    }

    /// Read complete lines appended since the last call, updating `state`.
    /// Resets to a full re-read if the file shrank (truncation/rotation). I/O
    /// failures on an existing transcript are surfaced once via `warnings`
    /// rather than silently leaving the session looking blank.
    fn advance(&mut self, warnings: &mut Vec<String>) {
        let Some(path) = self.path.clone() else {
            return;
        };
        let mut file = match File::open(&path) {
            Ok(f) => f,
            Err(e) => return self.warn_once(warnings, &path, &e),
        };
        let len = match file.metadata() {
            Ok(m) => m.len(),
            Err(e) => return self.warn_once(warnings, &path, &e),
        };

        if len < self.last_len {
            // Truncated/rotated: start over so stale derived state can't linger.
            self.byte_offset = 0;
            self.state = TranscriptState::default();
        }
        if len == self.byte_offset {
            self.last_len = len;
            self.warned = false; // healthy read
            return; // nothing new
        }
        if let Err(e) = file.seek(SeekFrom::Start(self.byte_offset)) {
            return self.warn_once(warnings, &path, &e);
        }

        let mut buf = String::new();
        if let Err(e) = file.take(len - self.byte_offset).read_to_string(&mut buf) {
            // non-UTF8 mid-write can be transient; a real read failure should not
            // hide forever. Warn once and leave the cursor untouched to retry.
            return self.warn_once(warnings, &path, &e);
        }

        // Only consume up to the last complete line; a trailing partial line is
        // left for the next tick (resuming at a newline avoids UTF-8 straddles).
        if let Some(nl) = buf.rfind('\n') {
            for line in buf[..=nl].lines() {
                self.apply_line(line);
            }
            self.byte_offset += (nl + 1) as u64;
        }
        self.last_len = len;
        self.warned = false; // healthy read
    }

    /// Emit a degradation warning at most once per unhealthy streak.
    fn warn_once(&mut self, warnings: &mut Vec<String>, path: &Path, err: &std::io::Error) {
        if !self.warned {
            self.warned = true;
            warnings.push(format!(
                "claude: cannot tail transcript {}: {err}",
                path.display()
            ));
        }
    }

    fn apply_line(&mut self, line: &str) {
        let line = line.trim();
        if line.is_empty() {
            return;
        }
        let parsed: RawLine = match serde_json::from_str(line) {
            Ok(p) => p,
            Err(_) => return, // unknown/drifted line shape: skip
        };
        match parsed {
            RawLine::Assistant {
                message,
                git_branch,
            } => {
                // Claude Code injects `<synthetic>` assistant turns (e.g. for
                // local slash-commands); keep the last *real* model instead.
                if let Some(m) = message
                    .model
                    .filter(|m| m != "<synthetic>" && !m.is_empty())
                {
                    self.state.model = Some(m);
                }
                if let Some(u) = message.usage {
                    self.state.used_tokens = Some(
                        u.input_tokens + u.cache_creation_input_tokens + u.cache_read_input_tokens,
                    );
                }
                let mut saw_tool_use = false;
                for block in message.content {
                    if let ContentBlock::ToolUse { name } = block {
                        saw_tool_use = true;
                        if name == "Task" || name == "Agent" {
                            self.state.sub_agent_count += 1;
                        }
                    }
                }
                // A turn that ends in a tool-use is "pending" until a user line
                // (the tool result / next prompt) lands.
                if saw_tool_use {
                    self.state.pending_tool_use = true;
                }
                if let Some(b) = git_branch.filter(|b| !b.is_empty()) {
                    self.state.branch = Some(b);
                }
            }
            RawLine::User { git_branch } => {
                self.state.pending_tool_use = false;
                if let Some(b) = git_branch.filter(|b| !b.is_empty()) {
                    self.state.branch = Some(b);
                }
            }
            RawLine::LastPrompt { last_prompt } => {
                self.state.last_prompt = Some(crate::util::truncate(&last_prompt, MAX_PROMPT_LEN));
            }
            RawLine::Other => {}
        }
    }
}

// ---- raw serde shapes -------------------------------------------------------

#[derive(Debug, Deserialize)]
struct RawSessionFile {
    pid: u32,
    #[serde(rename = "sessionId")]
    session_id: String,
    cwd: String,
    #[serde(default)]
    status: Option<String>,
    #[serde(default, rename = "startedAt")]
    started_at: u64,
    #[serde(default, rename = "updatedAt")]
    updated_at: Option<u64>,
    #[serde(default, rename = "statusUpdatedAt")]
    status_updated_at: Option<u64>,
    #[serde(default)]
    entrypoint: String,
    #[serde(default)]
    name: Option<String>,
}

/// A transcript line. Internally tagged by `type`; unknown types fold into
/// [`RawLine::Other`] and are skipped cheaply.
#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
enum RawLine {
    #[serde(rename = "assistant")]
    Assistant {
        message: AssistantMessage,
        #[serde(default, rename = "gitBranch")]
        git_branch: Option<String>,
    },
    #[serde(rename = "user")]
    User {
        #[serde(default, rename = "gitBranch")]
        git_branch: Option<String>,
    },
    #[serde(rename = "last-prompt")]
    LastPrompt {
        #[serde(rename = "lastPrompt")]
        last_prompt: String,
    },
    #[serde(other)]
    Other,
}

#[derive(Debug, Deserialize)]
struct AssistantMessage {
    #[serde(default)]
    model: Option<String>,
    #[serde(default)]
    usage: Option<Usage>,
    #[serde(default)]
    content: Vec<ContentBlock>,
}

#[derive(Debug, Deserialize)]
struct Usage {
    #[serde(default)]
    input_tokens: u64,
    #[serde(default)]
    cache_creation_input_tokens: u64,
    #[serde(default)]
    cache_read_input_tokens: u64,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
enum ContentBlock {
    #[serde(rename = "tool_use")]
    ToolUse {
        #[serde(default)]
        name: String,
    },
    #[serde(other)]
    Other,
}

#[derive(Debug, Deserialize)]
struct StatsCache {
    #[serde(default, rename = "modelUsage")]
    model_usage: HashMap<String, StatsModelUsage>,
}

#[derive(Debug, Deserialize)]
struct StatsModelUsage {
    #[serde(default, rename = "contextWindow")]
    context_window: Option<u64>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    /// Fold an entire transcript in one shot (the oracle).
    fn parse_whole(lines: &[&str]) -> TranscriptState {
        let mut c = TranscriptCursor::new(None);
        for l in lines {
            c.apply_line(l);
        }
        c.state
    }

    const ASSISTANT: &str = r#"{"type":"assistant","gitBranch":"main","message":{"model":"claude-opus-4-8","usage":{"input_tokens":1,"cache_creation_input_tokens":111,"cache_read_input_tokens":144481,"output_tokens":50},"content":[{"type":"text","text":"hi"}]}}"#;
    const LAST_PROMPT: &str = r#"{"type":"last-prompt","lastPrompt":"do the thing"}"#;
    const SUBAGENT: &str = r#"{"type":"assistant","message":{"model":"claude-opus-4-8","content":[{"type":"tool_use","name":"Task"}]}}"#;
    const UNKNOWN: &str = r#"{"type":"file-history-snapshot","foo":1}"#;

    #[test]
    fn derives_model_usage_prompt_branch() {
        let st = parse_whole(&[UNKNOWN, ASSISTANT, LAST_PROMPT]);
        assert_eq!(st.model.as_deref(), Some("claude-opus-4-8"));
        assert_eq!(st.used_tokens, Some(1 + 111 + 144_481));
        assert_eq!(st.last_prompt.as_deref(), Some("do the thing"));
        assert_eq!(st.branch.as_deref(), Some("main"));
    }

    #[test]
    fn counts_subagent_tool_uses() {
        let st = parse_whole(&[SUBAGENT, ASSISTANT, SUBAGENT]);
        assert_eq!(st.sub_agent_count, 2);
    }

    #[test]
    fn unknown_lines_are_skipped() {
        let st = parse_whole(&[UNKNOWN, UNKNOWN]);
        assert!(st.model.is_none());
        assert!(st.used_tokens.is_none());
    }

    /// Incremental tailing must equal a single whole-file parse (the core
    /// correctness property of the cursor).
    #[test]
    fn incremental_equals_whole_file_oracle() {
        let all = [UNKNOWN, ASSISTANT, SUBAGENT, LAST_PROMPT];
        let oracle = parse_whole(&all);

        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("t.jsonl");

        // Write the first half, advance, append the rest, advance again.
        {
            let mut f = File::create(&path).unwrap();
            writeln!(f, "{}", all[0]).unwrap();
            writeln!(f, "{}", all[1]).unwrap();
        }
        let mut cursor = TranscriptCursor::new(Some(path.clone()));
        cursor.advance(&mut Vec::new());
        {
            let mut f = File::options().append(true).open(&path).unwrap();
            writeln!(f, "{}", all[2]).unwrap();
            writeln!(f, "{}", all[3]).unwrap();
        }
        cursor.advance(&mut Vec::new());

        assert_eq!(cursor.state.model, oracle.model);
        assert_eq!(cursor.state.used_tokens, oracle.used_tokens);
        assert_eq!(cursor.state.sub_agent_count, oracle.sub_agent_count);
        assert_eq!(cursor.state.last_prompt, oracle.last_prompt);
    }

    /// A trailing partial line (no newline yet) must not be consumed until the
    /// writer finishes it.
    #[test]
    fn partial_trailing_line_waits_for_newline() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("t.jsonl");
        {
            let mut f = File::create(&path).unwrap();
            write!(f, "{}", ASSISTANT).unwrap(); // no newline
        }
        let mut cursor = TranscriptCursor::new(Some(path.clone()));
        cursor.advance(&mut Vec::new());
        assert!(
            cursor.state.model.is_none(),
            "partial line consumed too early"
        );

        // Finish the line.
        {
            let mut f = File::options().append(true).open(&path).unwrap();
            writeln!(f).unwrap();
        }
        cursor.advance(&mut Vec::new());
        assert_eq!(cursor.state.model.as_deref(), Some("claude-opus-4-8"));
    }

    #[test]
    fn truncation_resets_the_cursor() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("t.jsonl");
        {
            let mut f = File::create(&path).unwrap();
            writeln!(f, "{}", ASSISTANT).unwrap();
        }
        let mut cursor = TranscriptCursor::new(Some(path.clone()));
        cursor.advance(&mut Vec::new());
        assert!(cursor.state.used_tokens.is_some());
        let offset_before = cursor.byte_offset;
        assert!(offset_before > 0);

        // Rotate the file to something shorter.
        {
            let mut f = File::create(&path).unwrap();
            writeln!(f, "{}", LAST_PROMPT).unwrap();
        }
        cursor.advance(&mut Vec::new());
        // Test the mechanism, not a byte-length coincidence: the cursor must have
        // rewound to re-read the rotated file from the start.
        assert!(
            cursor.byte_offset <= offset_before,
            "cursor did not rewind on truncation"
        );
        assert!(
            cursor.state.used_tokens.is_none(),
            "stale usage survived truncation"
        );
        assert_eq!(cursor.state.last_prompt.as_deref(), Some("do the thing"));
    }

    #[test]
    fn collector_reads_session_with_missing_status() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        std::fs::create_dir_all(home.join("sessions")).unwrap();
        std::fs::create_dir_all(home.join("projects")).unwrap();
        // No `status` field at all — must parse and yield Unknown.
        std::fs::write(
            home.join("sessions").join("999.json"),
            r#"{"pid":999,"sessionId":"abc","cwd":"/tmp/x","startedAt":42,"entrypoint":"cli"}"#,
        )
        .unwrap();

        let mut c = ClaudeCollector::new(home.to_path_buf());
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);

        assert_eq!(out.len(), 1);
        assert!(warnings.is_empty(), "warnings: {warnings:?}");
        let s = &out[0];
        assert_eq!(s.pid, Some(999));
        assert_eq!(s.status, ActivityStatus::Unknown);
        assert_eq!(s.started_at_ms, 42);
        assert_eq!(s.updated_at_ms, 42); // falls back to started_at
    }

    #[test]
    fn missing_sessions_dir_is_not_an_error() {
        let tmp = tempfile::tempdir().unwrap();
        let mut c = ClaudeCollector::new(tmp.path().join("nope"));
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);
        assert!(out.is_empty());
        assert!(warnings.is_empty());
    }

    const SYNTHETIC: &str =
        r#"{"type":"assistant","message":{"model":"<synthetic>","content":[]}}"#;

    #[test]
    fn synthetic_model_does_not_clobber_the_real_one() {
        // A `<synthetic>` turn (e.g. a slash-command) must not overwrite the
        // last real model — otherwise every such session would show <synthetic>.
        let st = parse_whole(&[ASSISTANT, SYNTHETIC]);
        assert_eq!(st.model.as_deref(), Some("claude-opus-4-8"));
    }

    /// Build a minimal `~/.claude` with one session + its transcript.
    fn write_session(home: &Path, session_id: &str, session_json: &str, transcript: &[&str]) {
        std::fs::create_dir_all(home.join("sessions")).unwrap();
        let proj = home.join("projects").join("proj");
        std::fs::create_dir_all(&proj).unwrap();
        std::fs::write(home.join("sessions").join("1.json"), session_json).unwrap();
        // Each JSONL line ends in a newline — a trailing partial line is, by
        // design, not consumed until completed.
        let body = format!("{}\n", transcript.join("\n"));
        std::fs::write(proj.join(format!("{session_id}.jsonl")), body).unwrap();
    }

    #[test]
    fn stats_cache_context_window_overrides_the_static_table() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        let assistant = r#"{"type":"assistant","message":{"model":"test-model-x","usage":{"input_tokens":10,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":1},"content":[]}}"#;
        write_session(
            home,
            "sess-x",
            r#"{"pid":1,"sessionId":"sess-x","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli"}"#,
            &[assistant],
        );
        // Unknown model → static table would say 200k; the override must win.
        std::fs::write(
            home.join("stats-cache.json"),
            r#"{"modelUsage":{"test-model-x":{"contextWindow":50000}}}"#,
        )
        .unwrap();

        let mut c = ClaudeCollector::new(home.to_path_buf());
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);

        assert!(warnings.is_empty(), "warnings: {warnings:?}");
        let ctx = out[0].context.expect("usage present");
        assert_eq!(out[0].model.as_deref(), Some("test-model-x"));
        assert_eq!(ctx.window, 50_000, "stats-cache override was not applied");
        assert_eq!(ctx.used, 10);
    }

    #[test]
    fn collector_parses_explicit_busy_and_idle_status() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        std::fs::create_dir_all(home.join("sessions")).unwrap();
        std::fs::create_dir_all(home.join("projects")).unwrap();
        std::fs::write(
            home.join("sessions").join("1.json"),
            r#"{"pid":1,"sessionId":"a","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli","status":"busy"}"#,
        )
        .unwrap();
        std::fs::write(
            home.join("sessions").join("2.json"),
            r#"{"pid":2,"sessionId":"b","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli","status":"idle"}"#,
        )
        .unwrap();

        let mut c = ClaudeCollector::new(home.to_path_buf());
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);

        let busy = out.iter().find(|s| s.id == "a").unwrap();
        let idle = out.iter().find(|s| s.id == "b").unwrap();
        assert_eq!(busy.status, ActivityStatus::Busy);
        assert_eq!(idle.status, ActivityStatus::Idle);
    }

    const TOOL_USE: &str = r#"{"type":"assistant","message":{"model":"claude-opus-4-8","content":[{"type":"tool_use","name":"Bash"}]}}"#;
    const USER: &str =
        r#"{"type":"user","message":{"content":[{"type":"text","text":"go ahead"}]}}"#;

    #[test]
    fn pending_tool_use_sets_awaiting_permission() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        // Transcript ends on an unanswered tool-use; session has no "busy" status.
        write_session(
            home,
            "sess-p",
            r#"{"pid":1,"sessionId":"sess-p","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli"}"#,
            &[ASSISTANT, TOOL_USE],
        );
        let mut c = ClaudeCollector::new(home.to_path_buf());
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);
        assert!(
            out[0].awaiting_permission,
            "should be awaiting after a pending tool-use"
        );
    }

    #[test]
    fn a_following_user_line_clears_awaiting() {
        let st = parse_whole(&[TOOL_USE, USER]);
        assert!(
            !st.pending_tool_use,
            "user line (tool result) clears pending"
        );
    }

    #[test]
    fn awaiting_permission_is_suppressed_while_busy() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        // Same pending tool-use, but the session reports "busy" → not awaiting.
        write_session(
            home,
            "sess-b",
            r#"{"pid":1,"sessionId":"sess-b","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli","status":"busy"}"#,
            &[ASSISTANT, TOOL_USE],
        );
        let mut c = ClaudeCollector::new(home.to_path_buf());
        let mut out = Vec::new();
        c.collect(&mut out, &mut Vec::new());
        assert!(!out[0].awaiting_permission, "busy sessions aren't awaiting");
    }

    #[test]
    fn transcript_events_summarizes_the_timeline() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        write_session(
            home,
            "sess-t",
            r#"{"pid":1,"sessionId":"sess-t","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli"}"#,
            &[USER, ASSISTANT, TOOL_USE],
        );
        let events = transcript_events(home, "sess-t", 100).unwrap();
        // USER → user, ASSISTANT(text) → assistant, TOOL_USE → tool_use.
        assert_eq!(events.len(), 3);
        assert_eq!(events[0].kind, "user");
        assert!(events[0].text.contains("go ahead"));
        assert_eq!(events[1].kind, "assistant");
        assert!(events[1].text.contains("hi"));
        assert_eq!(events[2].kind, "tool_use");
        assert!(events[2].summary.contains("Bash"));
    }

    #[test]
    fn transcript_events_keeps_only_the_most_recent_limit() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        write_session(
            home,
            "sess-l",
            r#"{"pid":1,"sessionId":"sess-l","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli"}"#,
            &[USER, ASSISTANT, TOOL_USE],
        );
        // 3 segmented events; limit 2 → drop the oldest (the user line).
        let events = transcript_events(home, "sess-l", 2).unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].kind, "assistant");
        assert_eq!(events[1].kind, "tool_use");
    }

    #[test]
    fn missing_transcript_is_empty_not_an_error() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(tmp.path().join("projects")).unwrap();
        let events = transcript_events(tmp.path(), "nope", 10).unwrap();
        assert!(events.is_empty());
    }

    #[test]
    fn transcript_sub_agents_lists_calls_with_type_description_and_done() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        // Two Task calls; only the first one's result has come back.
        let t1 = r#"{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Task","input":{"subagent_type":"Explore","description":"map the code"}}]}}"#;
        let r1 = r#"{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"ok"}]}}"#;
        let t2 = r#"{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t2","name":"Task","input":{"subagent_type":"Plan","description":"design it"}}]}}"#;
        let bash = r#"{"type":"assistant","message":{"content":[{"type":"tool_use","id":"b","name":"Bash","input":{"command":"ls"}}]}}"#;
        write_session(
            home,
            "sess-sa",
            r#"{"pid":1,"sessionId":"sess-sa","cwd":"/tmp/x","startedAt":1,"entrypoint":"cli"}"#,
            &[t1, r1, t2, bash],
        );
        let agents = transcript_sub_agents(home, "sess-sa").unwrap();
        // Only Task calls are sub-agents; Bash is ignored.
        assert_eq!(agents.len(), 2);
        assert_eq!(agents[0].kind, "Explore");
        assert!(agents[0].description.contains("map the code"));
        assert!(agents[0].done, "its result came back");
        assert_eq!(agents[1].kind, "Plan");
        assert!(!agents[1].done, "no result yet → still running");
    }

    #[test]
    fn events_from_line_segments_each_arm() {
        // An assistant line fans out into one event per content block, carrying
        // the turn's model + token usage on the first segment.
        let a = events_from_line(
            r#"{"type":"assistant","timestamp":"2026-06-27T21:42:35.935Z","message":{"model":"claude-opus-4-8","usage":{"input_tokens":10,"cache_read_input_tokens":90,"output_tokens":7},"content":[{"type":"thinking","thinking":"hmm"},{"type":"tool_use","name":"Bash","input":{"command":"cargo test"}}]}}"#,
        );
        assert_eq!(a.len(), 2);
        assert_eq!(a[0].kind, "thinking");
        assert_eq!(a[0].text, "hmm");
        assert_eq!(a[0].model, "claude-opus-4-8");
        assert_eq!((a[0].in_tokens, a[0].out_tokens), (100, 7));
        assert_eq!(a[1].kind, "tool_use");
        assert!(a[1].summary.contains("Bash: cargo test"));
        assert_eq!((a[1].in_tokens, a[1].out_tokens), (0, 0)); // only first is tagged
        // The ISO timestamp is carried through.
        assert_eq!(a[0].at, "2026-06-27T21:42:35.935Z");

        // A tool result is its own kind and surfaces the actual output.
        let tr = events_from_line(
            r#"{"type":"user","message":{"content":[{"type":"tool_result","content":"build OK\n3 passed"}]}}"#,
        );
        assert_eq!(tr.len(), 1);
        assert_eq!(tr[0].kind, "tool_result");
        assert!(tr[0].text.contains("3 passed"));

        // A real prompt → a single `user` event.
        let u = events_from_line(
            r#"{"type":"user","message":{"content":[{"type":"text","text":"go ahead"}]}}"#,
        );
        assert_eq!(u.len(), 1);
        assert_eq!(u[0].kind, "user");
        assert!(u[0].text.contains("go ahead"));

        // Empty content, structural/system/meta lines, and unknown types all
        // emit nothing — only the real conversation + tools survive.
        assert!(events_from_line(r#"{"type":"user","message":{"content":[]}}"#).is_empty());
        assert!(events_from_line(r#"{"type":"last-prompt","lastPrompt":"hi"}"#).is_empty());
        assert!(events_from_line(r#"{"type":"system","content":"(system)"}"#).is_empty());
        assert!(events_from_line(r#"{"type":"mode","mode":"normal"}"#).is_empty());
        // isMeta lines (caveats, command echoes) are skipped even when user-typed.
        assert!(
            events_from_line(
                r#"{"type":"user","isMeta":true,"message":{"content":[{"type":"text","text":"caveat"}]}}"#
            )
            .is_empty()
        );
        assert!(events_from_line("not json").is_empty());
    }

    #[test]
    fn unparseable_stats_cache_warns_and_falls_back() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        std::fs::create_dir_all(home.join("sessions")).unwrap();
        std::fs::create_dir_all(home.join("projects")).unwrap();
        std::fs::write(home.join("stats-cache.json"), "{ not valid json").unwrap();

        let mut c = ClaudeCollector::new(home.to_path_buf());
        let mut out = Vec::new();
        let mut warnings = Vec::new();
        c.collect(&mut out, &mut warnings);
        assert_eq!(warnings.len(), 1, "expected one degradation warning");
        assert!(warnings[0].contains("stats-cache.json"));
    }
}
