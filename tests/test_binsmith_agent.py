from __future__ import annotations

from pathlib import Path

from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage

from lattis.agents.builtins import binsmith
from lattis.agents.plugin import AgentRunContext
from lattis.schedule_tools import ScheduleToolDeps


class _FakeStore:
    pass


def test_binsmith_create_deps_is_schedule_compatible(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_input = SubmitMessage(
        id="run-1",
        session_id="s1",
        thread_id="t1",
        scheduler_trigger=True,
        schedule_id="sched-1",
        messages=[
            UIMessage(
                id="msg-1",
                role="user",
                parts=[TextUIPart(text="check my calendar")],
            )
        ],
    )
    ctx = AgentRunContext(
        session_id="s1",
        thread_id="t1",
        model="test",
        workspace=workspace,
        project_root=tmp_path,
        store=_FakeStore(),
        run_input=run_input,
    )

    deps = binsmith.plugin.create_deps(ctx) if binsmith.plugin.create_deps else None
    assert isinstance(deps, ScheduleToolDeps)
    assert deps.scheduler_trigger is True
    assert deps.runtime is not None
    assert deps.runtime.schedule_id == "sched-1"
    assert (workspace / "bin").is_dir()
    assert (workspace / "data").is_dir()
    assert (workspace / "tmp").is_dir()

