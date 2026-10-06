"""The task function: set up a project, run the agent in it, run what it wrote."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from .agent import SKILL_DIR, build_agent
from .cases import AgentTask

REPO = Path(__file__).resolve().parents[2]
RUNS = (
    REPO / "evals" / "agent" / "runs"
)  # git-ignored: workspaces and program output hold real data
SKILL = REPO / "skills" / "sweatstack-python"
_EXIT_CODE = re.compile(r"\[exit code: (-?\d+)\]")


class AgentRun(BaseModel):
    """What happened in one case. Program output is personal data: it never leaves ``runs/``."""

    workspace: Path
    files: dict[str, str]
    """The Python files the agent wrote, for the evaluators and the judge."""
    final_message: str
    exit_code: int | None
    """The program's exit code; ``None`` for apps, which aren't run."""
    output_tail: str | None
    tool_calls: int
    model_requests: int
    failed_commands: list[str]
    """Each shell command that exited non-zero, with the first lines of its output."""
    consulted: list[str]
    """What the agent read: ``"skill"``, ``"docs"``."""


@dataclass
class Settings:
    """How a run is configured; set once by ``run.py``."""

    model: str | Model
    with_skill: bool = True
    web: bool = True
    run_programs: bool = True
    request_limit: int = 40
    run_dir: Path = RUNS


SETTINGS: Settings | None = None


async def solve(task: AgentTask) -> AgentRun:
    """The task function pydantic-evals runs per case."""
    assert SETTINGS is not None, "run.py sets the settings"
    workspace = _new_workspace(SETTINGS.run_dir, task, with_skill=SETTINGS.with_skill)
    agent = build_agent(
        workspace, model=SETTINGS.model, with_skill=SETTINGS.with_skill, web=SETTINGS.web
    )
    result = await agent.run(
        task.prompt, usage_limits=UsageLimits(request_limit=SETTINGS.request_limit)
    )
    messages = result.all_messages()
    exit_code, output_tail = (None, None)
    if task.kind == "script" and SETTINGS.run_programs:
        exit_code, output_tail = _run_program(workspace, task.entry)
    return AgentRun(
        workspace=workspace,
        files={str(p.relative_to(workspace)): p.read_text() for p in workspace.glob("*.py")},
        final_message=result.output,
        exit_code=exit_code,
        output_tail=output_tail,
        tool_calls=sum(isinstance(p, ToolCallPart) for m in messages for p in _parts(m)),
        model_requests=sum(isinstance(m, ModelResponse) for m in messages),
        failed_commands=_failed_commands(messages),
        consulted=_consulted(messages),
    )


def _new_workspace(run_dir: Path, task: AgentTask, *, with_skill: bool) -> Path:
    """A fresh uv project using this working tree of the SDK, with the skill installed."""
    workspace = run_dir / f"{Path(task.entry).stem}-{uuid.uuid4().hex[:8]}"  # unique per repeat
    workspace.mkdir(parents=True)
    _uv(workspace, "init", "--bare", "--no-workspace", "--quiet")
    _uv(workspace, "add", "--quiet", "--editable", f"{REPO}[polars,pandas,streamlit]")
    _uv(workspace, "add", "--quiet", "matplotlib")  # --editable would apply to it too
    if with_skill:
        shutil.copytree(SKILL, workspace / SKILL_DIR / SKILL.name)
    return workspace


def _uv(cwd: Path, *args: str) -> None:
    subprocess.run(["uv", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _run_program(workspace: Path, entry: str, timeout: int = 300) -> tuple[int, str]:
    """Run what the agent wrote, with the same environment the agent's shell had."""
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    try:
        done = subprocess.run(
            ["uv", "run", "python", entry],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout} s"
    return done.returncode, (done.stdout + done.stderr)[-4000:]


def _parts(message: ModelRequest | ModelResponse) -> list:
    return list(message.parts)


def _failed_commands(messages: list) -> list[str]:
    calls = {
        p.tool_call_id: p
        for m in messages
        for p in _parts(m)
        if isinstance(p, ToolCallPart) and p.tool_name == "run_command"
    }
    failed = []
    for m in messages:
        for p in _parts(m):
            if isinstance(p, ToolReturnPart) and p.tool_name == "run_command":
                content = str(p.content)
                code = _EXIT_CODE.search(content)
                if code and code.group(1) != "0":
                    command = calls[p.tool_call_id].args_as_dict().get("command", "?")
                    head = "\n".join(content.strip().splitlines()[-6:])
                    failed.append(f"$ {command}\n{head}")
    return failed


def _consulted(messages: list) -> list[str]:
    sources = set()
    for m in messages:
        for p in _parts(m):
            if not isinstance(p, ToolCallPart):
                continue
            args = str(p.args)
            if p.tool_name == "load_capability" or (
                p.tool_name == "read_file" and ".agents" in args
            ):
                sources.add("skill")
            elif "web_fetch" in p.tool_name or "docs.sweatstack.no" in args:
                sources.add("docs")
    return sorted(sources)
