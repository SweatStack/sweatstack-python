"""The snippet check (``python -m sweatstack._docs check``), and this repository's snippets.

Every Python snippet this repository publishes (README, the agent skill, examples, and the
``Examples:`` block of every public docstring) is checked against the SDK, so documentation
can't drift from the code without failing the suite.
"""

import inspect
from pathlib import Path

import pytest

from sweatstack import _docs, resources
from sweatstack.client import Client

ROOT = Path(__file__).resolve().parent.parent

MISTAKES = """
import sweatstack as ss
from datetime import date
from sweatstack import Client, Marker, NotAThing, TestResults
from sweatstack.streamlit import StreamlitAuth

ss.get_activities(limit=5)
client = Client(api_key="x", retries=3)
client.activities.list(sports=["cycling"])
client.activities.mean_max("a", "power")
coach = Client()
coach.delegated_client("u1").activities.lst()
auth = StreamlitAuth(client_id="x", redirect_uri="y")
auth.client.users.list(nme="carla")
TestResults(lt1=Marker(power=210), lt3=Marker(power=300))
with Client() as c:
    c.switch_user("u1")
"""


def _messages(code: str) -> list[str]:
    return [finding.message for finding in _docs.check_code(code)]


class TestChecker:
    def test_finds_every_kind_of_mistake(self):
        messages = _messages(MISTAKES)
        expected = [
            "sweatstack has no attribute 'NotAThing'",
            "sweatstack has no attribute 'get_activities' (removed in 0.91; use sweatstack.activities.list())",
            "Client() has no keyword argument 'retries'",
            "Activities.list() has no keyword argument 'sports'",
            "Activities.mean_max() takes 1 positional argument(s), got 2",
            "Activities has no attribute 'lst'",
            "Users.list() has no keyword argument 'nme'",
            "TestResults() has no keyword argument 'lt3'",
        ]
        for message in expected:
            assert message in messages
        assert any(
            m.startswith("Client has no attribute 'switch_user' (removed in 0.91") for m in messages
        )
        assert len(messages) == len(expected) + 1

    def test_correct_code_passes(self):
        code = """
from datetime import date
from sweatstack import Client
client = Client(timeout=30.0)
latest = client.activities.latest(sport="cycling")
client.activities.longitudinal.mean_max(sport=["cycling"], metric="power", start=date(2026, 1, 1))
client.activities.app_metadata.set("a1", data={})
client.portal.sessions.create("manage-integrations")
client.url, client.output, client.api_key
"""
        assert _messages(code) == []

    def test_unresolvable_code_is_left_alone(self):
        assert (
            _messages("result = something_else.get_activities(sports=1)\nresult.whatever()") == []
        )

    def test_syntax_errors_are_findings(self):
        assert _messages("client.activities.list(")[0].startswith("syntax error")

    def test_markdown_blocks_include_tabs_and_honour_the_skip_marker(self):
        text = (
            '=== "Python"\n\n    ```python\n    client.activities.lst()\n    ```\n\n'
            "<!-- docs: skip -->\n```python\nclient.activities.lst()\n```\n"
        )
        blocks = list(_docs.markdown_blocks(text))
        assert [(line, skipped) for line, _, skipped in blocks] == [(4, False), (9, True)]
        assert blocks[0][1] == "client.activities.lst()\n"

    def test_cli_exit_codes(self, tmp_path, capsys):
        good, bad = tmp_path / "good.md", tmp_path / "bad.md"
        good.write_text(
            "```python\nfrom sweatstack import Client\nClient().activities.list()\n```\n"
        )
        bad.write_text("```python\nimport sweatstack\nsweatstack.get_tests()\n```\n")
        assert _docs.main(["check", str(good)]) == 0
        assert _docs.main(["check", str(tmp_path)]) == 1
        assert "bad.md:3: sweatstack has no attribute 'get_tests'" in capsys.readouterr().out


@pytest.mark.parametrize("path", ["README.md", "skills", "examples"])
def test_published_snippets_match_the_sdk(path):
    report = _docs.check_paths([ROOT / path])
    assert report.blocks > 0
    assert report.findings == [], "\n".join(map(str, report.findings))


def _documented_callables():
    for name in resources.__all__:
        for attr, member in vars(getattr(resources, name)).items():
            if inspect.isfunction(member) and not attr.startswith("_"):
                yield f"{name}.{attr}", member
    yield "Client", Client
    yield "Client.__init__", Client.__init__
    for attr, member in vars(Client).items():
        if inspect.isfunction(member) and not attr.startswith("_"):
            yield f"Client.{attr}", member


@pytest.mark.parametrize("name, member", list(_documented_callables()), ids=lambda x: str(x))
def test_docstring_examples_match_the_sdk(name, member):
    findings = [
        finding
        for line, code in _docs.docstring_blocks(member.__doc__ or "")
        for finding in _docs.check_code(code, name, line)
    ]
    assert findings == [], "\n".join(map(str, findings))
