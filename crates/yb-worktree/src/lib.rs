//! Worktree engine — modeled on GitHubIssueTriager's decentralized multi-workspace
//! setup (discover-on-read, MD5 ports byte-compatible with `assign-port.ts`).
//! Phase 0 stub — composes [`yb_exec`], [`yb_git`], and [`yb_proc`].

// These became real crates ahead of the worktree engine; keep the architectural
// dependency edges declared until the engine consumes them.
use yb_exec as _;
use yb_git as _;
use yb_proc as _;

/// Crate marker used by Phase 0 to verify the dependency edges; replaced by the
/// `WorktreeEngine` (create/open/list/remove/prune) + `PortAllocator` in Phase 1.
pub fn placeholder() -> String {
    "yb-worktree (yb-exec + yb-git + yb-proc)".to_string()
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
