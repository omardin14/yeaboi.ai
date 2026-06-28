//! Worktree engine — modeled on GitHubIssueTriager's decentralized setup
//! (discover-on-read, no central registry; MD5 ports byte-compatible with
//! `assign-port.ts`).
//!
//! Create/list/remove/prune worktrees, render each one's `.env`, run the repo's
//! configured lifecycle commands (where DB isolation lives), and manage detached
//! per-worktree services. Config is `<repo>/.yeaboi/project.toml` (all optional).

pub mod branch;
pub mod config;
pub mod engine;
pub mod ports;

pub use config::ProjectConfig;
pub use engine::{Worktree, WorktreeEngine, WorktreeError};
pub use ports::PortConfig;
