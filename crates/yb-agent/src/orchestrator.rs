//! Fan-out review orchestrator: run every (provider × spec) pair concurrently,
//! report per-agent progress, then dedupe + sort the merged findings.
//!
//! Running the same diff through more than one provider is the **cross-provider**
//! review — different agents catch different things; identical findings dedupe.

use std::collections::HashSet;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use serde::{Deserialize, Serialize};

use crate::model::{Finding, ReviewSpec};
use crate::provider::AgentProvider;

/// Bound on concurrent agent processes.
const MAX_CONCURRENT: usize = 4;

/// Outcome of one agent×dimension run, for live progress.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct AgentProgress {
    pub provider: String,
    pub category: String,
    pub status: ProgressStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub enum ProgressStatus {
    /// Finished with this many findings.
    Done(#[cfg_attr(feature = "ts", ts(type = "number"))] u32),
    /// The agent errored (message).
    Failed(String),
}

pub struct ReviewOrchestrator {
    providers: Vec<Box<dyn AgentProvider>>,
    specs: Vec<ReviewSpec>,
}

impl ReviewOrchestrator {
    pub fn new(providers: Vec<Box<dyn AgentProvider>>, specs: Vec<ReviewSpec>) -> Self {
        ReviewOrchestrator { providers, specs }
    }

    /// Run the review, calling `on_progress` as each agent finishes. Cancellation
    /// (`cancel`) stops launching further work and signals running agents.
    pub fn run(
        &self,
        diff: &str,
        cancel: &AtomicBool,
        on_progress: impl Fn(AgentProgress) + Sync,
    ) -> Vec<Finding> {
        let collected: Mutex<Vec<Finding>> = Mutex::new(Vec::new());

        let pairs: Vec<(&dyn AgentProvider, &ReviewSpec)> = self
            .providers
            .iter()
            .flat_map(|p| self.specs.iter().map(move |s| (p.as_ref(), s)))
            .collect();

        for chunk in pairs.chunks(MAX_CONCURRENT) {
            if cancel.load(Ordering::Relaxed) {
                break;
            }
            std::thread::scope(|scope| {
                for &(provider, spec) in chunk {
                    let collected = &collected;
                    let on_progress = &on_progress;
                    scope.spawn(move || match provider.review(diff, spec, cancel) {
                        Ok(findings) => {
                            on_progress(AgentProgress {
                                provider: provider.name().to_string(),
                                category: spec.category.clone(),
                                status: ProgressStatus::Done(findings.len() as u32),
                            });
                            lock(collected).extend(findings);
                        }
                        Err(e) => on_progress(AgentProgress {
                            provider: provider.name().to_string(),
                            category: spec.category.clone(),
                            status: ProgressStatus::Failed(e.to_string()),
                        }),
                    });
                }
            });
        }

        let mut findings = collected.into_inner().unwrap_or_else(|e| e.into_inner());
        dedupe(&mut findings);
        findings.sort_by(|a, b| {
            a.severity
                .rank()
                .cmp(&b.severity.rank())
                .then_with(|| a.file.cmp(&b.file))
                .then_with(|| a.line.cmp(&b.line))
        });
        findings
    }
}

fn lock(m: &Mutex<Vec<Finding>>) -> std::sync::MutexGuard<'_, Vec<Finding>> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Collapse findings that are the same issue (file + line + category + title),
/// regardless of which provider reported them.
fn dedupe(findings: &mut Vec<Finding>) {
    let mut seen = HashSet::new();
    findings.retain(|f| {
        seen.insert((
            f.file.clone(),
            f.line,
            f.category.clone(),
            f.title.to_ascii_lowercase(),
        ))
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Finding, Severity, default_specs};

    /// A provider that returns a canned finding per spec (or fails).
    struct Fake {
        name: &'static str,
        fail: bool,
    }
    impl AgentProvider for Fake {
        fn name(&self) -> &str {
            self.name
        }
        fn is_available(&self) -> bool {
            true
        }
        fn review(
            &self,
            _diff: &str,
            spec: &ReviewSpec,
            _cancel: &AtomicBool,
        ) -> Result<Vec<Finding>, crate::provider::AgentError> {
            if self.fail {
                return Err(crate::provider::AgentError::Msg("boom".into()));
            }
            Ok(vec![Finding {
                severity: Severity::Important,
                category: spec.category.clone(),
                file: Some("a.rs".into()),
                line: Some(1),
                title: "shared finding".into(),
                body: String::new(),
                provider: self.name.to_string(),
            }])
        }
    }

    #[test]
    fn fans_out_and_reports_progress() {
        let orch = ReviewOrchestrator::new(
            vec![Box::new(Fake {
                name: "claude",
                fail: false,
            })],
            default_specs(),
        );
        let progress = Mutex::new(Vec::new());
        let findings = orch.run("diff", &AtomicBool::new(false), |p| {
            progress.lock().unwrap().push(p);
        });
        // One finding per spec (distinct categories → not deduped).
        assert_eq!(findings.len(), 5);
        assert_eq!(progress.lock().unwrap().len(), 5);
    }

    #[test]
    fn cross_provider_duplicates_are_merged() {
        // Two providers, same finding (file+line+category+title) → deduped to one
        // per category.
        let orch = ReviewOrchestrator::new(
            vec![
                Box::new(Fake {
                    name: "claude",
                    fail: false,
                }),
                Box::new(Fake {
                    name: "codex",
                    fail: false,
                }),
            ],
            default_specs(),
        );
        let findings = orch.run("diff", &AtomicBool::new(false), |_| {});
        assert_eq!(findings.len(), 5, "duplicates across providers merged");
    }

    #[test]
    fn a_failing_agent_reports_but_doesnt_abort() {
        let orch = ReviewOrchestrator::new(
            vec![
                Box::new(Fake {
                    name: "ok",
                    fail: false,
                }),
                Box::new(Fake {
                    name: "bad",
                    fail: true,
                }),
            ],
            default_specs(),
        );
        let progress = Mutex::new(Vec::new());
        let findings = orch.run("diff", &AtomicBool::new(false), |p| {
            progress.lock().unwrap().push(p);
        });
        // The good provider's findings still come through.
        assert_eq!(findings.len(), 5);
        let prog = progress.lock().unwrap();
        assert!(
            prog.iter()
                .any(|p| matches!(p.status, ProgressStatus::Failed(_)))
        );
    }

    #[test]
    fn cancellation_before_start_yields_nothing() {
        let orch = ReviewOrchestrator::new(
            vec![Box::new(Fake {
                name: "claude",
                fail: false,
            })],
            default_specs(),
        );
        let cancel = AtomicBool::new(true);
        assert!(orch.run("diff", &cancel, |_| {}).is_empty());
    }
}
