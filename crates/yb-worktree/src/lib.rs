//! Worktree engine — modeled on GitHubIssueTriager's decentralized multi-workspace
//! setup (discover-on-read, MD5 ports byte-compatible with `assign-port.ts`).
//! Phase 0 stub — composes [`yb_exec`], [`yb_git`], and [`yb_proc`].

// `yb-proc` became a real crate (process sampler) ahead of the worktree engine;
// keep the architectural dependency edge declared until the engine uses it.
use yb_proc as _;

/// Crate marker used by Phase 0 to verify the dependency edges; replaced by the
/// `WorktreeEngine` (create/open/list/remove/prune) + `PortAllocator` in Phase 1.
pub fn placeholder() -> String {
    format!(
        "yb-worktree ({} + {} + yb-proc)",
        yb_exec::placeholder(),
        yb_git::placeholder(),
    )
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_links_all_edges() {
        let s = super::placeholder();
        assert!(s.contains("yb-exec"));
        assert!(s.contains("yb-git"));
        assert!(s.contains("yb-proc"));
    }
}
