"""Unit tests for TUI API-error classification.

`_classify_api_error` is the single place that turns SDK exceptions into short,
user-friendly messages so the TUI never dumps a raw exception (a JIRAError, for
example, stringifies to its entire HTTP response including every header). These
tests cover each provider branch and the length-bounding fallback.
"""

from __future__ import annotations

from scrum_agent.ui.session._utils import _classify_api_error, _extract_status_code


def _make_error(name: str, module: str, *, status=None, text=""):
    """Build a fake SDK exception with a given class name, module, and status."""
    ns: dict = {}
    if status is not None:
        ns["status_code"] = status

    def __str__(self):  # noqa: N807
        return text or name

    ns["__str__"] = __str__
    cls = type(name, (Exception,), ns)
    cls.__module__ = module
    return cls()


# The real 401 dump from the bug report — full HTTP response with every header.
_JIRA_401_DUMP = (
    "JiraError HTTP 401 url: https://youlend.atlassian.net/rest/agile/1.0/board?projectKeyOrId=PSOT\n"
    "\ttext: Client must be authenticated to access this resource.\n"
    "\tresponse headers = {'Content-Type': 'text/html', 'Www-Authenticate': 'OAuth realm=...', ...}\n"
    "\tresponse text = Client must be authenticated to access this resource."
)


class TestExtractStatusCode:
    def test_from_status_code_attr(self):
        assert _extract_status_code(_make_error("JIRAError", "jira.exceptions", status=401)) == 401

    def test_from_response_object(self):
        err = Exception()
        err.response = type("R", (), {"status_code": 403})()
        assert _extract_status_code(err) == 403

    def test_parsed_from_message(self):
        assert _extract_status_code(Exception("Something HTTP 429 happened")) == 429

    def test_none_when_absent(self):
        assert _extract_status_code(Exception("plain error")) is None

    def test_bool_is_not_a_status(self):
        err = Exception()
        err.status_code = True  # must not be treated as int status 1
        assert _extract_status_code(err) is None


class TestJira:
    def test_401_is_friendly_and_hides_dump(self):
        msg = _classify_api_error(_make_error("JIRAError", "jira.exceptions", status=401, text=_JIRA_401_DUMP))
        assert "Jira authentication failed" in msg
        # The giant HTTP dump must never leak into the UI message.
        assert "Www-Authenticate" not in msg
        assert "response headers" not in msg
        assert len(msg) < 200

    def test_404_project_not_found(self):
        msg = _classify_api_error(_make_error("JIRAError", "jira.exceptions", status=404))
        assert "not found" in msg.lower()

    def test_other_status(self):
        msg = _classify_api_error(_make_error("JIRAError", "jira.exceptions", status=500))
        assert "Jira request failed" in msg
        assert "500" in msg


class TestAzureDevOps:
    def test_auth_failure(self):
        msg = _classify_api_error(_make_error("AzureDevOpsServiceError", "azure.devops.exceptions", status=401))
        assert "Azure DevOps authentication failed" in msg

    def test_no_status_code(self):
        msg = _classify_api_error(_make_error("AzureDevOpsServiceError", "azure.devops.exceptions"))
        assert "Azure DevOps request failed" in msg


class TestGitHub:
    def test_bad_credentials(self):
        msg = _classify_api_error(_make_error("BadCredentialsException", "github.GithubException", status=401))
        assert "GitHub authentication failed" in msg


class TestGenericAndFallback:
    def test_generic_401(self):
        msg = _classify_api_error(_make_error("SomeSDKError", "acme.sdk", status=401))
        assert "Authentication failed" in msg

    def test_generic_429(self):
        msg = _classify_api_error(_make_error("SomeSDKError", "acme.sdk", status=429))
        assert "Rate limited" in msg

    def test_connection_error(self):
        # builtin ConnectionError has no status code → matched by name.
        assert "Network error" in _classify_api_error(ConnectionError("refused"))

    def test_fallback_truncates_and_takes_first_line(self):
        long = "x" * 500 + "\nsecond line should be dropped"
        msg = _classify_api_error(Exception(long))
        assert msg.startswith("Unexpected error:")
        assert "second line" not in msg
        assert len(msg) <= 220  # bounded (prefix + 200 + ellipsis)

    def test_short_fallback_passthrough(self):
        assert _classify_api_error(ValueError("boom")) == "Unexpected error: boom"
