//! Agent providers (`claude`/`codex`) + the multi-agent review orchestrator.
//!
//! [`AgentProvider`]s spawn a local CLI to review a diff against a category
//! [`ReviewSpec`]; [`ReviewOrchestrator`] fans the specs out across providers,
//! reports per-agent progress, and dedupes the merged [`Finding`]s. Running more
//! than one provider is the cross-provider review.

pub mod extract;
pub mod model;
pub mod orchestrator;
pub mod provider;

pub use extract::extract_findings;
pub use model::{Finding, ReviewSpec, Severity, default_specs};
pub use orchestrator::{AgentProgress, ProgressStatus, ReviewOrchestrator};
pub use provider::{AgentError, AgentProvider, ClaudeProvider, CodexProvider, binary_on_path};

/// Build the orchestrator from whichever agent CLIs are reachable on `PATH`
/// (`claude` always preferred; `codex` added for a cross-provider review).
/// Returns `None` if neither is available.
pub fn default_orchestrator() -> Option<ReviewOrchestrator> {
    let mut providers: Vec<Box<dyn AgentProvider>> = Vec::new();
    if ClaudeProvider.is_available() {
        providers.push(Box::new(ClaudeProvider));
    }
    if CodexProvider.is_available() {
        providers.push(Box::new(CodexProvider));
    }
    if providers.is_empty() {
        return None;
    }
    Some(ReviewOrchestrator::new(providers, default_specs()))
}
