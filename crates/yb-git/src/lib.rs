//! Typed wrappers over `git` and `gh` (via [`yb_exec`]).
//!
//! Phase 1c ships the read side of the PR loop: [`GitRepo`] (branch/toplevel)
//! and [`Gh`] (PR list / view / diff). Create/merge/rebase/review land in the
//! following slices on the same error-handling spine.

mod gh;
mod git;
mod types;

pub use gh::{Gh, PullRequest, parse_pr_list};
pub use git::GitRepo;
pub use types::{MergeMethod, RebaseOutcome};

use thiserror::Error;

/// A `git` invocation that ran but exited non-zero. Spawn failures come through
/// [`yb_exec::ExecError`] (the `Exec` variant).
#[derive(Debug, Error)]
pub enum GitError {
    #[error("git {args} failed (exit {code:?}): {stderr}")]
    Command {
        args: String,
        code: Option<i32>,
        stderr: String,
    },
    #[error(transparent)]
    Exec(#[from] yb_exec::ExecError),
}

/// A `gh` invocation that failed to run, exited non-zero, or returned
/// unparseable JSON.
#[derive(Debug, Error)]
pub enum GhError {
    #[error("gh {args} failed (exit {code:?}): {stderr}")]
    Command {
        args: String,
        code: Option<i32>,
        stderr: String,
    },
    #[error(transparent)]
    Exec(#[from] yb_exec::ExecError),
    #[error("could not parse gh JSON: {0}")]
    Json(#[from] serde_json::Error),
}
