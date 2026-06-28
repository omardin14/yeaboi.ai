//! Filesystem-change watcher used to wake the collector early instead of
//! always sleeping a full tick. OS introspection (per-platform fsevents /
//! inotify / kqueue via `notify`), so it lives in `yb-proc`, not `yb-core`.
//!
//! Purely an optimization: if watching fails, the caller falls back to its
//! timeout and keeps polling.

use std::path::Path;
use std::sync::mpsc::{Receiver, RecvTimeoutError, channel};
use std::time::Duration;

use notify::{RecommendedWatcher, RecursiveMode, Watcher};

/// Signals when any watched path changes. Best-effort: paths that can't be
/// watched (e.g. an absent `~/.codex`) are skipped, not fatal.
pub struct DirtyWatcher {
    _watcher: RecommendedWatcher,
    rx: Receiver<()>,
}

impl DirtyWatcher {
    /// Watch `paths` recursively. Returns `None` if a watcher can't be created
    /// at all (the caller then just polls on its timeout).
    pub fn new<I, P>(paths: I) -> Option<Self>
    where
        I: IntoIterator<Item = P>,
        P: AsRef<Path>,
    {
        let (tx, rx) = channel();
        let mut watcher = match notify::recommended_watcher(move |res: notify::Result<_>| {
            // Coalesce every successful event into a single "dirty" ping. A send
            // failure just means the watcher was dropped — nothing to do. A
            // runtime watch error is surfaced rather than silently swallowed.
            match res {
                Ok(_) => {
                    let _ = tx.send(());
                }
                Err(err) => eprintln!("fswatch: watch error: {err}"),
            }
        }) {
            Ok(w) => w,
            Err(err) => {
                eprintln!("fswatch: could not create watcher: {err}");
                return None;
            }
        };

        for path in paths {
            let path = path.as_ref();
            if let Err(err) = watcher.watch(path, RecursiveMode::Recursive) {
                // A missing dir is fine (e.g. Codex never run); just don't watch it.
                if path.exists() {
                    eprintln!("fswatch: cannot watch {}: {err}", path.display());
                }
            }
        }

        Some(DirtyWatcher {
            _watcher: watcher,
            rx,
        })
    }

    /// Block up to `timeout`, returning `true` if a change occurred (and draining
    /// any coalesced follow-up events), `false` on timeout.
    pub fn wait(&self, timeout: Duration) -> bool {
        match self.rx.recv_timeout(timeout) {
            Ok(()) => {
                while self.rx.try_recv().is_ok() {}
                true
            }
            Err(RecvTimeoutError::Timeout) => false,
            // Sender gone (shouldn't happen while we hold the watcher) → treat as
            // no-change so the caller keeps ticking on its timeout.
            Err(RecvTimeoutError::Disconnected) => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wakes_on_a_file_change() {
        let tmp = tempfile::tempdir().unwrap();
        let watcher = DirtyWatcher::new([tmp.path()]).expect("watcher");

        std::fs::write(tmp.path().join("a.txt"), "hi").unwrap();
        // The change should arrive well within a generous window.
        assert!(
            watcher.wait(Duration::from_secs(2)),
            "expected a dirty signal"
        );
    }

    // (The "idle → timeout" path is just `recv_timeout`; we don't test it because
    // a shared/CI filesystem can deliver spurious events on the temp dir, making
    // any "stays quiet" assertion flaky.)
}
