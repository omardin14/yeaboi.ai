//! `git` wrapper. Runs `git -C <root> …` and turns a non-zero exit into a
//! structured [`GitError`].

use std::path::{Path, PathBuf};

use yb_exec::Cmd;

use crate::GitError;

/// A git repository rooted at `root`.
#[derive(Debug, Clone)]
pub struct GitRepo {
    root: PathBuf,
}

impl GitRepo {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        GitRepo { root: root.into() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Run `git -C <root> <args>`, returning trimmed stdout or a structured error.
    fn run(&self, args: &[&str]) -> Result<String, GitError> {
        let out = Cmd::new("git")
            .arg("-C")
            .arg(&self.root)
            .args(args.iter().copied())
            .output()?;
        if !out.success {
            return Err(GitError::Command {
                args: args.join(" "),
                code: out.status,
                stderr: out.stderr_tail().to_string(),
            });
        }
        Ok(out.stdout.trim_end().to_string())
    }

    /// The current branch name (`HEAD`'s short symbolic name).
    pub fn current_branch(&self) -> Result<String, GitError> {
        self.run(&["rev-parse", "--abbrev-ref", "HEAD"])
    }

    /// The repo's working-tree root.
    pub fn toplevel(&self) -> Result<String, GitError> {
        self.run(&["rev-parse", "--show-toplevel"])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn git(args: &[&str], cwd: &Path) {
        let out = Cmd::new("git")
            .args(args.iter().copied())
            .cwd(cwd)
            .output()
            .expect("run git");
        assert!(out.success, "git {args:?} failed: {}", out.stderr_tail());
    }

    fn git_available() -> bool {
        Cmd::new("git")
            .arg("--version")
            .output()
            .map(|o| o.success)
            .unwrap_or(false)
    }

    #[test]
    fn current_branch_of_a_real_repo() {
        if !git_available() {
            return;
        }
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path();
        git(&["init", "-q"], dir);
        git(&["config", "user.email", "t@t"], dir);
        git(&["config", "user.name", "t"], dir);
        git(&["checkout", "-q", "-b", "work"], dir);
        git(&["commit", "-q", "--allow-empty", "-m", "init"], dir);

        let repo = GitRepo::new(dir);
        assert_eq!(repo.current_branch().unwrap(), "work");
        assert_eq!(
            Path::new(&repo.toplevel().unwrap()).canonicalize().unwrap(),
            dir.canonicalize().unwrap()
        );
    }

    #[test]
    fn non_zero_exit_becomes_structured_error() {
        if !git_available() {
            return;
        }
        // A directory that isn't a git repo → `rev-parse` exits non-zero.
        let tmp = tempfile::tempdir().unwrap();
        let err = GitRepo::new(tmp.path()).current_branch().unwrap_err();
        match err {
            GitError::Command { code, stderr, .. } => {
                assert_ne!(code, Some(0));
                assert!(!stderr.is_empty());
            }
            other => panic!("expected a Command error, got {other:?}"),
        }
    }
}
