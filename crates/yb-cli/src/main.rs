//! yeaboi.ai headless CLI — the same engine the desktop app uses, scriptable.
//!
//! Reads `~/.claude` + `~/.codex` read-only and prints a live [`Snapshot`]:
//! `--json` for machine consumption, the default/`--once` for a top-style
//! human frame, `--interval <secs>` to refresh in place.

use std::io::Write;

use clap::Parser;
use yb_core::{ActivityStatus, CollectOptions, Engine, Session, Snapshot};

#[derive(Parser, Debug)]
#[command(name = "yeaboi", version, about = "yeaboi.ai headless CLI")]
struct Args {
    /// Emit the snapshot as JSON (one document per tick) instead of a table.
    #[arg(long)]
    json: bool,

    /// Collect once and exit (the default when `--interval` is absent).
    #[arg(long)]
    once: bool,

    /// Refresh every N seconds instead of collecting once.
    #[arg(long, value_name = "SECS")]
    interval: Option<u64>,

    /// Hide stale (dead) sessions whose process is no longer running.
    #[arg(long)]
    hide_dead: bool,

    /// Accepted for forward-compatibility; port collection lands in a later slice.
    #[arg(long)]
    no_ports: bool,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    let _ = args.no_ports; // reserved until lsof port collection lands

    let options = CollectOptions {
        drop_dead: args.hide_dead,
    };
    let mut engine = Engine::with_default_sources(options);

    match args.interval {
        // Streaming mode: keep a Sampler alive so CPU deltas are accurate, and
        // reuse the engine's transcript cursors so each tick stays cheap.
        Some(secs) if !args.once => {
            let secs = secs.max(1);
            let mut sampler = yb_proc::Sampler::new();
            // Prime CPU once before the first frame.
            std::thread::sleep(yb_proc::min_sample_interval());
            loop {
                let proc = sampler.sample();
                let snap = engine.collect(&proc);
                render(&snap, args.json)?;
                std::thread::sleep(std::time::Duration::from_secs(secs));
            }
        }
        // One-shot.
        _ => {
            let proc = yb_proc::sample_once();
            let snap = engine.collect(&proc);
            render(&snap, args.json)?;
            Ok(())
        }
    }
}

fn render(snap: &Snapshot, json: bool) -> anyhow::Result<()> {
    let mut out = std::io::stdout().lock();
    if json {
        serde_json::to_writer_pretty(&mut out, snap)?;
        writeln!(out)?;
    } else {
        write_frame(&mut out, snap)?;
    }
    out.flush()?;
    Ok(())
}

/// Top-style frame: a header, then each project with its sessions indented.
fn write_frame(out: &mut impl Write, snap: &Snapshot) -> std::io::Result<()> {
    writeln!(
        out,
        "yeaboi.ai — {} session(s) · {} busy · {} project(s)",
        snap.totals.session_count, snap.totals.busy_count, snap.totals.project_count
    )?;

    for project in &snap.projects {
        writeln!(
            out,
            "\n{} ({} sessions)",
            project.name, project.session_count
        )?;
        for id in &project.session_ids {
            if let Some(session) = snap.sessions.iter().find(|s| &s.id == id) {
                write_session_row(out, session)?;
            }
        }
    }

    for w in &snap.warnings {
        writeln!(out, "warning: {w}")?;
    }
    Ok(())
}

fn write_session_row(out: &mut impl Write, s: &Session) -> std::io::Result<()> {
    let pid = s.pid.map(|p| p.to_string()).unwrap_or_else(|| "—".into());
    let ctx = s
        .context
        .map(|c| format!("{:>3.0}%", c.pct * 100.0))
        .unwrap_or_else(|| "  —".into());
    let cpu = s
        .proc_stats
        .map(|p| format!("{:>4.0}%", p.cpu_pct))
        .unwrap_or_else(|| "   —".into());
    let mem = s
        .proc_stats
        .map(|p| format!("{:>5}MB", p.mem_bytes / 1_048_576))
        .unwrap_or_else(|| "     —".into());
    let model = s.model.as_deref().unwrap_or("—");
    let branch = s.branch.as_deref().unwrap_or("—");
    let prompt = s.last_prompt.as_deref().unwrap_or("");

    writeln!(
        out,
        "  {:>7}  {:<7}  ctx {}  cpu {}  {}  {:<22}  {:<18}  {}",
        pid,
        status_label(s.status),
        ctx,
        cpu,
        mem,
        truncate(model, 22),
        truncate(branch, 18),
        truncate(prompt, 60),
    )
}

fn status_label(s: ActivityStatus) -> &'static str {
    match s {
        ActivityStatus::Busy => "BUSY",
        ActivityStatus::Idle => "idle",
        ActivityStatus::Dead => "dead",
        ActivityStatus::Unknown => "?",
    }
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    let mut out: String = s.chars().take(max.saturating_sub(1)).collect();
    out.push('…');
    out
}
