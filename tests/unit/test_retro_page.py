"""Unit tests for the served browser board page + config getter."""

from scrum_agent.retro.page import build_board_html


class TestBuildBoardHtml:
    def test_self_contained(self):
        html = build_board_html()
        assert "<!DOCTYPE html>" in html
        assert "<style>" in html and "<script>" in html
        # No external resources (CSP-hostile) — no http(s) src/href, no CDN.
        assert "http://" not in html and "https://" not in html
        assert "cdn" not in html.lower()

    def test_token_free_page(self):
        # Security: the served page must NOT bake the token (GET / is unauthenticated).
        # The client reads it from the URL instead.
        html = build_board_html()
        assert "let TOKEN = new URLSearchParams" in html
        assert "const TOKEN" not in html

    def test_has_four_grids(self):
        html = build_board_html()
        for label in ("What went well", "What didn't go well", "Action items", "Demos"):
            assert label in html

    def test_renders_via_textcontent_not_innerhtml(self):
        html = build_board_html()
        assert "function esc(" in html
        assert "textContent" in html

    def test_round1_features(self):
        html = build_board_html()
        assert "AudioContext" in html and "music-btn" in html and "music-mood" in html
        assert 'data-secs="60"' in html and "timer-readout" in html and "custom-min" in html
        assert "reactionBar" in html and "/api/react" in html
        assert 'id="avatars"' in html and 'id="dice"' in html and "randomName" in html
        assert "typing…" in html and 'id="presence"' in html and "/api/presence" in html

    def test_round2_features(self):
        html = build_board_html()
        # join code gate + invite QR
        assert 'id="code-modal"' in html and "/api/join" in html
        assert 'id="invite-modal"' in html and "/api/qr" in html
        # rename control
        assert 'id="me"' in html and "openProfile" in html
        # theme switcher: swatch buttons (built from THEMES) + the alt-theme CSS block
        assert "data-set-theme" in html and '[data-theme="synthwave"]' in html
        assert '"synthwave"' in html and "buildSwatches" in html
        assert 'id="theme-btn"' in html and 'id="theme-pop"' in html
        # richer music moods
        assert ">Hip-hop<" in html and ">Jazz<" in html and "boombap" in html
        # visualizer + drag + edit/delete + confetti/alarm
        assert 'id="viz"' in html and "drawViz" in html
        assert 'draggable="true"' in html and "/api/card/move" in html
        assert "data-edit" in html and "/api/card/edit" in html and "/api/card/delete" in html
        assert 'id="confetti"' in html and "function confetti(" in html and "function alarm(" in html

    def test_compact_toolbar(self):
        html = build_board_html()
        # Toolbar icon buttons + their popovers (controls appear on demand).
        assert 'class="toolbar"' in html
        for tid in ("music-btn", "timer-btn", "theme-btn", "invite-btn"):
            assert f'id="{tid}"' in html
        for pid in ("music-pop", "timer-pop", "theme-pop"):
            assert f'id="{pid}"' in html
        assert "togglePop" in html and "closePops" in html
        # Distinct "you" chip + others-only presence stack (no duplicate self).
        assert 'class="me-chip"' in html and 'class="avatars"' in html
        assert "p.name !== NAME" in html  # self excluded from the teammate stack
        # Room count + roster of who's in the room.
        assert 'id="room-btn"' in html and 'id="roomcount"' in html
        assert 'id="room-pop"' in html and "function renderRoom" in html

    def test_stable_pid_generated_offline(self):
        html = build_board_html()
        assert "crypto.randomUUID" in html and "retro_pid" in html

    def test_no_dangling_element_ids(self):
        # Regression: toggleInvite once referenced a non-existent #invite-code and
        # threw. Every getElementById target used at runtime must exist in the DOM.
        import re

        html = build_board_html()
        referenced = set(re.findall(r'getElementById\("([^"]+)"\)', html))
        defined = set(re.findall(r'id="([^"]+)"', html))
        # Grid-scoped ids (cards-*/typing-*/in-*/edit-*) are created dynamically.
        dynamic = {r for r in referenced if r.split("-")[0] in ("cards", "typing", "in", "edit")}
        missing = referenced - defined - dynamic
        assert not missing, f"getElementById targets with no matching element: {missing}"

    def test_injected_sets_present(self):
        html = build_board_html()
        for emoji in ("👍", "❤️", "🔥"):
            assert emoji in html
        assert "🤠" in html  # an avatar


class TestConfig:
    def test_default_port(self, monkeypatch):
        from scrum_agent import config

        monkeypatch.delenv("RETRO_PORT", raising=False)
        assert config.get_retro_server_port() == 5173

    def test_env_override(self, monkeypatch):
        from scrum_agent import config

        monkeypatch.setenv("RETRO_PORT", "6000")
        assert config.get_retro_server_port() == 6000

    def test_bad_env_falls_back(self, monkeypatch):
        from scrum_agent import config

        monkeypatch.setenv("RETRO_PORT", "notanint")
        assert config.get_retro_server_port() == 5173
