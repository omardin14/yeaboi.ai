//! Typed external-command runner — the foundation under `yb-git`/`yb-agent`.
//!
//! Phase 1c ships the blocking [`Cmd::output`] form (run, wait, capture). The
//! streaming (`stream(tx, cancel)`) and detached (`spawn_detached`) forms land
//! when the review orchestrator and per-worktree services need them.

use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

use thiserror::Error;

/// Failure to *launch* a command (vs. the command running and failing, which is
/// a successful [`Output`] with `success == false`).
#[derive(Debug, Error)]
pub enum ExecError {
    #[error("failed to spawn `{program}`: {source}")]
    Spawn {
        program: String,
        #[source]
        source: std::io::Error,
    },
}

/// The captured result of a finished command. `stdout`/`stderr` are decoded
/// lossily (subprocess output is text in our uses; never panic on odd bytes).
#[derive(Debug, Clone)]
pub struct Output {
    /// Exit code, or `None` if the process was terminated by a signal.
    pub status: Option<i32>,
    /// Whether the process exited 0.
    pub success: bool,
    pub stdout: String,
    pub stderr: String,
}

impl Output {
    /// stderr with surrounding whitespace trimmed — handy for error messages.
    pub fn stderr_tail(&self) -> &str {
        self.stderr.trim()
    }
}

/// A command to run: program + args + optional working directory.
#[derive(Debug, Clone)]
pub struct Cmd {
    program: OsString,
    args: Vec<OsString>,
    cwd: Option<PathBuf>,
}

impl Cmd {
    pub fn new(program: impl AsRef<OsStr>) -> Self {
        Cmd {
            program: program.as_ref().to_os_string(),
            args: Vec::new(),
            cwd: None,
        }
    }

    pub fn arg(mut self, arg: impl AsRef<OsStr>) -> Self {
        self.args.push(arg.as_ref().to_os_string());
        self
    }

    pub fn args<I, S>(mut self, args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: AsRef<OsStr>,
    {
        self.args
            .extend(args.into_iter().map(|a| a.as_ref().to_os_string()));
        self
    }

    pub fn cwd(mut self, dir: impl AsRef<Path>) -> Self {
        self.cwd = Some(dir.as_ref().to_path_buf());
        self
    }

    /// Run to completion, capturing stdout/stderr. Errors only if the process
    /// can't be launched; a non-zero exit is a successful call with
    /// `Output::success == false`.
    pub fn output(&self) -> Result<Output, ExecError> {
        let mut command = std::process::Command::new(&self.program);
        command.args(&self.args);
        if let Some(dir) = &self.cwd {
            command.current_dir(dir);
        }

        let out = command.output().map_err(|source| ExecError::Spawn {
            program: self.program.to_string_lossy().into_owned(),
            source,
        })?;

        Ok(Output {
            status: out.status.code(),
            success: out.status.success(),
            stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captures_stdout_of_a_successful_command() {
        let out = Cmd::new("echo").arg("hello").output().expect("run echo");
        assert!(out.success);
        assert_eq!(out.status, Some(0));
        assert_eq!(out.stdout.trim(), "hello");
    }

    #[test]
    fn nonzero_exit_is_a_successful_call_with_success_false() {
        // `sh -c '…; exit 3'` runs fine but exits 3 and writes to stderr.
        let out = Cmd::new("sh")
            .args(["-c", "echo oops >&2; exit 3"])
            .output()
            .expect("run sh");
        assert!(!out.success);
        assert_eq!(out.status, Some(3));
        assert_eq!(out.stderr_tail(), "oops");
    }

    #[test]
    fn spawn_failure_is_an_exec_error() {
        let err = Cmd::new("yb-no-such-binary-xyz").output().unwrap_err();
        assert!(matches!(err, ExecError::Spawn { .. }));
    }

    #[test]
    fn cwd_is_respected() {
        // `/` is a stable, symlink-free directory on every unix.
        let out = Cmd::new("pwd").cwd("/").output().expect("run pwd");
        assert_eq!(out.stdout.trim(), "/");
    }
}
