//! Listening-TCP-port enumeration via `lsof`.
//!
//! `lsof` can block on a stuck mount, so the call is run with a hard timeout and
//! degrades to a typed error rather than hanging a collect tick. The output is
//! parsed from the stable `-F` field format. Non-unix platforms return
//! [`PortError::Unsupported`].

use std::time::Duration;

use thiserror::Error;
use yb_core::Port;

/// Default ceiling on how long we'll wait for `lsof` before giving up.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_millis(750);

/// Why a port enumeration failed (the caller degrades to a warning).
#[derive(Debug, Error)]
pub enum PortError {
    #[error("lsof did not finish within {0:?}")]
    Timeout(Duration),
    #[error("could not run lsof: {0}")]
    Spawn(#[source] std::io::Error),
    #[error("port enumeration is not supported on this platform")]
    Unsupported,
}

/// List listening TCP ports (with the pid holding each socket), with the default
/// timeout.
pub fn list() -> Result<Vec<Port>, PortError> {
    list_with_timeout(DEFAULT_TIMEOUT)
}

#[cfg(unix)]
pub fn list_with_timeout(timeout: Duration) -> Result<Vec<Port>, PortError> {
    // -n/-P: skip DNS/port-name lookups (faster, no hangs). -iTCP -sTCP:LISTEN:
    // only listening TCP sockets. -Fpn: machine-readable pid + name fields.
    list_from_command("lsof", &["-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"], timeout)
}

/// Run `program args`, reading its stdout on a worker thread so the read can be
/// abandoned on timeout. Factored out so tests can drive the timeout/spawn arms
/// with a fake subprocess.
#[cfg(unix)]
fn list_from_command(
    program: &str,
    args: &[&str],
    timeout: Duration,
) -> Result<Vec<Port>, PortError> {
    use std::io::Read;
    use std::process::{Command, Stdio};
    use std::sync::mpsc::{self, RecvTimeoutError};

    let mut child = Command::new(program)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(PortError::Spawn)?;

    let mut stdout = child.stdout.take().expect("stdout was piped above");
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut buf = String::new();
        let read_result = stdout.read_to_string(&mut buf);
        // The receiver may have timed out and gone away; a failed send just
        // means nobody's listening, which is the expected race, not an error.
        if tx.send(read_result.map(|_| buf)).is_err() {
            // nothing to do — the timeout arm already handled the child
        }
    });

    match rx.recv_timeout(timeout) {
        Ok(Ok(output)) => {
            reap(&mut child);
            Ok(parse_lsof(&output))
        }
        // The pipe read failed: reap and surface it (don't hang).
        Ok(Err(err)) => {
            reap(&mut child);
            Err(PortError::Spawn(err))
        }
        Err(RecvTimeoutError::Timeout) => {
            // Stuck child — kill it so it doesn't linger, then surface the timeout.
            if let Err(e) = child.kill() {
                eprintln!("lsof kill failed: {e}");
            }
            reap(&mut child);
            Err(PortError::Timeout(timeout))
        }
        // The reader thread dropped its sender without sending (e.g. it
        // panicked). Report a read failure, not a misleading "timed out".
        Err(RecvTimeoutError::Disconnected) => {
            reap(&mut child);
            Err(PortError::Spawn(std::io::Error::other(
                "lsof reader thread ended unexpectedly",
            )))
        }
    }
}

#[cfg(not(unix))]
pub fn list_with_timeout(_timeout: Duration) -> Result<Vec<Port>, PortError> {
    Err(PortError::Unsupported)
}

/// Best-effort reap so a finished `lsof` doesn't become a zombie.
#[cfg(unix)]
fn reap(child: &mut std::process::Child) {
    if let Err(err) = child.wait() {
        eprintln!("lsof reap failed: {err}");
    }
}

/// Parse `lsof -Fpn` output. Lines are field-prefixed: `p<pid>` opens a process
/// block; subsequent `n<host:port>` lines are that pid's listening sockets.
fn parse_lsof(output: &str) -> Vec<Port> {
    let mut ports = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut current_pid: Option<u32> = None;

    for line in output.lines() {
        let Some((tag, rest)) = line.split_at_checked(1) else {
            continue;
        };
        match tag {
            // A malformed pid is an intentional best-effort skip: the rest of
            // this process block gets dropped. lsof is stable under our flags,
            // so this shouldn't happen in practice.
            "p" => current_pid = rest.trim().parse().ok(),
            "n" => {
                if let (Some(pid), Some(number)) = (current_pid, port_from_name(rest)) {
                    // lsof lists IPv4 + IPv6 rows for the same socket; dedupe.
                    if seen.insert((pid, number)) {
                        ports.push(Port {
                            number,
                            pid,
                            state: "LISTEN".to_string(),
                        });
                    }
                }
            }
            _ => {}
        }
    }
    ports
}

/// Extract the port from an lsof name field: `*:1420`, `127.0.0.1:3000`,
/// `[::1]:5173`, possibly with a trailing ` (LISTEN)`.
fn port_from_name(name: &str) -> Option<u16> {
    let name = name.split_whitespace().next().unwrap_or(name);
    let after_colon = name.rsplit(':').next()?;
    after_colon.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_pid_grouped_listeners() {
        let sample = "\
p123
n*:1420
n127.0.0.1:3000
p456
n[::1]:5173
n*:5173
";
        let mut ports = parse_lsof(sample);
        ports.sort_by_key(|p| (p.pid, p.number));

        assert_eq!(ports.len(), 3, "IPv4+IPv6 duplicate of 5173 deduped");
        assert_eq!((ports[0].pid, ports[0].number), (123, 1420));
        assert_eq!((ports[1].pid, ports[1].number), (123, 3000));
        assert_eq!((ports[2].pid, ports[2].number), (456, 5173));
        assert!(ports.iter().all(|p| p.state == "LISTEN"));
    }

    #[test]
    fn port_from_name_variants() {
        assert_eq!(port_from_name("*:1420"), Some(1420));
        assert_eq!(port_from_name("127.0.0.1:3000"), Some(3000));
        assert_eq!(port_from_name("[::1]:5173"), Some(5173));
        assert_eq!(port_from_name("*:8080 (LISTEN)"), Some(8080));
        assert_eq!(port_from_name("garbage"), None);
    }

    #[test]
    fn ignores_lines_without_a_current_pid() {
        // An `n` line before any `p` line is dropped, not attributed to pid 0.
        assert!(parse_lsof("n*:1420\n").is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn times_out_on_a_slow_command() {
        // A fake "lsof" that never finishes must hit the timeout arm (and the
        // child-kill path), not hang.
        let r = list_from_command("sleep", &["5"], Duration::from_millis(80));
        assert!(matches!(r, Err(PortError::Timeout(_))), "got {r:?}");
    }

    #[cfg(unix)]
    #[test]
    fn spawn_failure_is_surfaced() {
        let r = list_from_command("yb-no-such-binary-xyz", &[], Duration::from_millis(500));
        assert!(matches!(r, Err(PortError::Spawn(_))), "got {r:?}");
    }
}
