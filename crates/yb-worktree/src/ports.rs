//! Deterministic worktree → port allocation.
//!
//! Byte-compatible with the reference `assign-port.ts`: the worktree's absolute
//! path is MD5'd, the first 4 bytes are read big-endian as a u32, `% range`
//! gives an offset onto `worktree_base`. The main checkout is special-cased to
//! `base`. Using **MD5** (not a stronger hash) is deliberate — it makes the port
//! yeaboi shows match the one a repo's own `pnpm dev` computes.

use md5::{Digest, Md5};
use serde::Deserialize;

/// Port ranges. Defaults match the reference (main 4000, worktrees 4100–4199).
#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(default)]
pub struct PortConfig {
    /// Port for the main checkout.
    pub base: u16,
    /// Start of the worktree port range.
    pub worktree_base: u16,
    /// Size of the worktree range (`worktree_base .. worktree_base + range`).
    pub range: u16,
}

impl Default for PortConfig {
    fn default() -> Self {
        PortConfig {
            base: 4000,
            worktree_base: 4100,
            range: 100,
        }
    }
}

impl PortConfig {
    /// The deterministic port for a checkout at `path`.
    pub fn port_for(&self, path: &str, is_main: bool) -> u16 {
        if is_main {
            return self.base;
        }
        let digest = Md5::digest(path.as_bytes());
        let n = u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]);
        self.worktree_base + (n % self.range.max(1) as u32) as u16
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn main_checkout_gets_the_base_port() {
        assert_eq!(PortConfig::default().port_for("/anything", true), 4000);
    }

    #[test]
    fn byte_parity_with_assign_port_ts() {
        // Values computed from the reference algorithm (md5 → first 4 BE bytes
        // → % 100 → +4100) for these exact path strings.
        let c = PortConfig::default();
        assert_eq!(
            c.port_for("/Users/dinho/Documents/ai-manager-feat", false),
            4157
        );
        assert_eq!(c.port_for("/tmp/wt", false), 4127);
    }

    #[test]
    fn is_deterministic_and_in_range() {
        let c = PortConfig::default();
        let p1 = c.port_for("/some/worktree/path", false);
        let p2 = c.port_for("/some/worktree/path", false);
        assert_eq!(p1, p2);
        assert!((4100..4200).contains(&p1), "port {p1} out of range");
    }

    #[test]
    fn respects_a_custom_range() {
        let c = PortConfig {
            base: 3000,
            worktree_base: 3100,
            range: 10,
        };
        let p = c.port_for("/x", false);
        assert!((3100..3110).contains(&p));
        assert_eq!(c.port_for("/x", true), 3000);
    }
}
