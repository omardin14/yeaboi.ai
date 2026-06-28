//! Process actions — the only *write* path in yb-proc.
//!
//! Currently just `SIGTERM` (a polite stop), guarded against signalling the
//! kernel/init pids. Higher layers re-validate that the pid is a session we
//! actually track before calling in.

use thiserror::Error;

/// Why a kill request was refused or failed.
#[derive(Debug, Error)]
pub enum KillError {
    /// Refused to signal pid 0 or 1 (kernel / init).
    #[error("refusing to signal protected pid {0}")]
    Protected(u32),
    /// The OS rejected the signal (e.g. no such process, or not permitted).
    #[error("failed to signal pid {pid}: {source}")]
    Signal {
        pid: u32,
        #[source]
        source: std::io::Error,
    },
    /// Signalling isn't implemented for this platform yet.
    #[error("process signalling is not supported on this platform")]
    Unsupported,
}

/// Send `SIGTERM` to `pid`. Refuses pid ≤ 1 and any value that wouldn't survive
/// the `i32` round-trip — `kill(-1, …)` would signal the whole process group, so
/// an out-of-range pid must never reach the syscall.
#[cfg(unix)]
pub fn sigterm(pid: u32) -> Result<(), KillError> {
    use nix::sys::signal::{Signal, kill};
    use nix::unistd::Pid;

    if pid <= 1 || pid > i32::MAX as u32 {
        return Err(KillError::Protected(pid));
    }
    kill(Pid::from_raw(pid as i32), Signal::SIGTERM).map_err(|errno| KillError::Signal {
        pid,
        source: errno.into(),
    })
}

/// Non-unix fallback so the API exists everywhere (Windows support is a later
/// platform pass).
#[cfg(not(unix))]
pub fn sigterm(_pid: u32) -> Result<(), KillError> {
    Err(KillError::Unsupported)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn rejects_protected_pids() {
        assert!(matches!(sigterm(1), Err(KillError::Protected(1))));
        assert!(matches!(sigterm(0), Err(KillError::Protected(0))));
    }

    #[test]
    fn rejects_pids_that_overflow_i32() {
        // Would wrap negative and signal the whole process group via kill(-1, …).
        let huge = i32::MAX as u32 + 1;
        assert!(matches!(sigterm(huge), Err(KillError::Protected(p)) if p == huge));
        assert!(matches!(sigterm(u32::MAX), Err(KillError::Protected(_))));
    }

    #[test]
    fn sigterm_terminates_a_child() {
        // A long sleep we then SIGTERM; it must exit, not by a clean exit code.
        let mut child = std::process::Command::new("sleep")
            .arg("30")
            .spawn()
            .expect("spawn sleep");
        sigterm(child.id()).expect("sigterm");
        let status = child.wait().expect("wait");
        assert!(
            !status.success(),
            "child should have been terminated by the signal"
        );
    }

    #[test]
    fn signalling_a_dead_pid_errors() {
        // Spawn + reap a child, then signal its (now-free) pid.
        let mut child = std::process::Command::new("true").spawn().expect("spawn");
        let pid = child.id();
        child.wait().expect("wait");
        // No such process → ESRCH, surfaced as a Signal error (not a panic).
        match sigterm(pid) {
            Err(KillError::Signal { source, .. }) => {
                assert_eq!(source.raw_os_error(), Some(nix::libc::ESRCH));
            }
            other => panic!("expected an ESRCH Signal error, got {other:?}"),
        }
    }
}
