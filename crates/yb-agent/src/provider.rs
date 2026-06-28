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
        )?;
        // `--output-format json` wraps the reply: {"type":"result","result":"…"};
        // an error envelope is surfaced rather than parsed as findings.
        let text = claude_result_text(&raw).map_err(AgentError::Msg)?;
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
        let raw = run_streamed("codex", &["exec", &prompt], cancel)?;
        Ok(extract_findings(&raw, "codex", &spec.category))
    }
}

/// Run `program args`, accumulating stdout, cancelable mid-flight. Errors on a
/// non-zero exit (carrying captured stderr) and on empty stdout — an empty reply
/// is a failure, not a clean review, and must not parse to zero findings.
fn run_streamed(program: &str, args: &[&str], cancel: &AtomicBool) -> Result<String, AgentError> {
    let mut buf = String::new();
    let result = Cmd::new(program)
        .args(args.iter().copied())
        .stream(cancel, |line| {
            buf.push_str(line);
            buf.push('\n');
        })?;
    if result.canceled {
        return Err(AgentError::Canceled(program.to_string()));
    }
    if !result.success {
        let stderr = result.stderr.trim();
        let detail = if stderr.is_empty() {
            String::new()
        } else {
            format!(": {stderr}")
        };
        return Err(AgentError::Msg(format!(
            "{program} exited with status {:?}{detail}",
            result.status
        )));
    }
    if buf.trim().is_empty() {
        return Err(AgentError::Msg(format!("{program} produced no output")));
    }
    Ok(buf)
}

/// Unwrap `claude --output-format json`'s envelope to the assistant text. The
/// CLI also reports its own failures in this envelope (`is_error: true`, or a
/// missing `result`); those are surfaced as an error rather than parsed as a
/// review, so a CLI error can't masquerade as findings.
fn claude_result_text(raw: &str) -> Result<String, String> {
    let Ok(v) = serde_json::from_str::<serde_json::Value>(raw.trim()) else {
        // Not the JSON envelope at all — hand the raw text to the extractor.
        return Ok(raw.to_string());
    };
    if v.get("is_error").and_then(serde_json::Value::as_bool) == Some(true) {
        let msg = v
            .get("result")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("claude reported an error");
        return Err(format!("claude error: {msg}"));
    }
    match v.get("result").and_then(serde_json::Value::as_str) {
        Some(text) => Ok(text.to_string()),
        // An object envelope with no `result` string is a malformed/error reply.
        None if v.is_object() => Err("claude returned no result text".to_string()),
        None => Ok(raw.to_string()),
    }
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
        assert_eq!(claude_result_text(envelope).unwrap(), "{\"findings\":[]}");
        // Non-envelope passes through.
        assert_eq!(claude_result_text("plain text").unwrap(), "plain text");
    }

    #[test]
    fn claude_result_text_surfaces_an_error_envelope() {
        // `is_error: true` must become an Err, not parse as zero findings.
        let envelope = r#"{"type":"result","is_error":true,"result":"usage limit reached"}"#;
        let err = claude_result_text(envelope).unwrap_err();
        assert!(err.contains("usage limit reached"), "got: {err}");
    }

    #[test]
    fn claude_result_text_rejects_an_object_without_result() {
        // A JSON object envelope missing `result` is malformed → Err.
        let err = claude_result_text(r#"{"type":"result","session_id":"x"}"#).unwrap_err();
        assert!(err.contains("no result"), "got: {err}");
    }
}
