//! Group sessions by repository using only the filesystem — no `git`
//! subprocess (keeps `yb-core` free of process spawning).
//!
//! From a session's `cwd` we walk up to the `.git` entry. A worktree's `.git`
//! is a *file* (`gitdir: …/.git/worktrees/<name>`); resolving it to the shared
//! **common dir** is what makes every worktree of a repo roll up under one
//! [`Project`]. The `origin` remote (read from the common dir's `config`) names
//! the project; non-git dirs fall back to the cwd itself.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// The repo identity a `cwd` resolves to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedProject {
    /// Stable id shared by all worktrees of the repo (the repo root path).
    pub id: String,
    /// Display name (remote slug, else the root folder name).
    pub name: String,
    /// Repo root (main checkout), or the cwd for non-git dirs.
    pub root: String,
    /// `origin` remote URL, when present.
    pub remote: Option<String>,
}

/// Resolves `cwd → ResolvedProject`, caching by cwd so a tick with many
/// sessions in the same repo only touches the filesystem once.
#[derive(Debug, Default)]
pub struct ProjectResolver {
    cache: HashMap<String, ResolvedProject>,
}

impl ProjectResolver {
    pub fn new() -> Self {
        Self::default()
    }

    /// Resolve `cwd`, consulting (and populating) the cache.
    pub fn resolve(&mut self, cwd: &str) -> ResolvedProject {
        if let Some(hit) = self.cache.get(cwd) {
            return hit.clone();
        }
        let resolved = resolve_uncached(Path::new(cwd));
        self.cache.insert(cwd.to_string(), resolved.clone());
        resolved
    }
}

/// Walk up from `start` to the first `.git`, resolving worktrees to the common
/// dir. Falls back to the cwd as its own project when nothing git-like is found.
fn resolve_uncached(start: &Path) -> ResolvedProject {
    let mut dir = Some(start);
    while let Some(d) = dir {
        let dot_git = d.join(".git");
        if dot_git.is_dir() {
            return project_from_root(d, &dot_git);
        }
        if dot_git.is_file()
            && let Some((root, common)) = worktree_root(d, &dot_git)
        {
            return project_from_root(&root, &common);
        }
        dir = d.parent();
    }
    fallback(start)
}

/// Resolve a worktree's `.git` file to `(repo_root, common_dir)`.
///
/// The file holds `gitdir: <main>/.git/worktrees/<name>`; the common dir is two
/// levels up (`<main>/.git`) and the repo root is its parent (`<main>`).
fn worktree_root(worktree_dir: &Path, dot_git_file: &Path) -> Option<(PathBuf, PathBuf)> {
    let contents = std::fs::read_to_string(dot_git_file).ok()?;
    let gitdir = contents
        .lines()
        .find_map(|l| l.strip_prefix("gitdir:"))?
        .trim();

    let gitdir_path = {
        let p = Path::new(gitdir);
        if p.is_absolute() {
            p.to_path_buf()
        } else {
            worktree_dir.join(p)
        }
    };

    // <main>/.git/worktrees/<name> → common = <main>/.git, root = <main>
    let common = gitdir_path.parent()?.parent()?.to_path_buf();
    let root = common.parent()?.to_path_buf();
    Some((root, common))
}

/// Build a [`ResolvedProject`] from a repo root and its git common dir.
fn project_from_root(root: &Path, common_dir: &Path) -> ResolvedProject {
    let remote = read_origin_remote(&common_dir.join("config"));
    let name = remote
        .as_deref()
        .and_then(remote_slug)
        .unwrap_or_else(|| dir_name(root));
    ResolvedProject {
        id: root.to_string_lossy().into_owned(),
        name,
        root: root.to_string_lossy().into_owned(),
        remote,
    }
}

/// A non-git cwd is its own single-session project.
fn fallback(cwd: &Path) -> ResolvedProject {
    ResolvedProject {
        id: cwd.to_string_lossy().into_owned(),
        name: dir_name(cwd),
        root: cwd.to_string_lossy().into_owned(),
        remote: None,
    }
}

