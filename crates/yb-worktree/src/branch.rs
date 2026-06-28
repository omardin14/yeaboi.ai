//! Derive a git branch name from a worktree name via config rules.

use regex::Regex;

use crate::config::BranchRule;

/// Apply the first matching `BranchRule` (regex → template with `$1` captures)
/// to `name`; if none match (or there are no rules), the name is used verbatim.
/// An invalid regex in a rule is skipped, not fatal.
pub fn derive_branch(name: &str, rules: &[BranchRule]) -> String {
    for rule in rules {
        match Regex::new(&rule.pattern) {
            Ok(re) if re.is_match(name) => {
                return re.replace(name, &rule.template).into_owned();
            }
            Ok(_) => {}
            Err(e) => eprintln!("worktree: bad branch_rule /{}/: {e}", rule.pattern),
        }
    }
    name.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rule(pattern: &str, template: &str) -> BranchRule {
        BranchRule {
            pattern: pattern.to_string(),
            template: template.to_string(),
        }
    }

    #[test]
    fn applies_capture_template() {
        let rules = vec![rule(r"^issue-(\d+)$", "feature/issue-$1")];
        assert_eq!(derive_branch("issue-58", &rules), "feature/issue-58");
    }

    #[test]
    fn first_matching_rule_wins() {
        let rules = vec![rule(r"^fix-(.+)$", "fix/$1"), rule(r"^.*$", "catch/all")];
        assert_eq!(derive_branch("fix-thing", &rules), "fix/thing");
    }

    #[test]
    fn falls_back_to_the_literal_name() {
        assert_eq!(derive_branch("my-branch", &[]), "my-branch");
        let rules = vec![rule(r"^issue-(\d+)$", "feature/issue-$1")];
        assert_eq!(derive_branch("hotfix", &rules), "hotfix");
    }

    #[test]
    fn a_bad_regex_is_skipped() {
        let rules = vec![rule(r"^(unclosed", "x"), rule(r"^ok-(.+)$", "ok/$1")];
        assert_eq!(derive_branch("ok-go", &rules), "ok/go");
    }
}
