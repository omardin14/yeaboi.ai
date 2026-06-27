# ai-manager — common tasks.
# You really only need two:  `make dev` (desktop app)  ·  `make cli` (headless).
# Both set up everything themselves (cargo path, frontend deps, builds).

# Resolve cargo even when ~/.cargo/bin isn't on PATH (rustup installs it there).
CARGO := $(shell command -v cargo 2>/dev/null || echo "$(HOME)/.cargo/bin/cargo")
PNPM  ?= pnpm
# Prepended for tools we shell out to that call `cargo` by name (e.g. tauri dev).
CARGO_BIN := $(HOME)/.cargo/bin

.DEFAULT_GOAL := help

# ---- main ----

.PHONY: dev
dev: desktop/node_modules ## Run the desktop app (installs deps + builds + hot-reload)
	cd desktop && PATH="$(CARGO_BIN):$$PATH" $(PNPM) tauri dev

.PHONY: cli
cli: ## Run the headless CLI (prints a live snapshot as JSON)
	@$(CARGO) run -q -p aim-cli -- --json

# ---- quality ----

.PHONY: test
test: desktop/node_modules ## Run all Rust + frontend tests
	$(CARGO) test --workspace
	cd desktop && $(PNPM) test

.PHONY: lint
lint: desktop/node_modules ## rustfmt --check + clippy -D warnings + tsc
	$(CARGO) fmt --all -- --check
	$(CARGO) clippy --workspace --all-targets -- -D warnings
	cd desktop && $(PNPM) typecheck

.PHONY: fmt
fmt: ## Auto-format Rust
	$(CARGO) fmt --all

.PHONY: build
build: ## Build the Rust workspace
	$(CARGO) build --workspace

.PHONY: gen-bindings
gen-bindings: ## Regenerate Rust->TS bindings (desktop/src/lib/bindings)
	$(CARGO) test -p aim-core --features ts

.PHONY: verify
verify: lint test cli ## Run everything CI runs

# ---- internal ----

# Install frontend deps only when missing or the lockfile changed.
desktop/node_modules: desktop/package.json desktop/pnpm-lock.yaml
	cd desktop && $(PNPM) install
	@touch desktop/node_modules

.PHONY: help
help: ## Show this help
	@echo "ai-manager — run 'make dev' (desktop app) or 'make cli' (headless)."
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
