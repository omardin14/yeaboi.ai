//! Review value types (ts-exported for the desktop) + the default review specs.

use serde::{Deserialize, Serialize};

/// How serious a finding is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub enum Severity {
    Critical,
    Important,
    Suggestion,
    Info,
}

impl Severity {
    /// Parse a loose severity string from an agent (case-insensitive); unknown
    /// → `Suggestion`.
    pub fn parse(s: &str) -> Severity {
        match s.trim().to_ascii_lowercase().as_str() {
            "critical" | "blocker" | "high" => Severity::Critical,
            "important" | "major" | "medium" => Severity::Important,
            "info" | "note" | "nit" => Severity::Info,
            _ => Severity::Suggestion,
        }
    }

    /// Sort key (Critical first).
    pub fn rank(self) -> u8 {
        match self {
            Severity::Critical => 0,
            Severity::Important => 1,
            Severity::Suggestion => 2,
            Severity::Info => 3,
        }
    }
}

/// One review finding.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[cfg_attr(
    feature = "ts",
    ts(export, export_to = "../../../desktop/src/lib/bindings/")
)]
pub struct Finding {
    pub severity: Severity,
    /// Which review dimension produced it (code / error-handling / …).
    pub category: String,
    pub file: Option<String>,
    #[cfg_attr(feature = "ts", ts(type = "number | null"))]
    pub line: Option<u32>,
    pub title: String,
    pub body: String,
    /// Which agent produced it (`claude` / `codex`).
    pub provider: String,
}

/// One review dimension: a category + the instruction handed to the agent.
#[derive(Debug, Clone)]
pub struct ReviewSpec {
    pub category: String,
    pub instruction: String,
}

impl ReviewSpec {
    fn new(category: &str, instruction: &str) -> Self {
        ReviewSpec {
            category: category.to_string(),
            instruction: instruction.to_string(),
        }
    }
}

/// The default 5-way review fan-out.
pub fn default_specs() -> Vec<ReviewSpec> {
    vec![
        ReviewSpec::new(
            "code",
            "Review for correctness bugs, logic errors, and risky changes.",
        ),
        ReviewSpec::new(
            "error-handling",
            "Review error handling: swallowed errors, unwrap/expect/panic in runtime paths, missing Result propagation, silent fallbacks.",
        ),
        ReviewSpec::new(
            "tests",
            "Review test coverage: untested new behavior, weak assertions, missing edge cases.",
        ),
        ReviewSpec::new(
            "comments",
            "Review comments and naming: stale/misleading comments, unclear names.",
        ),
        ReviewSpec::new(
            "docs",
            "Review docs: missing or outdated documentation for the changed public surface.",
        ),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn severity_parse_is_lenient() {
        assert_eq!(Severity::parse("CRITICAL"), Severity::Critical);
        assert_eq!(Severity::parse(" Major "), Severity::Important);
        assert_eq!(Severity::parse("nit"), Severity::Info);
        assert_eq!(Severity::parse("whatever"), Severity::Suggestion);
    }

    #[test]
    fn default_specs_are_the_five_dimensions() {
        let specs = default_specs();
        assert_eq!(specs.len(), 5);
        assert!(specs.iter().any(|s| s.category == "error-handling"));
    }
}
