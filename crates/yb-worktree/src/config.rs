//! Per-repo worktree config: `<repo>/.yeaboi/project.toml`.
//!
//! Everything is optional — a repo with no config gets sensible defaults (the
//! reference port ranges, literal branch names, no lifecycle/services). The
//! lifecycle/service commands are where a repo expresses its own DB isolation
//! (a Neon branch, a Postgres schema clone, …); yeaboi stays DB-agnostic.

use std::collections::BTreeMap;
use std::path::Path;

use serde::Deserialize;

use crate::ports::PortConfig;

/// Parsed `project.toml` (all sections optional).
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct ProjectConfig {
    pub ports: PortConfig,
    /// Ordered name→branch rules; first match wins.
    pub branch_rules: Vec<BranchRule>,
    pub lifecycle: Lifecycle,
    /// Long-lived per-worktree services (dev servers, etc.).
    pub services: Vec<Service>,
    /// Extra env vars written into each worktree's `.env`.
    pub env: BTreeMap<String, String>,
}

/// A regex→template rule, e.g. `^issue-(\d+)$` → `feature/issue-$1`.
#[derive(Debug, Clone, Deserialize)]
pub struct BranchRule {
    pub pattern: String,
    pub template: String,
}

/// Shell commands run on worktree create/remove.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Lifecycle {
    pub setup: Vec<String>,
    pub teardown: Vec<String>,
}

/// A long-lived service started in a worktree.
#[derive(Debug, Clone, Deserialize)]
pub struct Service {
    pub name: String,
    pub cmd: String,
}

impl ProjectConfig {
    /// Load `<repo_root>/.yeaboi/project.toml`, or defaults if it's absent. A
    /// present-but-invalid file degrades to defaults with a logged warning.
    pub fn load(repo_root: &Path) -> Self {
        let path = repo_root.join(".yeaboi").join("project.toml");
        let text = match std::fs::read_to_string(&path) {
            Ok(t) => t,
            Err(_) => return ProjectConfig::default(),
        };
        match toml::from_str(&text) {
            Ok(cfg) => cfg,
            Err(e) => {
                eprintln!("worktree: ignoring invalid {}: {e}", path.display());
                ProjectConfig::default()
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_when_no_file() {
        let tmp = tempfile::tempdir().unwrap();
        let cfg = ProjectConfig::load(tmp.path());
        assert_eq!(cfg.ports.base, 4000);
        assert!(cfg.branch_rules.is_empty());
        assert!(cfg.services.is_empty());
    }

    #[test]
    fn parses_a_full_config() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(tmp.path().join(".yeaboi")).unwrap();
        std::fs::write(
            tmp.path().join(".yeaboi").join("project.toml"),
            r#"
[ports]
base = 5000
worktree_base = 5100
range = 50

[[branch_rules]]
pattern = "^issue-(\\d+)$"
template = "feature/issue-$1"

[lifecycle]
setup = ["pnpm install"]
teardown = ["echo bye"]

[[services]]
name = "dev"
cmd = "pnpm dev"

[env]
FOO = "bar"
"#,
        )
        .unwrap();

        let cfg = ProjectConfig::load(tmp.path());
        assert_eq!(cfg.ports.base, 5000);
        assert_eq!(cfg.ports.range, 50);
        assert_eq!(cfg.branch_rules[0].template, "feature/issue-$1");
        assert_eq!(cfg.lifecycle.setup, vec!["pnpm install".to_string()]);
        assert_eq!(cfg.services[0].name, "dev");
        assert_eq!(cfg.env.get("FOO").map(String::as_str), Some("bar"));
    }

    #[test]
    fn invalid_toml_falls_back_to_defaults() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(tmp.path().join(".yeaboi")).unwrap();
        std::fs::write(
            tmp.path().join(".yeaboi").join("project.toml"),
            "this = is = not = toml",
        )
        .unwrap();
        assert_eq!(ProjectConfig::load(tmp.path()).ports.base, 4000);
    }
}
