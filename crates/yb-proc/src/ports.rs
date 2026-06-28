//! Listening-TCP-port enumeration via `lsof`.
//!
//! `lsof` can block on a stuck mount, so the call is run with a hard timeout and
//! degrades to a typed error rather than hanging a collect tick. The output is
//! parsed from the stable `-F` field format. Non-unix platforms return empty.

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
    use std::io::Read;
    use std::process::{Command, Stdio};
    use std::sync::mpsc;

    // -n/-P: skip DNS/port-name lookups (faster, no hangs). -iTCP -sTCP:LISTEN:
    // only listening TCP sockets. -Fpn: machine-readable pid + name fields.
    let mut child = Command::new("lsof")
        .args(["-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(PortError::Spawn)?;

    let mut stdout = child.stdout.take().expect("stdout was piped above");
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut buf = String::new();
        let read = stdout.read_to_string(&mut buf);
        // If the receiver timed out and went away, this send just fails — fine.
        let _ = tx.send(read.map(|_| buf));
    });

    match rx.recv_timeout(timeout) {
        Ok(Ok(output)) => {
            reap(&mut child);
            Ok(parse_lsof(&output))
        }
        // Read error on the pipe: reap and report nothing rather than hang.
        Ok(Err(err)) => {
            reap(&mut child);
            Err(PortError::Spawn(err))
        }
        Err(_) => {
            // Timed out — kill the stuck lsof so it doesn't linger.
            let _ = child.kill();
            reap(&mut child);
            Err(PortError::Timeout(timeout))
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
}
