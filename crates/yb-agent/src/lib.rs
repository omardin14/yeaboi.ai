//! Agent providers (`claude`/`codex`) + parallel review orchestrator.
//! Phase 0 stub — depends on [`yb_exec`] for spawning the agent CLIs.

// Keep the dependency edge declared until the providers consume it.
use yb_exec as _;

/// Crate marker used by Phase 0 to verify linkage; replaced by `AgentProvider`
/// and `ReviewOrchestrator` in Phase 1.
pub fn placeholder() -> String {
    "yb-agent (spawns via yb-exec)".to_string()
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_links_exec() {
        assert!(super::placeholder().contains("yb-exec"));
    }
}
