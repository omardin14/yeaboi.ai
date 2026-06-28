# yeaboi.ai — common tasks.
# You really only need two:  `make dev` (desktop app)  ·  `make cli` (headless).
# Both set up everything themselves (cargo path, frontend deps, builds).

# Resolve cargo even when ~/.cargo/bin isn't on PATH (rustup installs it there).
CARGO := $(shell command -v cargo 2>/dev/null || echo "$(HOME)/.cargo/bin/cargo")
PNPM  ?= pnpm
# Prepended for tools we shell out to that call `cargo` by name (e.g. tauri dev).
CARGO_BIN := $(HOME)/.cargo/bin

# Deterministic dev-server port per checkout: main -> 1420, each worktree hashes
# to 1430-1529, so several `make dev` instances can run without colliding.
YB_DEV_PORT := $(shell \
  if [ "$(notdir $(CURDIR))" = "ai-manager" ]; then echo 1420; else \
    h=$$(printf '%s' '$(CURDIR)' | (md5 2>/dev/null || md5sum) | tr -dc '0-9a-f' | cut -c1-4); \
    echo $$((1430 + 0x$$h % 100)); \
  fi)

.DEFAULT_GOAL := help

# ---- main ----

.PHONY: dev
dev: desktop/node_modules ## Run the desktop app (installs deps + builds + hot-reload)
	cd desktop && PATH="$(CARGO_BIN):$$PATH" YB_DEV_PORT=$(YB_DEV_PORT) \
		$(PNPM) tauri dev --config '{"build":{"devUrl":"http://localhost:$(YB_DEV_PORT)"}}'

.PHONY: cli
cli: ## Run the headless CLI (prints a live snapshot as JSON)
	@$(CARGO) run -q -p yb-cli -- --json

.PHONY: port
port: ## Print this checkout's deterministic dev-server port
	@echo $(YB_DEV_PORT)

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
	$(CARGO) test -p yb-core --features ts
	$(CARGO) test -p yb-git --features ts

.PHONY: e2e
e2e: desktop/node_modules ## Playwright smoke of the built frontend (needs `pnpm exec playwright install chromium`)
	cd desktop && $(PNPM) build && $(PNPM) e2e

.PHONY: verify
verify: lint test cli ## Run everything CI runs

# ---- internal ----

# Install frontend deps only when missing or the lockfile changed.
desktop/node_modules: desktop/package.json desktop/pnpm-lock.yaml
	cd desktop && $(PNPM) install
	@touch desktop/node_modules

.PHONY: help
help: ## Show this help
	@echo "yeaboi.ai — run 'make dev' (desktop app) or 'make cli' (headless)."
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
