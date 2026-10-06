"""The tasks the agent gets, each with the rubric its result is judged by."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic_evals import Case

EVAL_USER = "SDK eval"
"""The managed user that tasks which write data act on. Created on first use, never deleted."""


class AgentTask(BaseModel):
    """What the agent is asked to do."""

    prompt: str
    kind: Literal["script", "app"]
    entry: str = "main.py"
    """The file the agent writes its solution in, and the harness runs (for scripts)."""


class CaseMeta(BaseModel):
    """How the harness treats a case."""

    writes_data: bool = False
    """Writes to the managed user EVAL_USER; the lifecycle deletes what it created."""
    expected_files: list[str] = []
    requires_client: bool = False
    """Must use ``Client()`` rather than the module-level interface (apps, multi-user code)."""
    timeout_s: int = 900


def _case(name: str, task: AgentTask, rubric: str, **meta) -> Case[AgentTask, object, CaseMeta]:
    from pydantic_evals.evaluators import LLMJudge

    return Case(
        name=name,
        inputs=task,
        metadata=CaseMeta(**meta),
        evaluators=[
            LLMJudge(
                rubric=rubric,
                include_input=True,
                assertion={"evaluation_name": "solves", "include_reason": True},
            ),
        ],
    )


def cases(*, with_judge: bool = True) -> list[Case]:
    """The six tasks. ``with_judge=False`` leaves out the LLM judge (dry runs)."""
    all_cases = [
        _case(
            "recent_activities",
            AgentTask(
                prompt="Print my 5 most recent activities with their date, sport and duration.",
                kind="script",
            ),
            "1. Lists activities with the SweatStack SDK, limited to 5.\n"
            "2. Prints date, sport and duration for each.\n"
            "3. The program output shows five lines (or fewer if the user has fewer).",
        ),
        _case(
            "latest_ride_plot",
            AgentTask(
                prompt="Plot power over time for my latest ride, using Polars. Save the plot as plot.png.",
                kind="script",
            ),
            "1. Finds the latest cycling activity, then fetches its data by activity ID.\n"
            '2. Uses Polars (output="polars"), not pandas.\n'
            "3. Plots power against time and saves plot.png.",
            expected_files=["plot.png"],
        ),
        _case(
            "mean_max_90d",
            AgentTask(
                prompt="Print my power mean-max curve over the last 90 days of cycling, as a table.",
                kind="script",
            ),
            "1. Uses the longitudinal mean-max endpoint for cycling and power over 90 days.\n"
            "2. Prints durations with their best average power.",
        ),
        _case(
            "streamlit_login",
            AgentTask(
                prompt=(
                    "Build a Streamlit app with Sign in with SweatStack that shows the signed-in "
                    "user's last 10 activities. Read the client ID and secret from the environment."
                ),
                kind="app",
                entry="app.py",
            ),
            "1. Uses sweatstack.streamlit.StreamlitAuth for the sign-in.\n"
            "2. Makes its API calls through auth.client, not the module-level interface.\n"
            "3. Shows the last 10 activities after sign-in, and nothing private before.",
            requires_client=True,
        ),
        _case(
            "coach_weekly_volume",
            AgentTask(
                prompt=(
                    "For every athlete I coach, compute weekly training volume (hours) over the "
                    "last 4 weeks and print it as one DataFrame."
                ),
                kind="script",
            ),
            "1. Lists the users the coach can access and leaves out the coach.\n"
            "2. Uses delegated_client() per athlete, not a shared or switched client.\n"
            "3. Produces one frame with athlete, week and hours.",
            requires_client=True,
        ),
        _case(
            "lactate_test",
            AgentTask(
                prompt=(
                    f'For the managed user "{EVAL_USER}", record a lactate test from today with '
                    "two markers (LT1 at 200 W, LT2 at 280 W) and link a lactate trace of 2.0 "
                    "mmol/L to it."
                ),
                kind="script",
            ),
            f'1. Finds the managed user "{EVAL_USER}" and acts as them with delegated_client().\n'
            "2. Creates a test with lt1 and lt2 markers, with timezone-aware datetimes.\n"
            "3. Creates a trace with lactate 2.0 linked via test_id.",
            writes_data=True,
        ),
    ]
    if not with_judge:
        for case in all_cases:
            case.evaluators = []
    return all_cases
