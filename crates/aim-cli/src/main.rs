//! ai-manager headless CLI — the same engine the desktop app uses, scriptable.
//!
//! Phase 0 prints a stub [`Snapshot`]; Phase 1 swaps in the real collector path
//! (`--json` / `--once` / `--interval` / `--no-ports`) with no contract change.

use aim_core::Snapshot;
use clap::Parser;

#[derive(Parser, Debug)]
#[command(name = "aim", version, about = "ai-manager headless CLI")]
struct Args {
    /// Emit a single snapshot as JSON and exit.
    #[arg(long)]
    json: bool,

    /// Collect once, print a human-readable frame, then exit.
    #[arg(long)]
    once: bool,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();

    // Phase 0: stub snapshot. Phase 1 replaces this with the collector registry.
    let snap = Snapshot::stub_now();

    if args.json {
        println!("{}", serde_json::to_string_pretty(&snap)?);
        return Ok(());
    }

    // Default and `--once` both render one human frame.
    let _ = args.once;
    println!(
        "ai-manager — {} session(s) @ {}ms",
        snap.sessions.len(),
        snap.generated_at_ms
    );
    for s in &snap.sessions {
        println!("  [{:<4}] {:<20} {}", s.status, s.project, s.id);
    }
    for w in &snap.warnings {
        eprintln!("warning: {w}");
    }
    Ok(())
}
