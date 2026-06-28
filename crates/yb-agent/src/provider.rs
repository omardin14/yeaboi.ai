//! Agent providers: spawn a local `claude`/`codex` CLI to review a diff and
//! return [`Finding`]s. The CLI gets a category-specific instruction plus a
//! fixed JSON schema; [`crate::extract`] tolerantly parses the reply.

use std::sync::atomic::AtomicBool;

use thiserror::Error;
use yb_exec::Cmd;

use crate::extract::extract_findings;
use crate::model::{Finding, ReviewSpec};

#[derive(Debug, Error)]
pub enum AgentError {
    #[error(transparent)]
    Exec(#[from] yb_exec::ExecError),
    #[error("review by `{0}` was canceled")]
    Canceled(String),
    #[error("{0}")]
    Msg(String),
}

/// A reviewer backed by some agent CLI.
pub trait AgentProvider: Send + Sync {
    /// Stable identifier (`claude` / `codex`).
    fn name(&self) -> &str;

    /// Whether the underlying CLI is on `PATH`.
    fn is_available(&self) -> bool;

    /// Review `diff` for the dimension `spec`, stopping early if `cancel` is set.
    fn review(
        &self,
        diff: &str,
        spec: &ReviewSpec,
        cancel: &AtomicBool,
    ) -> Result<Vec<Finding>, AgentError>;
}

/// The instruction + JSON-schema prompt handed to an agent.
pub fn build_prompt(diff: &str, spec: &ReviewSpec) -> String {
    format!(
        "You are a meticulous senior code reviewer. {instruction}\n\n\
         Respond with ONLY a JSON object of this exact shape (no prose):\n\
         {{\"findings\":[{{\"severity\":\"critical|important|suggestion|info\",\"file\":\"path\",\"line\":123,\"title\":\"one line\",\"body\":\"detail\"}}]}}\n\
         If there are no issues, respond with {{\"findings\":[]}}.\n\n\
         Here is the unified diff to review:\n\n{diff}",
        instruction = spec.instruction,
    )
}

/// `claude -p … --output-format json`.
pub struct ClaudeProvider;

impl AgentProvider for ClaudeProvider {
    fn name(&self) -> &str {
        "claude"
    }
    fn is_available(&self) -> bool {
        binary_on_path("claude")
    }
    fn review(
        &self,
        diff: &str,
        spec: &ReviewSpec,
        cancel: &AtomicBool,
    ) -> Result<Vec<Finding>, AgentError> {
        let prompt = build_prompt(diff, spec);
        let raw = run_streamed(
            "claude",
            &["-p", &prompt, "--output-format", "json"],
            cancel,
            "claude",
        )?;
        // `--output-format json` wraps the reply: {"type":"result","result":"…"}.
        let text = claude_result_text(&raw);
        Ok(extract_findings(&text, "claude", &spec.category))
    }
}

/// `codex exec …` (non-interactive).
pub struct CodexProvider;

impl AgentProvider for CodexProvider {
    fn name(&self) -> &str {
        "codex"
    }
    fn is_available(&self) -> bool {
        binary_on_path("codex")
    }
    fn review(
        &self,
        diff: &str,
        spec: &ReviewSpec,
        cancel: &AtomicBool,
    ) -> Result<Vec<Finding>, AgentError> {
        let prompt = build_prompt(diff, spec);
        let raw = run_streamed("codex", &["exec", &prompt], cancel, "codex")?;
        Ok(extract_findings(&raw, "codex", &spec.category))
    }
}

/// Run `program args`, accumulating stdout, cancelable mid-flight.
fn run_streamed(
    program: &str,
    args: &[&str],
    cancel: &AtomicBool,
    provider: &str,
) -> Result<String, AgentError> {
    let mut buf = String::new();
    let result = Cmd::new(program)
        .args(args.iter().copied())
        .stream(cancel, |line| {
            buf.push_str(line);
            buf.push('\n');
        })?;
    if result.canceled {
        return Err(AgentError::Canceled(provider.to_string()));
    }
    if !result.success {
        return Err(AgentError::Msg(format!(
            "{program} exited with status {:?}",
            result.status
        )));
    }
    Ok(buf)
}

fn claude_result_text(raw: &str) -> String {
    if let Ok(v) = serde_json::from_str::<serde_json::Value>(raw.trim())
        && let Some(text) = v.get("result").and_then(|r| r.as_str())
    {
        return text.to_string();
    }
    raw.to_string()
}

/// Is an executable named `name` reachable on `PATH`?
pub fn binary_on_path(name: &str) -> bool {
    std::env::var_os("PATH")
        .map(|paths| std::env::split_paths(&paths).any(|dir| dir.join(name).is_file()))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::ReviewSpec;

    #[test]
    fn prompt_includes_instruction_diff_and_schema() {
        let spec = ReviewSpec {
            category: "code".into(),
            instruction: "Look for bugs.".into(),
        };
        let p = build_prompt("diff --git a b", &spec);
        assert!(p.contains("Look for bugs."));
        assert!(p.contains("diff --git a b"));
        assert!(p.contains("\"findings\""));
    }

    #[test]
    fn claude_result_text_unwraps_the_envelope() {
        let envelope = r#"{"type":"result","result":"{\"findings\":[]}","session_id":"x"}"#;
        assert_eq!(claude_result_text(envelope), "{\"findings\":[]}");
        // Non-envelope passes through.
        assert_eq!(claude_result_text("plain text"), "plain text");
    }
}
