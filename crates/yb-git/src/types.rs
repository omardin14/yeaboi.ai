//! Shared PR-loop value types, ts-exported for the desktop UI.

use serde::{Deserialize, Serialize};

/// How a PR should be merged.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub enum MergeMethod {
    Merge,
    Squash,
    Rebase,
}

impl MergeMethod {
    /// The `gh pr merge` flag for this method.
    pub fn flag(self) -> &'static str {
        match self {
            MergeMethod::Merge => "--merge",
            MergeMethod::Squash => "--squash",
            MergeMethod::Rebase => "--rebase",
        }
    }
}

/// The result of rebasing a branch onto its base.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub enum RebaseOutcome {
    /// Rebase applied cleanly.
    Clean,
    /// Rebase stopped on conflicts in these files (the rebase is in progress).
    Conflicts(Vec<String>),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merge_method_flags() {
        assert_eq!(MergeMethod::Squash.flag(), "--squash");
        assert_eq!(MergeMethod::Merge.flag(), "--merge");
        assert_eq!(MergeMethod::Rebase.flag(), "--rebase");
    }
}
