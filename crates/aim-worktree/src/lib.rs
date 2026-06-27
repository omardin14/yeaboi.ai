//! Worktree engine — modeled on GitHubIssueTriager's decentralized multi-workspace
//! setup (discover-on-read, MD5 ports byte-compatible with `assign-port.ts`).
//! Phase 0 stub — composes [`aim_exec`], [`aim_git`], and [`aim_proc`].

/// Crate marker used by Phase 0 to verify the dependency edges; replaced by the
/// `WorktreeEngine` (create/open/list/remove/prune) + `PortAllocator` in Phase 1.
pub fn placeholder() -> String {
    format!(
        "aim-worktree ({} + {} + {})",
        aim_exec::placeholder(),
        aim_git::placeholder(),
        aim_proc::placeholder(),
    )
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_links_all_edges() {
        let s = super::placeholder();
        assert!(s.contains("aim-exec"));
        assert!(s.contains("aim-git"));
        assert!(s.contains("aim-proc"));
    }
}
