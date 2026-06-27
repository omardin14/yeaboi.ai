//! External command runner — typed spawn/stream/detached over `git`, `gh`,
//! `claude`, `codex`, and per-worktree services. Phase 0 stub.

/// Crate marker used by Phase 0 to verify linkage; replaced by `Cmd` in Phase 1.
pub fn placeholder() -> &'static str {
    "yb-exec"
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_name() {
        assert_eq!(super::placeholder(), "yb-exec");
    }
}
