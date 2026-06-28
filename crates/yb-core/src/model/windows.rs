//! Static `model → context-window` lookup.
//!
//! Used to turn a session's token usage into a percentage. The values are a
//! best-effort snapshot of known 2026 models; `~/.claude/stats-cache.json`
//! carries a per-model `contextWindow` we prefer when present (see
//! [`crate::adapters::claude`]), so this table is the offline fallback, not the
//! source of truth.

/// Default window when the model is unknown — every current Claude model is at
/// least 200k, so this never *over*-reports usage for an unknown Claude model.
pub const DEFAULT_WINDOW: u64 = 200_000;

/// Extended-context window for models flagged with the `[1m]` beta suffix.
pub const EXTENDED_WINDOW: u64 = 1_000_000;

/// Context-window size (in tokens) for `model`.
///
/// Matching is intentionally loose (substring/prefix) so new point releases of
/// a known family resolve without a table edit. A `[1m]` suffix always wins —
/// it's an explicit per-session opt-in to the extended window.
pub fn context_window(model: &str) -> u64 {
    let m = model.to_ascii_lowercase();

    // Explicit extended-context opt-in (e.g. `claude-opus-4-8[1m]`).
    if m.contains("[1m]") || m.contains("-1m") {
        return EXTENDED_WINDOW;
    }

    // Sonnet 4.x ships a 1M context window by default.
    if m.contains("sonnet-4") || m.contains("sonnet4") {
        return EXTENDED_WINDOW;
    }

    // Opus and Haiku 4.x are 200k.
    if m.contains("opus") || m.contains("haiku") {
        return DEFAULT_WINDOW;
    }

    // OpenAI / Codex families we may see via the codex collector.
    if m.contains("gpt-4") || m.contains("gpt-5") || m.contains("o1") || m.contains("o3") {
        return 128_000;
    }

    DEFAULT_WINDOW
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opus_and_haiku_are_200k() {
        assert_eq!(context_window("claude-opus-4-8"), 200_000);
        assert_eq!(context_window("claude-opus-4-7"), 200_000);
        assert_eq!(context_window("claude-haiku-4-5-20251001"), 200_000);
    }

    #[test]
    fn sonnet_4_is_1m() {
        assert_eq!(context_window("claude-sonnet-4-6"), 1_000_000);
    }

    #[test]
    fn explicit_1m_suffix_wins() {
        assert_eq!(context_window("claude-opus-4-8[1m]"), 1_000_000);
    }

    #[test]
    fn unknown_model_falls_back_to_default() {
        assert_eq!(context_window("some-future-model"), DEFAULT_WINDOW);
    }
}
