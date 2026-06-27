//! Typed wrappers over `git` + `gh` (PR list/diff/create/merge/review,
//! rebase/conflicts). Phase 0 stub — depends on [`aim_exec`] for spawning.

/// Crate marker used by Phase 0 to verify linkage; replaced by `GitRepo`/`Gh`
/// in Phase 1.
pub fn placeholder() -> String {
    format!("aim-git (runs via {})", aim_exec::placeholder())
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_links_exec() {
        assert!(super::placeholder().contains("aim-exec"));
    }
}
