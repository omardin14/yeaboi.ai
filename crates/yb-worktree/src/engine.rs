//! The worktree engine — decentralized (discover-on-read, no central registry).
//!
//! State is derived from `git worktree list` + the deterministic port recomputed
//! from each path; nothing is cached. Create/remove run the repo's configured
//! lifecycle commands (where DB isolation lives) and render each worktree's
//! `.env` from the parent minus overridden keys.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;
use yb_exec::Cmd;
use yb_git::GitRepo;

use crate::branch::derive_branch;
use crate::config::ProjectConfig;

/// A worktree as the UI sees it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Worktree {
    /// Short name (the path leaf with the `<repo>-` prefix stripped).
    pub name: String,
    pub path: String,
    pub branch: String,
    /// Deterministic dev-server port for this checkout.
    pub port: u16,
    pub is_main: bool,
}

#[derive(Debug, Error)]
pub enum WorktreeError {
    #[error(transparent)]
    Git(#[from] yb_git::GitError),
    #[error(transparent)]
    Exec(#[from] yb_exec::ExecError),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Msg(String),
}

/// Manages the worktrees of one repository.
pub struct WorktreeEngine {
    repo_root: PathBuf,
    repo_name: String,
    /// Directory containing the repo (siblings hold the worktrees).
    parent: PathBuf,
    config: ProjectConfig,
}

impl WorktreeEngine {
    /// Build from any path inside a repo: resolve the worktree's toplevel, then
    /// the *main* repo root, and load `<root>/.yeaboi/project.toml`.
    pub fn discover(start: impl AsRef<Path>) -> Result<Self, WorktreeError> {
        let repo_root = PathBuf::from(GitRepo::new(start.as_ref()).toplevel()?);
        let repo_name = repo_root
            .file_name()
            .map(|s| s.to_string_lossy().into_owned())
            .ok_or_else(|| WorktreeError::Msg("repo path has no final component".into()))?;
        let parent = repo_root
            .parent()
            .map(Path::to_path_buf)
            .ok_or_else(|| WorktreeError::Msg("repo has no parent directory".into()))?;
        let config = ProjectConfig::load(&repo_root);
        Ok(WorktreeEngine {
            repo_root,
            repo_name,
            parent,
            config,
        })
    }

    /// Sibling path a worktree named `name` lives at: `<parent>/<repo>-<name>`.
    fn target_path(&self, name: &str) -> PathBuf {
        self.parent.join(format!("{}-{}", self.repo_name, name))
    }

    fn run_git(&self, args: &[&str]) -> Result<yb_exec::Output, WorktreeError> {
        Ok(Cmd::new("git")
            .arg("-C")
            .arg(&self.repo_root)
            .args(args.iter().copied())
            .output()?)
    }

    /// Run a git subcommand best-effort, logging (not failing) on error — for the
    /// idempotent cleanup steps (`prune`, `branch -D`).
    fn git_quiet(&self, args: &[&str]) {
        match self.run_git(args) {
            Ok(o) if !o.success => {
                eprintln!("worktree: git {} — {}", args.join(" "), o.stderr_tail())
            }
            Ok(_) => {}
            Err(e) => eprintln!("worktree: git {} — {e}", args.join(" ")),
        }
    }

    /// List worktrees, discovered fresh from `git worktree list --porcelain`.
    pub fn list(&self) -> Result<Vec<Worktree>, WorktreeError> {
        let out = self.run_git(&["worktree", "list", "--porcelain"])?;
        if !out.success {
            return Err(WorktreeError::Msg(format!(
                "git worktree list failed: {}",
                out.stderr_tail()
            )));
        }
        Ok(self.parse_porcelain(&out.stdout))
    }

    fn parse_porcelain(&self, text: &str) -> Vec<Worktree> {
        let mut worktrees = Vec::new();
        let mut path: Option<String> = None;
        let mut branch: Option<String> = None;

        for line in text.lines() {
            if let Some(p) = line.strip_prefix("worktree ") {
                self.flush(&mut path, &mut branch, &mut worktrees);
                path = Some(p.to_string());
            } else if let Some(b) = line.strip_prefix("branch ") {
                branch = Some(b.strip_prefix("refs/heads/").unwrap_or(b).to_string());
            } else if line.is_empty() {
                self.flush(&mut path, &mut branch, &mut worktrees);
            }
        }
        self.flush(&mut path, &mut branch, &mut worktrees);
        worktrees
    }

    fn flush(
        &self,
        path: &mut Option<String>,
        branch: &mut Option<String>,
        out: &mut Vec<Worktree>,
    ) {
        let Some(p) = path.take() else {
            return;
        };
        let b = branch.take().unwrap_or_else(|| "(detached)".to_string());
        let is_main = Path::new(&p) == self.repo_root;
        let leaf = Path::new(&p)
            .file_name()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_else(|| p.clone());
        let name = if is_main {
            "(main)".to_string()
        } else {
            leaf.strip_prefix(&format!("{}-", self.repo_name))
                .unwrap_or(&leaf)
                .to_string()
        };
        let port = self.config.ports.port_for(&p, is_main);
        out.push(Worktree {
            name,
            path: p,
            branch: b,
            port,
            is_main,
        });
    }

    /// Create a worktree: derive the branch, `git worktree add -b`, render `.env`,
    /// then run the configured setup commands.
    pub fn create(&self, name: &str) -> Result<Worktree, WorktreeError> {
        if name.trim().is_empty() {
            return Err(WorktreeError::Msg("worktree name is empty".into()));
        }
        let branch = derive_branch(name, &self.config.branch_rules);
        let target = self.target_path(name);
        if target.exists() {
            return Err(WorktreeError::Msg(format!(
                "{} already exists",
                target.display()
            )));
        }

        let out = Cmd::new("git")
            .arg("-C")
            .arg(&self.repo_root)
            .args(["worktree", "add"])
            .arg(&target)
            .args(["-b", &branch])
            .output()?;
        if !out.success {
            return Err(WorktreeError::Msg(format!(
                "git worktree add failed: {}",
                out.stderr_tail()
            )));
        }

        let port = self.config.ports.port_for(&target.to_string_lossy(), false);
        self.render_env(&target, port)?;
        self.run_commands(&target, &self.config.lifecycle.setup)?;

        Ok(Worktree {
            name: name.to_string(),
            path: target.to_string_lossy().into_owned(),
            branch,
            port,
            is_main: false,
        })
    }

    /// Render `<worktree>/.env`: parent `.env` minus overridden keys, then `PORT`
    /// and the configured `[env]` overrides.
    fn render_env(&self, target: &Path, port: u16) -> Result<(), WorktreeError> {
        let overridden: HashSet<&str> = std::iter::once("PORT")
            .chain(self.config.env.keys().map(String::as_str))
            .collect();

        let mut lines = Vec::new();
        if let Ok(text) = std::fs::read_to_string(self.repo_root.join(".env")) {
            for line in text.lines() {
                let key = line.split('=').next().unwrap_or("").trim();
                if !overridden.contains(key) {
                    lines.push(line.to_string());
                }
            }
        }
        lines.push(format!("PORT={port}"));
        for (k, v) in &self.config.env {
            lines.push(format!("{k}={v}"));
        }
        std::fs::write(target.join(".env"), format!("{}\n", lines.join("\n")))?;
        Ok(())
    }

    /// Run shell commands in `dir`, stopping on the first failure.
    fn run_commands(&self, dir: &Path, cmds: &[String]) -> Result<(), WorktreeError> {
        for cmd in cmds {
            let out = Cmd::new("sh").arg("-c").arg(cmd).cwd(dir).output()?;
            if !out.success {
                return Err(WorktreeError::Msg(format!(
                    "command `{cmd}` failed: {}",
                    out.stderr_tail()
                )));
            }
        }
        Ok(())
    }

    /// Remove a worktree: teardown (best-effort) → forced removal → prune →
    /// delete the branch. Idempotent, like the reference `w.sh rm`.
    pub fn remove(&self, name: &str) -> Result<(), WorktreeError> {
        let target = self.target_path(name);
        let branch = derive_branch(name, &self.config.branch_rules);

        if let Err(e) = self.run_commands(&target, &self.config.lifecycle.teardown) {
            eprintln!("worktree: teardown for {name} failed (continuing): {e}");
        }

        let removed = Cmd::new("git")
            .arg("-C")
            .arg(&self.repo_root)
            .args(["worktree", "remove", "--force"])
            .arg(&target)
            .output()?;
        if !removed.success {
            eprintln!("worktree: git worktree remove — {}", removed.stderr_tail());
        }
        if target.exists() {
            std::fs::remove_dir_all(&target)?;
        }
        self.git_quiet(&["worktree", "prune"]);
        self.git_quiet(&["branch", "-D", &branch]);
        Ok(())
    }

    /// Remove every worktree whose branch is already merged into the default
    /// branch; returns the names removed.
    pub fn prune_merged(&self) -> Result<Vec<String>, WorktreeError> {
        let base = GitRepo::new(&self.repo_root).default_base()?;
        let merged: HashSet<String> = GitRepo::new(&self.repo_root)
            .merged_branches(&base)?
            .into_iter()
            .collect();

        let mut removed = Vec::new();
        for wt in self.list()? {
            if !wt.is_main && merged.contains(&wt.branch) {
                self.remove(&wt.name)?;
                removed.push(wt.name);
            }
        }
        Ok(removed)
    }

    /// Start the repo's configured services in a worktree (detached, pid-filed).
    #[cfg(unix)]
    pub fn start_services(&self, name: &str) -> Result<(), WorktreeError> {
        let dir = self.target_path(name);
        let svc_dir = dir.join(".yeaboi");
        std::fs::create_dir_all(&svc_dir)?;
        for svc in &self.config.services {
            let log = svc_dir.join(format!("{}.log", svc.name));
            let pid_file = svc_dir.join(format!("{}.pid", svc.name));
            Cmd::new("sh")
                .arg("-c")
                .arg(&svc.cmd)
                .cwd(&dir)
                .spawn_detached(&log, &pid_file)?;
        }
        Ok(())
    }

    #[cfg(not(unix))]
    pub fn start_services(&self, _name: &str) -> Result<(), WorktreeError> {
        Err(WorktreeError::Msg(
            "services are only supported on unix".into(),
        ))
    }

    /// Stop a worktree's services by SIGTERM-ing their pids and clearing the
    /// pid files.
    pub fn stop_services(&self, name: &str) -> Result<(), WorktreeError> {
        let svc_dir = self.target_path(name).join(".yeaboi");
        for svc in &self.config.services {
            let pid_file = svc_dir.join(format!("{}.pid", svc.name));
            let Ok(text) = std::fs::read_to_string(&pid_file) else {
                continue;
            };
            if let Ok(pid) = text.trim().parse::<u32>()
                && let Err(e) = yb_proc::actions::sigterm(pid)
            {
                eprintln!("worktree: stop {} (pid {pid}): {e}", svc.name);
            }
            if let Err(e) = std::fs::remove_file(&pid_file) {
                eprintln!("worktree: could not clear {}: {e}", pid_file.display());
            }
        }
        Ok(())
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
        assert!(out.success, "git {args:?}: {}", out.stderr_tail());
    }

    /// A repo named `proj` under a temp parent, on `main` with one commit.
    fn repo() -> (tempfile::TempDir, PathBuf) {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("proj");
        std::fs::create_dir_all(&root).unwrap();
        git(&["init", "-q", "-b", "main"], &root);
        git(&["config", "user.email", "t@t"], &root);
        git(&["config", "user.name", "t"], &root);
        std::fs::write(root.join(".env"), "API_KEY=keep\nPORT=9999\n").unwrap();
        git(&["add", "."], &root);
        git(&["commit", "-q", "-m", "init"], &root);
        (tmp, root)
    }

    #[test]
    fn list_includes_the_main_checkout() {
        let (_tmp, root) = repo();
        let eng = WorktreeEngine::discover(&root).unwrap();
        let wts = eng.list().unwrap();
        assert_eq!(wts.len(), 1);
        assert!(wts[0].is_main);
        assert_eq!(wts[0].port, 4000);
        assert_eq!(wts[0].branch, "main");
    }

    #[test]
    fn create_then_list_then_remove() {
        let (_tmp, root) = repo();
        let eng = WorktreeEngine::discover(&root).unwrap();

        let wt = eng.create("feat-x").unwrap();
        assert_eq!(wt.name, "feat-x");
        assert_eq!(wt.branch, "feat-x");
        assert!((4100..4200).contains(&wt.port));
        assert!(Path::new(&wt.path).join(".env").exists());

        // .env: parent key kept, PORT overridden to the worktree port.
        let env = std::fs::read_to_string(Path::new(&wt.path).join(".env")).unwrap();
        assert!(env.contains("API_KEY=keep"));
        assert!(env.contains(&format!("PORT={}", wt.port)));
        assert!(!env.contains("PORT=9999"));

        let listed = eng.list().unwrap();
        assert_eq!(listed.len(), 2);
        assert!(listed.iter().any(|w| w.name == "feat-x" && !w.is_main));

        eng.remove("feat-x").unwrap();
        assert!(!Path::new(&wt.path).exists());
        assert_eq!(eng.list().unwrap().len(), 1);
    }

    #[test]
    fn branch_rules_apply_on_create() {
        let (_tmp, root) = repo();
        std::fs::create_dir_all(root.join(".yeaboi")).unwrap();
        std::fs::write(
            root.join(".yeaboi").join("project.toml"),
            "[[branch_rules]]\npattern = \"^issue-(\\\\d+)$\"\ntemplate = \"feature/issue-$1\"\n",
        )
        .unwrap();
        let eng = WorktreeEngine::discover(&root).unwrap();
        let wt = eng.create("issue-42").unwrap();
        assert_eq!(wt.branch, "feature/issue-42");
        eng.remove("issue-42").unwrap();
    }
}
