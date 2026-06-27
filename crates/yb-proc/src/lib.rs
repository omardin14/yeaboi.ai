//! Process + port introspection (sysinfo, lsof) and signals (nix). Phase 0 stub.

/// Crate marker used by Phase 0 to verify linkage; replaced by `ProcTable`,
/// port enumeration, and `actions::sigterm` in Phase 1.
pub fn placeholder() -> &'static str {
    "yb-proc"
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_name() {
        assert_eq!(super::placeholder(), "yb-proc");
    }
}
