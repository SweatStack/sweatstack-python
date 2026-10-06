"""The reference agent: pydantic-ai with a workspace, a shell limited to uv, the docs, and the skill."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace, WebFetch
from pydantic_ai.models import Model
from pydantic_ai_harness import FileSystem, Shell, Skills

INSTRUCTIONS = """\
You are a developer working in the project in your workspace.
Write the solution to the task in the file the task names (main.py unless it says otherwise).
Run scripts with `uv run python <file>`. Add dependencies with `uv add <package>`.
When the program does what was asked, stop and summarise what you did in two sentences.
"""
# Nothing about SweatStack: what the agent knows has to come from the skill and the docs.

SKILL_DIR = Path(".agents") / "skills"
DOC_DOMAINS = ["docs.sweatstack.no", "app.sweatstack.no"]


def build_agent(
    workspace: Path, *, model: str | Model, with_skill: bool, web: bool = True
) -> Agent[None, str]:
    """The agent for one case.

    Args:
        workspace: The case's project directory; the agent can't read or write outside it.
        model: A pydantic-ai model name, e.g. ``"anthropic:claude-sonnet-5-5"``, or a model.
        with_skill: Install the sweatstack-python skill (copied into ``workspace``).
        web: Let the agent fetch the SweatStack docs. Off for dry runs, whose test model has
            no server-side tools.
    """
    capabilities = [
        LocalWorkspace(workspace),
        FileSystem(root_dir=workspace),
        # Commands start in the workspace. A guardrail, not a security boundary: `uv run`
        # runs whatever the agent wrote.
        Shell(allowed_commands=["uv"], default_timeout=300),
    ]
    if web:
        capabilities.append(WebFetch(allowed_domains=DOC_DOMAINS))
    if with_skill:
        capabilities.append(Skills(workspace / SKILL_DIR))
    return Agent(model, instructions=INSTRUCTIONS, capabilities=capabilities)
