"""Run the agent test.

    uv run --group evals python -m evals.agent.run                  # all cases, needs ANTHROPIC_API_KEY
    uv run --group evals python -m evals.agent.run --case latest_ride_plot
    uv run --group evals python -m evals.agent.run --without-skill  # what does the skill add?
    uv run --group evals python -m evals.agent.run --dry-run        # wiring only: no API key, no account

A real run uses your saved SweatStack sign-in (``client.authenticate()`` once, beforehand) and
the model API under ``ANTHROPIC_API_KEY``. Workspaces and program output, which hold your data,
stay in the git-ignored ``evals/agent/runs/``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

from pydantic_ai.models.test import TestModel
from pydantic_evals import Dataset
from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

from . import harness
from .cases import cases
from .evaluators import EVALUATORS
from .lifecycle import EvalLifecycle

DEFAULT_MODEL = "anthropic:claude-sonnet-5-5"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", action="append", help="Run only this case (repeatable)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="pydantic-ai model for the agent")
    parser.add_argument("--judge", default=DEFAULT_MODEL, help="pydantic-ai model for the judge")
    parser.add_argument("--repeat", type=int, default=1, help="Run each case N times")
    parser.add_argument("--without-skill", action="store_true", help="Don't install the skill")
    parser.add_argument("--dry-run", action="store_true", help="TestModel, no judge, no account")
    args = parser.parse_args(argv)

    if not args.dry_run:
        problem = _preflight()
        if problem:
            print(problem, file=sys.stderr)
            return 2
        set_default_judge_model(args.judge)

    run_dir = harness.RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    harness.SETTINGS = harness.Settings(
        model=TestModel(call_tools=[]) if args.dry_run else args.model,
        with_skill=not args.without_skill,
        web=not args.dry_run,
        run_programs=not args.dry_run,
        run_dir=run_dir,
    )
    selected = [
        c for c in cases(with_judge=not args.dry_run) if not args.case or c.name in args.case
    ]
    if not selected:
        print(f"No such case: {args.case}", file=sys.stderr)
        return 2
    dataset = Dataset(name="sweatstack-agent", cases=selected, evaluators=EVALUATORS)
    report = asyncio.run(
        dataset.evaluate(
            harness.solve,
            name=f"{'dry run' if args.dry_run else args.model}, skill {'off' if args.without_skill else 'on'}",
            max_concurrency=3,
            repeat=args.repeat,
            lifecycle=EvalLifecycle,
            progress=False,
        )
    )
    report.print(include_reasons=True, include_input=False, include_output=False)
    print(f"Workspaces of failed cases: {run_dir}")
    return 0 if not report.failures else 1


def _preflight() -> str | None:
    """Why a real run can't start, or None."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "Set ANTHROPIC_API_KEY (the agent and the judge use it), or pass --dry-run."
    from sweatstack import Client

    try:
        Client().whoami()
    except Exception as error:
        return f"No working SweatStack sign-in ({error}). Run Client().authenticate() once."
    return None


if __name__ == "__main__":
    sys.exit(main())
