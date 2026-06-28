//! `git` wrapper. Runs `git -C <root> …` and turns a non-zero exit into a
//! structured [`GitError`].

use std::path::{Path, PathBuf};

use yb_exec::Cmd;

use crate::{GitError, RebaseOutcome};

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

    /// Push the current branch to `origin`, setting upstream.
    pub fn push_current(&self) -> Result<(), GitError> {
        self.run(&["push", "-u", "origin", "HEAD"])?;
        Ok(())
    }

    /// Files with unresolved merge conflicts (empty when none).
    pub fn list_conflicts(&self) -> Result<Vec<String>, GitError> {
        let out = self.run(&["diff", "--name-only", "--diff-filter=U"])?;
        Ok(out.lines().map(str::to_string).collect())
    }

    /// Fetch `origin/<base>` and rebase the current branch onto it. On conflict
    /// the rebase is left in progress and the conflicting files are returned;
    /// the caller resolves + continues, or aborts.
    pub fn rebase_onto(&self, base: &str) -> Result<RebaseOutcome, GitError> {
        self.run(&["fetch", "origin", base])?;
        let target = format!("origin/{base}");
        let out = Cmd::new("git")
            .arg("-C")
            .arg(&self.root)
            .args(["rebase", &target])
            .output()?;
        if out.success {
            return Ok(RebaseOutcome::Clean);
        }
        // Non-zero may mean conflicts (rebase paused) — report them. If there are
        // none, it's a genuine failure to surface.
        let conflicts = self.list_conflicts()?;
        if conflicts.is_empty() {
            return Err(GitError::Command {
                args: format!("rebase {target}"),
                code: out.status,
                stderr: out.stderr_tail().to_string(),
            });
        }
        Ok(RebaseOutcome::Conflicts(conflicts))
    }

    /// Continue an in-progress rebase after conflicts are resolved.
    pub fn rebase_continue(&self) -> Result<RebaseOutcome, GitError> {
        // `git rebase --continue` needs the editor disabled in non-interactive use.
        let out = Cmd::new("git")
            .arg("-C")
            .arg(&self.root)
            .args(["-c", "core.editor=true", "rebase", "--continue"])
            .output()?;
        if out.success {
            return Ok(RebaseOutcome::Clean);
        }
        let conflicts = self.list_conflicts()?;
        if conflicts.is_empty() {
            return Err(GitError::Command {
                args: "rebase --continue".to_string(),
                code: out.status,
                stderr: out.stderr_tail().to_string(),
            });
        }
        Ok(RebaseOutcome::Conflicts(conflicts))
    }

    /// Abort an in-progress rebase, restoring the pre-rebase state.
    pub fn rebase_abort(&self) -> Result<(), GitError> {
        self.run(&["rebase", "--abort"])?;
        Ok(())
    }

    /// Local branches already merged into `base` (excluding `base` itself).
    pub fn merged_branches(&self, base: &str) -> Result<Vec<String>, GitError> {
        let out = self.run(&["branch", "--merged", base, "--format=%(refname:short)"])?;
        Ok(out
            .lines()
            .map(str::trim)
            .filter(|b| !b.is_empty() && *b != base)
            .map(str::to_string)
            .collect())
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

    /// Init a `work` repo on `main` with a `file.txt`, wired to a bare `origin`
    /// that already has that first commit. Returns the kept tempdirs + work path.
    fn repo_with_origin() -> (tempfile::TempDir, tempfile::TempDir, PathBuf) {
        let origin = tempfile::tempdir().unwrap();
        let work = tempfile::tempdir().unwrap();
        let o = origin.path();
        let w = work.path().to_path_buf();

        git(&["init", "-q", "--bare"], o);
        git(&["init", "-q", "-b", "main"], &w);
        git(&["config", "user.email", "t@t"], &w);
        git(&["config", "user.name", "t"], &w);
        git(&["remote", "add", "origin", &o.to_string_lossy()], &w);
        std::fs::write(w.join("file.txt"), "base\n").unwrap();
        git(&["add", "."], &w);
        git(&["commit", "-q", "-m", "base"], &w);
        git(&["push", "-q", "origin", "main"], &w);
        (origin, work, w)
    }

    fn write_commit(dir: &Path, file: &str, body: &str, msg: &str) {
        std::fs::write(dir.join(file), body).unwrap();
        git(&["add", "."], dir);
        git(&["commit", "-q", "-m", msg], dir);
    }

    #[test]
    fn rebase_onto_is_clean_without_conflicts() {
        if !git_available() {
            return;
        }
        let (_o, _w, w) = repo_with_origin();
        // feat adds a non-conflicting file.
        git(&["checkout", "-q", "-b", "feat"], &w);
        write_commit(&w, "feat.txt", "x\n", "feat");
        // main advances with a different file and is pushed.
        git(&["checkout", "-q", "main"], &w);
        write_commit(&w, "main.txt", "y\n", "main");
        git(&["push", "-q", "origin", "main"], &w);

        git(&["checkout", "-q", "feat"], &w);
        assert_eq!(
            GitRepo::new(&w).rebase_onto("main").unwrap(),
            RebaseOutcome::Clean
        );
    }

    #[test]
    fn rebase_onto_reports_then_aborts_conflicts() {
        if !git_available() {
            return;
        }
        let (_o, _w, w) = repo_with_origin();
        // feat and main both change file.txt differently → conflict on rebase.
        git(&["checkout", "-q", "-b", "feat"], &w);
        write_commit(&w, "file.txt", "feat-change\n", "feat edit");
        git(&["checkout", "-q", "main"], &w);
        write_commit(&w, "file.txt", "main-change\n", "main edit");
        git(&["push", "-q", "origin", "main"], &w);

        git(&["checkout", "-q", "feat"], &w);
        let repo = GitRepo::new(&w);
        match repo.rebase_onto("main").unwrap() {
            RebaseOutcome::Conflicts(files) => assert_eq!(files, vec!["file.txt".to_string()]),
            RebaseOutcome::Clean => panic!("expected a conflict"),
        }
        // The conflict is observable, then the rebase can be aborted cleanly.
        assert_eq!(repo.list_conflicts().unwrap(), vec!["file.txt".to_string()]);
        repo.rebase_abort().unwrap();
        assert!(repo.list_conflicts().unwrap().is_empty());
    }

    #[test]
    fn merged_branches_lists_ancestors_excluding_base() {
        if !git_available() {
            return;
        }
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path();
        git(&["init", "-q", "-b", "main"], dir);
        git(&["config", "user.email", "t@t"], dir);
        git(&["config", "user.name", "t"], dir);
        write_commit(dir, "a.txt", "a\n", "init");
        // `done` points at main's tip → merged; `wip` has an extra commit → not.
        git(&["branch", "done"], dir);
        git(&["checkout", "-q", "-b", "wip"], dir);
        write_commit(dir, "b.txt", "b\n", "wip");
        git(&["checkout", "-q", "main"], dir);

        let merged = GitRepo::new(dir).merged_branches("main").unwrap();
        assert!(merged.contains(&"done".to_string()));
        assert!(!merged.contains(&"wip".to_string()));
        assert!(!merged.contains(&"main".to_string()), "base excluded");
    }
}
