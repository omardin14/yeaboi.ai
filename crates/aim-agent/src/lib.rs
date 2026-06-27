//! Agent providers (`claude`/`codex`) + parallel review orchestrator.
//! Phase 0 stub — depends on [`aim_exec`] for spawning the agent CLIs.

/// Crate marker used by Phase 0 to verify linkage; replaced by `AgentProvider`
/// and `ReviewOrchestrator` in Phase 1.
pub fn placeholder() -> String {
    format!("aim-agent (spawns via {})", aim_exec::placeholder())
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_links_exec() {
        assert!(super::placeholder().contains("aim-exec"));
    }
}
