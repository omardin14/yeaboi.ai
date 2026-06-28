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
    // Prefer a ```json fenced block.
    if let Some(blob) = fenced_block(raw)
        && let Some(findings) = parse_blob(blob, provider, category)
    {
        return findings;
    }
    // Otherwise try each balanced {…}/[…] candidate until one parses as findings —
    // so a stray `{...}` in prose before the real block doesn't defeat us.
    for (start, c) in raw.char_indices() {
        if (c == '{' || c == '[')
            && let Some(blob) = balanced_from(raw, start)
            && let Some(findings) = parse_blob(blob, provider, category)
        {
            return findings;
        }
    }
    // Nothing structured → keep the raw text as one note (never silently lost).
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

/// `Some(findings)` if `blob` is findings-shaped JSON (object with `findings`, or
/// a bare array) — even if empty; `None` if it's not that shape.
fn parse_blob(blob: &str, provider: &str, category: &str) -> Option<Vec<Finding>> {
    let value: Value = serde_json::from_str(blob).ok()?;
    if let Some(items) = value.get("findings").and_then(Value::as_array) {
        return Some(map_findings(items, provider, category));
    }
    if let Some(items) = value.as_array() {
        return Some(map_findings(items, provider, category));
    }
    None
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
            .unwrap_or(default_category)
            .to_string(),
        file: obj.get("file").and_then(Value::as_str).map(str::to_string),
        // Accept a numeric or string line ("42").
        line: obj
            .get("line")
            .and_then(|v| {
                v.as_u64()
                    .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
            })
            .map(|n| n as u32),
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

/// The contents of the first ```…``` fence, if any.
fn fenced_block(raw: &str) -> Option<&str> {
    let fence = raw.find("```")?;
    let after = &raw[fence + 3..];
    let nl = after.find('\n')?;
    let body_start = fence + 3 + nl + 1;
    let end = raw[body_start..].find("```")?;
    Some(raw[body_start..body_start + end].trim())
}

/// The balanced `{…}`/`[…]` group beginning at byte `start` (string-aware, so a
/// bracket inside a JSON string doesn't throw off the depth count).
fn balanced_from(raw: &str, start: usize) -> Option<&str> {
    let open = raw[start..].chars().next()?;
    let close = match open {
        '{' => '}',
        '[' => ']',
        _ => return None,
    };
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escaped = false;
    for (i, c) in raw[start..].char_indices() {
        if in_string {
            if escaped {
                escaped = false;
            } else if c == '\\' {
                escaped = true;
            } else if c == '"' {
                in_string = false;
            }
            continue;
        }
        match c {
            '"' => in_string = true,
            d if d == open => depth += 1,
            d if d == close => {
                depth -= 1;
                if depth == 0 {
                    return Some(&raw[start..start + i + c.len_utf8()]);
                }
            }
            _ => {}
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

    #[test]
    fn braces_inside_strings_dont_corrupt_the_scan() {
        // A `}` inside a title would mis-balance a naive scanner.
        let raw = r#"{"findings":[{"title":"Remove extra }","severity":"important"}]}"#;
        let f = extract_findings(raw, "claude", "code");
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].title, "Remove extra }");
        assert_eq!(f[0].severity, Severity::Important);
    }

    #[test]
    fn skips_a_balanced_brace_group_in_prose() {
        // A non-JSON `{...}` before the real findings block must be skipped.
        let raw = r#"I considered {some idea} but here it is:
        {"findings":[{"title":"real","severity":"critical"}]}"#;
        let f = extract_findings(raw, "claude", "code");
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].title, "real");
        assert_eq!(f[0].severity, Severity::Critical);
    }

    #[test]
    fn line_as_string_is_parsed() {
        let raw = r#"{"findings":[{"title":"x","line":"42"}]}"#;
        let f = extract_findings(raw, "c", "code");
        assert_eq!(f[0].line, Some(42));
    }
}
