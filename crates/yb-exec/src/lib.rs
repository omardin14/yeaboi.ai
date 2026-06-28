//! Typed external-command runner — the foundation under `yb-git`/`yb-agent`.
//!
//! Three forms: blocking [`Cmd::output`] (run, wait, capture), [`Cmd::stream`]
//! (cancelable line-by-line) for agent output, and [`Cmd::spawn_detached`]
//! (new process group + pid file) for long-lived per-worktree services.

use std::ffi::{OsStr, OsString};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};

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
    #[error("io error running `{program}`: {source}")]
    Io {
        program: String,
        #[source]
        source: std::io::Error,
    },
}

/// The result of a [`Cmd::stream`] run.
#[derive(Debug, Clone)]
pub struct StreamResult {
    /// Exit code, or `None` if signalled (incl. our own cancel-kill).
    pub status: Option<i32>,
    /// Whether the process exited 0.
    pub success: bool,
    /// Whether we cancelled it.
    pub canceled: bool,
    /// Captured stderr (so a non-zero exit's reason isn't lost).
    pub stderr: String,
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
        let out = self
            .std_command()
            .output()
            .map_err(|source| ExecError::Spawn {
                program: self.program_name(),
                source,
            })?;

        Ok(Output {
            status: out.status.code(),
            success: out.status.success(),
            stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
        })
    }

    fn std_command(&self) -> std::process::Command {
        let mut command = std::process::Command::new(&self.program);
        command.args(&self.args);
        if let Some(dir) = &self.cwd {
            command.current_dir(dir);
        }
        command
    }

    fn program_name(&self) -> String {
        self.program.to_string_lossy().into_owned()
    }

    /// Run, invoking `on_line` for each stdout line as it arrives. `cancel` is
    /// checked continuously on a background reader, so setting it kills the child
    /// promptly even mid-silence (cooperative cancellation). stderr is discarded;
    /// use [`Cmd::output`] when you need it.
    pub fn stream(
        &self,
        cancel: &AtomicBool,
        mut on_line: impl FnMut(&str),
    ) -> Result<StreamResult, ExecError> {
        use std::process::Stdio;
        use std::sync::mpsc::{self, RecvTimeoutError};
        use std::time::Duration;

        let mut child = self
            .std_command()
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|source| ExecError::Spawn {
                program: self.program_name(),
                source,
            })?;

        let stdout = child.stdout.take().expect("stdout was piped above");
        let stderr = child.stderr.take().expect("stderr was piped above");
        let program = self.program_name();

        // Drain stderr on its own thread so it can't deadlock the stdout reader.
        let stderr_program = program.clone();
        let stderr_reader = std::thread::spawn(move || {
            use std::io::Read;
            let mut buf = String::new();
            if let Err(e) = BufReader::new(stderr).read_to_string(&mut buf) {
                eprintln!("stream: stderr read error on `{stderr_program}`: {e}");
            }
            buf
        });

        let (tx, rx) = mpsc::channel();
        let reader = std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                match line {
                    // Receiver gone (we cancelled) → stop reading.
                    Ok(l) => {
                        if tx.send(l).is_err() {
                            break;
                        }
                    }
                    // A real read error (not clean EOF) shouldn't vanish silently.
                    Err(e) => {
                        eprintln!("stream: read error on `{program}`: {e}");
                        break;
                    }
                }
            }
        });

        let mut canceled = false;
        loop {
            if cancel.load(Ordering::Relaxed) {
                canceled = true;
                if let Err(e) = child.kill() {
                    eprintln!("stream: failed to kill `{}`: {e}", self.program_name());
                }
                break;
            }
            match rx.recv_timeout(Duration::from_millis(100)) {
                Ok(line) => on_line(&line),
                Err(RecvTimeoutError::Timeout) => continue,
                // Reader finished — the process closed stdout (it's exiting).
                Err(RecvTimeoutError::Disconnected) => break,
            }
        }

        let status = child.wait().map_err(|source| ExecError::Io {
            program: self.program_name(),
            source,
        })?;
        if let Err(e) = reader.join() {
            eprintln!("stream: reader thread panicked: {e:?}");
        }
        let stderr = stderr_reader.join().unwrap_or_default();

        Ok(StreamResult {
            status: status.code(),
            success: status.success(),
            canceled,
            stderr,
        })
    }

    /// Spawn a long-lived process detached from us: a new process group (so it
    /// outlives the app and isn't killed by our signals), stdout+stderr to
    /// `log`, and its pid written to `pid_file`. Returns the child pid.
    #[cfg(unix)]
    pub fn spawn_detached(&self, log: &Path, pid_file: &Path) -> Result<u32, ExecError> {
        use std::os::unix::process::CommandExt;

        let io_err = |source| ExecError::Io {
            program: self.program_name(),
            source,
        };

        let log_file = std::fs::File::create(log).map_err(io_err)?;
        let log_err = log_file.try_clone().map_err(io_err)?;

        let mut child = self
            .std_command()
            .stdout(log_file)
            .stderr(log_err)
            .process_group(0) // detach into a new group
            .spawn()
            .map_err(|source| ExecError::Spawn {
                program: self.program_name(),
                source,
            })?;

        let pid = child.id();
        // If we can't record the pid we'd leak an untracked process — kill it
        // (best-effort) before surfacing the error.
        if let Err(source) = std::fs::write(pid_file, pid.to_string()) {
            if let Err(e) = child.kill() {
                eprintln!("spawn_detached: failed to kill orphaned child {pid}: {e}");
            }
            return Err(io_err(source));
        }
        Ok(pid)
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

    #[test]
    fn stream_delivers_lines_in_order() {
        let cancel = AtomicBool::new(false);
        let mut lines = Vec::new();
        let res = Cmd::new("sh")
            .args(["-c", "echo a; echo b; echo c"])
            .stream(&cancel, |l| lines.push(l.to_string()))
            .expect("stream");
        assert_eq!(lines, ["a", "b", "c"]);
        assert!(res.success);
        assert!(!res.canceled);
    }

    #[test]
    fn stream_captures_stderr_separately_from_stdout() {
        let cancel = AtomicBool::new(false);
        let mut lines = Vec::new();
        let res = Cmd::new("sh")
            .args(["-c", "echo out; echo boom >&2"])
            .stream(&cancel, |l| lines.push(l.to_string()))
            .expect("stream");
        assert_eq!(lines, ["out"]);
        assert_eq!(res.stderr.trim(), "boom");
    }

    #[test]
    fn stream_cancel_interrupts_a_hanging_child() {
        // Emits one line, then sleeps far longer than the test should take.
        let cancel = AtomicBool::new(false);
        let res = Cmd::new("sh")
            .args(["-c", "echo go; sleep 30"])
            .stream(&cancel, |_| cancel.store(true, Ordering::Relaxed))
            .expect("stream");
        // The cancel (set on the first line) must kill the child promptly.
        assert!(res.canceled);
        assert!(!res.success);
    }

    #[cfg(unix)]
    #[test]
    fn spawn_detached_writes_pid_and_log() {
        let tmp = std::env::temp_dir().join(format!("yb-detach-{}", std::process::id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let log = tmp.join("out.log");
        let pid_file = tmp.join("pid");

        let pid = Cmd::new("sh")
            .args(["-c", "echo hi"])
            .spawn_detached(&log, &pid_file)
            .expect("spawn_detached");
        assert!(pid > 1);
        assert_eq!(std::fs::read_to_string(&pid_file).unwrap(), pid.to_string());

        // Poll the log (rather than a fixed sleep) until the child flushes "hi".
        let mut logged = false;
        for _ in 0..50 {
            if std::fs::read_to_string(&log)
                .unwrap_or_default()
                .contains("hi")
            {
                logged = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        assert!(logged, "detached child's output never reached the log");
        std::fs::remove_dir_all(&tmp).ok();
    }
}
