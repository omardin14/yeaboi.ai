//! Tolerant extraction of [`Finding`]s from an agent's free-form output.
//!
//! Agents don't always honor the requested JSON exactly — they wrap it in prose
//! or a ```json fence. We pull out the outermost JSON blob and read a `findings`
//! array (or a bare array); anything we can't parse becomes a single `Info`
//! finding carrying the raw text, so a review is never silently lost.

use serde_json::Value;

use crate::model::{Finding, Severity};

/// Parse `raw` into findings, tagging each with `provider` and defaulting a
/// missing category to `category`.
pub fn extract_findings(raw: &str, provider: &str, category: &str) -> Vec<Finding> {
    if let Some(blob) = find_json(raw)
        && let Ok(value) = serde_json::from_str::<Value>(blob)
    {
        if let Some(items) = value.get("findings").and_then(Value::as_array) {
            return map_findings(items, provider, category);
        }
        if let Some(items) = value.as_array() {
            return map_findings(items, provider, category);
        }
    }
    // Couldn't find/parse structured findings → keep the raw text as one note.
    vec![Finding {
        severity: Severity::Info,
        category: category.to_string(),
        file: None,
        line: None,
        title: "Unstructured review (couldn't parse JSON)".to_string(),
        body: truncate(raw, 4000),
        provider: provider.to_string(),
    }]
}

fn map_findings(items: &[Value], provider: &str, category: &str) -> Vec<Finding> {
    items
        .iter()
        .filter_map(|v| to_finding(v, provider, category))
        .collect()
}

fn to_finding(v: &Value, provider: &str, default_category: &str) -> Option<Finding> {
    let obj = v.as_object()?;
    let title = first_str(obj, &["title", "message", "summary"])?;
    Some(Finding {
        severity: obj
            .get("severity")
            .and_then(Value::as_str)
            .map(Severity::parse)
            .unwrap_or(Severity::Suggestion),
        category: obj
            .get("category")
            .and_then(Value::as_str)
            .map(str::to_string)
            .unwrap_or_else(|| default_category.to_string()),
        file: obj.get("file").and_then(Value::as_str).map(str::to_string),
        line: obj.get("line").and_then(Value::as_u64).map(|n| n as u32),
        title,
        body: first_str(obj, &["body", "description", "detail"]).unwrap_or_default(),
        provider: provider.to_string(),
    })
}

fn first_str(obj: &serde_json::Map<String, Value>, keys: &[&str]) -> Option<String> {
    keys.iter()
        .find_map(|k| obj.get(*k).and_then(Value::as_str))
        .map(str::to_string)
}

/// Find the JSON payload in agent output: a ```json fence, else a balanced
/// object/array starting at the first opener.
fn find_json(raw: &str) -> Option<&str> {
    if let Some(fence) = raw.find("```") {
        let after = &raw[fence + 3..];
        if let Some(nl) = after.find('\n') {
            let body_start = fence + 3 + nl + 1;
            if let Some(end) = raw[body_start..].find("```") {
                return Some(raw[body_start..body_start + end].trim());
            }
        }
    }

    let (start, open) = raw.char_indices().find(|(_, c)| *c == '{' || *c == '[')?;
    let close = if open == '{' { '}' } else { ']' };
    let mut depth = 0i32;
    for (i, c) in raw[start..].char_indices() {
        if c == open {
            depth += 1;
        } else if c == close {
            depth -= 1;
            if depth == 0 {
                return Some(&raw[start..start + i + c.len_utf8()]);
            }
        }
    }
    None
}

fn truncate(s: &str, max: usize) -> String {
    let s = s.trim();
    if s.chars().count() <= max {
        return s.to_string();
    }
    let mut out: String = s.chars().take(max).collect();
    out.push('…');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_findings_object() {
        let raw = r#"Here's my review:
        {"findings":[
          {"severity":"critical","file":"a.rs","line":12,"title":"Bug","body":"oops"},
          {"severity":"nit","title":"style"}
        ]}"#;
        let f = extract_findings(raw, "claude", "code");
        assert_eq!(f.len(), 2);
        assert_eq!(f[0].severity, Severity::Critical);
        assert_eq!(f[0].file.as_deref(), Some("a.rs"));
        assert_eq!(f[0].line, Some(12));
        assert_eq!(f[0].provider, "claude");
        assert_eq!(f[1].severity, Severity::Info);
        assert_eq!(f[1].category, "code"); // defaulted
    }

    #[test]
    fn parses_a_fenced_bare_array() {
        let raw = "Sure!\n```json\n[{\"title\":\"x\",\"severity\":\"important\"}]\n```\nDone.";
        let f = extract_findings(raw, "codex", "tests");
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].severity, Severity::Important);
        assert_eq!(f[0].category, "tests");
    }

    #[test]
    fn empty_findings_means_a_clean_review() {
        let f = extract_findings(r#"{"findings": []}"#, "claude", "code");
        assert!(f.is_empty());
    }

    #[test]
    fn unparseable_output_becomes_one_info_note() {
        let f = extract_findings("the diff looks fine to me, no issues", "claude", "docs");
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].severity, Severity::Info);
        assert!(f[0].body.contains("looks fine"));
    }

    #[test]
    fn ignores_a_finding_without_a_title() {
        let f = extract_findings(r#"{"findings":[{"severity":"high"}]}"#, "c", "code");
        assert!(f.is_empty(), "a finding with no title is dropped");
    }
}