/// Parse the `url` under `[remote "origin"]` from a git config file (best
/// effort; returns `None` if the file or section is absent).
fn read_origin_remote(config_path: &Path) -> Option<String> {
    let contents = std::fs::read_to_string(config_path).ok()?;
    let mut in_origin = false;
    for line in contents.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_origin = line == "[remote \"origin\"]";
            continue;
        }
        if in_origin
            && let Some(url) = line.strip_prefix("url")
            && let Some((_, value)) = url.split_once('=')
        {
            // `url = git@github.com:owner/repo.git`
            return Some(value.trim().to_string());
        }
    }
    None
}

/// `git@github.com:owner/repo.git` / `https://github.com/owner/repo` → `repo`.
fn remote_slug(remote: &str) -> Option<String> {
    let trimmed = remote.trim_end_matches('/');
    let last = trimmed.rsplit(['/', ':']).next()?;
    let name = last.strip_suffix(".git").unwrap_or(last);
    if name.is_empty() {
        None
    } else {
        Some(name.to_string())
    }
}

fn dir_name(path: &Path) -> String {
    path.file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn remote_slug_variants() {
        assert_eq!(
            remote_slug("git@github.com:omardin14/yeaboi.ai.git").as_deref(),
            Some("yeaboi.ai")
        );
        assert_eq!(
            remote_slug("https://github.com/owner/repo").as_deref(),
            Some("repo")
        );
    }

    #[test]
    fn main_checkout_resolves_with_remote_name() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("yeaboi");
        let git = root.join(".git");
        fs::create_dir_all(&git).unwrap();
        fs::write(
            git.join("config"),
            "[core]\n\trepositoryformatversion = 0\n[remote \"origin\"]\n\turl = git@github.com:omardin14/yeaboi.ai.git\n",
        )
        .unwrap();

        let mut r = ProjectResolver::new();
        let p = r.resolve(&root.to_string_lossy());
        assert_eq!(p.name, "yeaboi.ai");
        assert_eq!(p.root, root.to_string_lossy());
        assert_eq!(
            p.remote.as_deref(),
            Some("git@github.com:omardin14/yeaboi.ai.git")
        );
    }

    #[test]
    fn worktree_rolls_up_under_main_repo() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("yeaboi");
        let git = root.join(".git");
        fs::create_dir_all(git.join("worktrees").join("feat")).unwrap();
        fs::write(
            git.join("config"),
            "[remote \"origin\"]\n\turl = git@github.com:o/yeaboi.ai.git\n",
        )
        .unwrap();

        // Worktree checkout with a `.git` *file* pointing at the common dir.
        let wt = tmp.path().join("yeaboi-feat");
        fs::create_dir_all(&wt).unwrap();
        fs::write(
            wt.join(".git"),
            format!("gitdir: {}\n", git.join("worktrees").join("feat").display()),
        )
        .unwrap();

        let mut r = ProjectResolver::new();
        let main = r.resolve(&root.to_string_lossy());
        let worktree = r.resolve(&wt.to_string_lossy());
        // Both must resolve to the SAME project id (the main repo root).
        assert_eq!(main.id, worktree.id);
        assert_eq!(worktree.name, "yeaboi.ai");
    }

    #[test]
    fn nested_subdir_walks_up_to_repo_root() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("repo");
        fs::create_dir_all(root.join(".git")).unwrap();
        let deep = root.join("crates").join("yb-core").join("src");
        fs::create_dir_all(&deep).unwrap();

        let mut r = ProjectResolver::new();
        let p = r.resolve(&deep.to_string_lossy());
        assert_eq!(p.root, root.to_string_lossy());
        assert_eq!(p.name, "repo");
    }

    #[test]
    fn non_git_dir_is_its_own_project() {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("scratch");
        fs::create_dir_all(&dir).unwrap();

        let mut r = ProjectResolver::new();
        let p = r.resolve(&dir.to_string_lossy());
        assert_eq!(p.id, dir.to_string_lossy());
        assert_eq!(p.name, "scratch");
        assert!(p.remote.is_none());
    }
}
