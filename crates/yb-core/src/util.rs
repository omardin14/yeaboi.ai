//! Small shared helpers for the collectors.

/// Trim `s` and cap it to `max` characters, appending `…` when truncated.
/// Counts by `char` so it never splits a multi-byte codepoint.
pub(crate) fn truncate(s: &str, max: usize) -> String {
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
    fn leaves_short_strings_untouched() {
        assert_eq!(truncate("  hi  ", 10), "hi");
    }

    #[test]
    fn caps_and_appends_ellipsis() {
        assert_eq!(truncate("abcdef", 3), "abc…");
    }

    #[test]
    fn counts_chars_not_bytes() {
        // 4 multi-byte chars, cap 2 → 2 chars + ellipsis, no panic.
        assert_eq!(truncate("日本語語", 2), "日本…");
    }
}
