from __future__ import annotations

from pathlib import Path

import pytest

from lattis.domain.errors import WorkspaceProtectedError
from lattis.domain.models import GLOBAL_WORKSPACE_ID
from lattis.storage.sqlite import SQLiteDaemonStore


def test_global_workspace_and_idempotent_upsert(tmp_path: Path) -> None:
    store = SQLiteDaemonStore(tmp_path / "lattis.db")
    g = store.ensure_global_workspace(str(tmp_path / "global"))
    assert g.id == GLOBAL_WORKSPACE_ID
    assert g.kind == "global"

    proj_dir = tmp_path / "proj"
    ws1, created1 = store.upsert_workspace(root_path=str(proj_dir), name="Proj")
    ws2, created2 = store.upsert_workspace(root_path=str(proj_dir), name="Other")
    assert created1 is True
    assert created2 is False
    assert ws1.id == ws2.id

    with pytest.raises(WorkspaceProtectedError):
        store.delete_workspace(GLOBAL_WORKSPACE_ID)


def test_items_sequencing_pagination_and_crash_recovery(tmp_path: Path) -> None:
    store = SQLiteDaemonStore(tmp_path / "lattis.db")
    store.ensure_global_workspace(str(tmp_path / "global"))
    thread = store.create_thread(workspace_id=GLOBAL_WORKSPACE_ID, title="Test")
    run = store.create_run(
        run_id="run-1",
        thread_id=thread.id,
        workspace_id=GLOBAL_WORKSPACE_ID,
        agent_id="assistant",
        model="test",
    )
    store.update_thread(thread.id, status="running")

    i1 = store.append_item(thread_id=thread.id, run_id=run.id, kind="user_message", status="completed", payload={"text": "hi"})
    i2 = store.append_item(thread_id=thread.id, run_id=run.id, kind="assistant_text", status="streaming", payload={"text": "hel"})
    i3 = store.append_item(thread_id=thread.id, run_id=run.id, kind="tool_call", status="streaming", payload={"tool_name": "bash"})

    assert [i1.seq, i2.seq, i3.seq] == [1, 2, 3]

    page1, has_more1 = store.list_items(thread.id, after_seq=0, limit=2)
    assert [i.seq for i in page1] == [1, 2]
    assert has_more1 is True

    page2, has_more2 = store.list_items(thread.id, after_seq=2, limit=2)
    assert [i.seq for i in page2] == [3]
    assert has_more2 is False

    # Crash recovery marks active runs & streaming items cancelled, threads idle
    recovered = store.recover_interrupted_runs()
    assert recovered == 1
    assert store.get_run("run-1").status == "cancelled"
    assert store.get_thread(thread.id).status == "idle"
    assert store.get_item(i2.id).status == "cancelled"
    assert store.get_item(i1.id).status == "completed"
