//! `gh` wrapper for the PR loop. Uses `--json` everywhere so we parse stable
//! machine output rather than scraping human text.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use yb_exec::Cmd;

use crate::{GhError, MergeMethod};

/// The `--json` fields we request for a PR. Kept in one place so list/view agree.
const PR_FIELDS: &str = "number,title,state,headRefName,baseRefName,author,url,isDraft,updatedAt";

/// A pull request, flattened from `gh`'s JSON into the shape the app renders.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct PullRequest {
    #[cfg_attr(feature = "ts", ts(type = "number"))]
    pub number: u64,
    pub title: String,
    /// `OPEN` | `CLOSED` | `MERGED`.
    pub state: String,
    /// Source branch (`headRefName`).
    pub head: String,
    /// Target branch (`baseRefName`).
    pub base: String,
    /// Author login.
    pub author: String,
    pub url: String,
    pub is_draft: bool,
    pub updated_at: String,
}

/// `gh` rooted at a working directory (it infers the repo from cwd).
#[derive(Debug, Clone)]
pub struct Gh {
    cwd: PathBuf,
}

impl Gh {
    pub fn new(cwd: impl Into<PathBuf>) -> Self {
        Gh { cwd: cwd.into() }
    }

    /// Run `gh <args>` in the configured cwd, returning stdout or a structured error.
    fn run(&self, args: &[&str]) -> Result<String, GhError> {
        let out = Cmd::new("gh")
            .args(args.iter().copied())
            .cwd(&self.cwd)
            .output()?;
        if !out.success {
            return Err(GhError::Command {
                args: args.join(" "),
                code: out.status,
                stderr: out.stderr_tail().to_string(),
            });
        }
        Ok(out.stdout)
    }

    /// List up to `limit` pull requests in any state, newest activity first.
    pub fn pr_list(&self, limit: u32) -> Result<Vec<PullRequest>, GhError> {
        let limit = limit.to_string();
        let json = self.run(&[
            "pr", "list", "--state", "all", "--json", PR_FIELDS, "--limit", &limit,
        ])?;
        Ok(parse_pr_list(&json)?)
    }

    /// View a single PR by number.
    pub fn pr_view(&self, number: u64) -> Result<PullRequest, GhError> {
        let number = number.to_string();
        let json = self.run(&["pr", "view", &number, "--json", PR_FIELDS])?;
        let raw: RawPr = serde_json::from_str(&json)?;
        Ok(raw.into())
    }

    /// The unified diff for a PR.
    pub fn pr_diff(&self, number: u64) -> Result<String, GhError> {
        let number = number.to_string();
        self.run(&["pr", "diff", &number])
    }

    /// The open PR whose head is `branch`, if one exists.
    pub fn find_existing(&self, branch: &str) -> Result<Option<PullRequest>, GhError> {
        let json = self.run(&[
            "pr", "list", "--head", branch, "--state", "open", "--json", PR_FIELDS,
        ])?;
        Ok(parse_pr_list(&json)?.into_iter().next())
    }

    /// Open a PR for the current branch against `base`, filling title/body from
    /// commits (`--fill`). Returns the new PR's URL.
    pub fn pr_create(&self, base: &str) -> Result<String, GhError> {
        Ok(self
            .run(&["pr", "create", "--fill", "--base", base])?
            .trim()
            .to_string())
    }

    /// Merge a PR with the given method.
    pub fn pr_merge(&self, number: u64, method: MergeMethod) -> Result<(), GhError> {
        let number = number.to_string();
        self.run(&["pr", "merge", &number, method.flag()])?;
        Ok(())
    }

    /// Post a comment on a PR.
    pub fn pr_comment(&self, number: u64, body: &str) -> Result<(), GhError> {
        let number = number.to_string();
        self.run(&["pr", "comment", &number, "--body", body])?;
        Ok(())
    }
}

/// Parse a `gh pr list --json …` array into [`PullRequest`]s. Split out so the
/// JSON mapping is testable without `gh` installed.
pub fn parse_pr_list(json: &str) -> Result<Vec<PullRequest>, serde_json::Error> {
    let raw: Vec<RawPr> = serde_json::from_str(json)?;
    Ok(raw.into_iter().map(Into::into).collect())
}

// ---- raw gh JSON shapes -----------------------------------------------------

#[derive(Deserialize)]
struct RawPr {
    number: u64,
    title: String,
    state: String,
    #[serde(rename = "headRefName")]
    head: String,
    #[serde(rename = "baseRefName")]
    base: String,
    // GitHub returns `"author": null` for deleted/bot accounts (not just an
    // absent key), so accept null too — `#[serde(default)]` alone wouldn't.
    #[serde(default)]
    author: Option<RawAuthor>,
    url: String,
    #[serde(rename = "isDraft")]
    is_draft: bool,
    #[serde(rename = "updatedAt")]
    updated_at: String,
}

#[derive(Deserialize, Default)]
struct RawAuthor {
    #[serde(default)]
    login: String,
}

impl From<RawPr> for PullRequest {
    fn from(r: RawPr) -> Self {
        PullRequest {
            number: r.number,
            title: r.title,
            state: r.state,
            head: r.head,
            base: r.base,
            author: r.author.unwrap_or_default().login,
            url: r.url,
            is_draft: r.is_draft,
            updated_at: r.updated_at,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURE: &str = r#"[
      {"number":6,"title":"Phase 1b-4: free_port","state":"MERGED",
       "headRefName":"feat/phase-1b4-free-port","baseRefName":"main",
       "author":{"login":"omardin14"},"url":"https://github.com/omardin14/yeaboi.ai/pull/6",
       "isDraft":false,"updatedAt":"2026-06-28T15:49:57Z"},
      {"number":7,"title":"WIP","state":"OPEN","headRefName":"feat/x","baseRefName":"main",
       "author":{"login":"someone"},"url":"https://example/7","isDraft":true,"updatedAt":"2026-06-28T16:00:00Z"}
    ]"#;

    #[test]
    fn parses_pr_list_flattening_author() {
        let prs = parse_pr_list(FIXTURE).expect("parse");
        assert_eq!(prs.len(), 2);

        let first = &prs[0];
        assert_eq!(first.number, 6);
        assert_eq!(first.state, "MERGED");
        assert_eq!(first.head, "feat/phase-1b4-free-port");
        assert_eq!(first.base, "main");
        assert_eq!(first.author, "omardin14"); // nested {login} flattened
        assert!(!first.is_draft);

        assert!(prs[1].is_draft);
        assert_eq!(prs[1].author, "someone");
    }

    #[test]
    fn missing_author_defaults_to_empty() {
        let json = r#"[{"number":1,"title":"t","state":"OPEN","headRefName":"h",
            "baseRefName":"main","url":"u","isDraft":false,"updatedAt":"now"}]"#;
        let prs = parse_pr_list(json).expect("parse");
        assert_eq!(prs[0].author, "");
    }

    #[test]
    fn null_author_is_accepted() {
        // gh returns `"author": null` for deleted/bot accounts.
        let json = r#"[{"number":1,"title":"t","state":"OPEN","headRefName":"h",
            "baseRefName":"main","author":null,"url":"u","isDraft":false,"updatedAt":"now"}]"#;
        let prs = parse_pr_list(json).expect("parse");
        assert_eq!(prs[0].author, "");
    }

    #[test]
    fn malformed_json_is_an_error() {
        assert!(parse_pr_list("{not an array}").is_err());
    }
}
