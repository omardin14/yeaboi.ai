//! OS process introspection for yeaboi.ai.
//!
//! Produces a [`yb_core::ProcTable`] (cpu / memory / uptime / parent + a
//! parent→children adjacency) from `sysinfo`. This is the only OS-specific
//! crate in the Phase 1a data path; `yb-core` stays free of OS calls and
//! consumes the table the enrichment pass joins onto sessions by pid.
//!
//! CPU usage is a *delta* between two refreshes, so a [`Sampler`] keeps its
//! `System` alive across ticks (the `--interval` loop's own delay is the gap).
//! For a one-shot read use [`sample_once`], which waits the minimum interval
//! between the priming refresh and the measurement.

use std::collections::HashMap;

use sysinfo::{ProcessRefreshKind, ProcessesToUpdate, System};
use yb_core::{ProcStats, ProcTable};

pub mod actions;

/// Reusable process sampler. Holds a `System` so CPU deltas accumulate across
/// `sample` calls without an artificial sleep on the hot path.
pub struct Sampler {
    sys: System,
}

impl Sampler {
    /// Create a sampler and take a priming refresh so the next [`Sampler::sample`]
    /// can report a meaningful CPU delta.
    pub fn new() -> Self {
        let mut sys = System::new();
        refresh(&mut sys);
        Sampler { sys }
    }

    /// Refresh and build a fresh [`ProcTable`].
    pub fn sample(&mut self) -> ProcTable {
        refresh(&mut self.sys);
        build_table(&self.sys)
    }
}

impl Default for Sampler {
    fn default() -> Self {
        Self::new()
    }
}

/// Minimum gap `sysinfo` needs between two refreshes for a meaningful CPU
/// reading. Callers driving a [`Sampler`] manually should wait at least this
/// long between [`Sampler::new`] and the first [`Sampler::sample`].
pub fn min_sample_interval() -> std::time::Duration {
    sysinfo::MINIMUM_CPU_UPDATE_INTERVAL
}

/// One-shot sample. Primes, waits the minimum CPU interval, then measures — so
/// even a single `--once`/`--json` read carries real CPU numbers.
pub fn sample_once() -> ProcTable {
    let mut sampler = Sampler::new();
    std::thread::sleep(min_sample_interval());
    sampler.sample()
}

/// Refresh only cpu + memory for every process (parent/run-time come for free).
fn refresh(sys: &mut System) {
    sys.refresh_processes_specifics(
        ProcessesToUpdate::All,
        true,
        ProcessRefreshKind::nothing().with_cpu().with_memory(),
    );
}

fn build_table(sys: &System) -> ProcTable {
    let mut by_pid: HashMap<u32, ProcStats> = HashMap::new();
    let mut children: HashMap<u32, Vec<u32>> = HashMap::new();

    for (pid, process) in sys.processes() {
        let p = pid.as_u32();
        let ppid = process.parent().map(|parent| parent.as_u32());
        by_pid.insert(
            p,
            ProcStats {
                cpu_pct: process.cpu_usage(),
                mem_bytes: process.memory(),
                uptime_secs: process.run_time(),
                ppid,
            },
        );
        if let Some(parent) = ppid {
            children.entry(parent).or_default().push(p);
        }
    }

    ProcTable { by_pid, children }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sampler_includes_current_process() {
        let mut sampler = Sampler::new();
        let table = sampler.sample();
        let me = std::process::id();
        assert!(
            table.by_pid.contains_key(&me),
            "current pid {me} missing from table"
        );
        let stats = table.by_pid[&me];
        assert!(
            stats.mem_bytes > 0,
            "expected non-zero RSS for the test process"
        );
    }

    #[test]
    fn parent_child_adjacency_is_consistent() {
        let table = sample_once();
        // Every child listed under a parent must record that parent as its ppid.
        for (&parent, kids) in &table.children {
            for kid in kids {
                let stats = table.by_pid.get(kid).expect("child must be in by_pid");
                assert_eq!(stats.ppid, Some(parent));
            }
        }
    }
}
