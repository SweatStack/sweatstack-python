"""Checks on each case. The reasons are the point: they say where the agent stumbled."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from sweatstack import _docs
from sweatstack.client import RESOURCES

from .cases import AgentTask, CaseMeta
from .harness import AgentRun

Context = EvaluatorContext[AgentTask, AgentRun, CaseMeta]


@dataclass
class Runs(Evaluator[AgentTask, AgentRun, CaseMeta]):
    """Scripts exit 0. Not applicable to apps."""

    def evaluate(self, ctx: Context) -> EvaluationReason | dict:
        if ctx.output.exit_code is None:
            return {}
        reason = None if ctx.output.exit_code == 0 else (ctx.output.output_tail or "")[-600:]
        return EvaluationReason(value=ctx.output.exit_code == 0, reason=reason)


@dataclass
class ProducesFiles(Evaluator[AgentTask, AgentRun, CaseMeta]):
    """The files the task asks for exist."""

    def evaluate(self, ctx: Context) -> EvaluationReason | dict:
        expected = ctx.metadata.expected_files if ctx.metadata else []
        if not expected:
            return {}
        missing = [f for f in expected if not (ctx.output.workspace / f).exists()]
        return EvaluationReason(
            value=not missing, reason=f"missing: {missing}" if missing else None
        )


@dataclass
class CurrentApi(Evaluator[AgentTask, AgentRun, CaseMeta]):
    """The code uses only names and arguments the SDK has (`python -m sweatstack._docs check`)."""

    def evaluate(self, ctx: Context) -> EvaluationReason:
        findings = [
            str(finding)
            for name, code in ctx.output.files.items()
            for finding in _docs.check_code(code, name)
        ]
        return EvaluationReason(value=not findings, reason="\n".join(findings) or None)


@dataclass
class ClientInApps(Evaluator[AgentTask, AgentRun, CaseMeta]):
    """Apps and multi-user code use a Client, never the module-level interface."""

    def evaluate(self, ctx: Context) -> EvaluationReason | dict:
        if not (ctx.metadata and ctx.metadata.requires_client):
            return {}
        uses = sorted(
            {
                f"{name}:{node.lineno} sweatstack.{node.attr}"
                for name, code in ctx.output.files.items()
                for node in _walk(code)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "sweatstack"
                and (node.attr in RESOURCES or node.attr in {"authenticate", "delegated_client"})
            }
        )
        return EvaluationReason(value=not uses, reason="\n".join(uses) or None)


@dataclass
class FailedCommands(Evaluator[AgentTask, AgentRun, CaseMeta]):
    """How often a command failed on the way: each one is friction. A score, not pass/fail."""

    def evaluate(self, ctx: Context) -> EvaluationReason:
        failed = ctx.output.failed_commands
        return EvaluationReason(value=len(failed), reason="\n\n".join(failed[:5]) or None)


@dataclass
class Budget(Evaluator[AgentTask, AgentRun, CaseMeta]):
    """Tool calls and model requests stay within a budget; a rise means the agent struggled."""

    max_tool_calls: int = 40
    max_model_requests: int = 30

    def evaluate(self, ctx: Context) -> dict[str, EvaluationReason]:
        run = ctx.output
        return {
            "tool_budget": EvaluationReason(
                value=run.tool_calls <= self.max_tool_calls, reason=f"{run.tool_calls} tool calls"
            ),
            "request_budget": EvaluationReason(
                value=run.model_requests <= self.max_model_requests,
                reason=f"{run.model_requests} model requests",
            ),
        }


@dataclass
class ConsultedSources(Evaluator[AgentTask, AgentRun, CaseMeta]):
    """Whether the agent read the skill, the docs, both or neither. A label."""

    def evaluate(self, ctx: Context) -> str:
        consulted = ctx.output.consulted
        return "both" if len(consulted) == 2 else (consulted[0] if consulted else "neither")


def _walk(code: str):
    try:
        return ast.walk(ast.parse(code))
    except SyntaxError:
        return iter(())


EVALUATORS = [
    Runs(),
    ProducesFiles(),
    CurrentApi(),
    ClientInApps(),
    FailedCommands(),
    Budget(),
    ConsultedSources(),
]
