from __future__ import annotations

import asyncio

import pytest

from lattis.telegram import (
    build_run_input,
    chat_id_for_thread_id,
    collect_assistant_text,
    split_telegram_message,
    thread_id_for_chat,
)


def test_thread_id_for_chat_formats_positive_and_negative() -> None:
    assert thread_id_for_chat(1234) == "tg-1234"
    assert thread_id_for_chat(-5678) == "tg-m5678"
    assert thread_id_for_chat(42, prefix="chat") == "chat-42"


def test_chat_id_for_thread_id_round_trip() -> None:
    assert chat_id_for_thread_id("tg-1234") == 1234
    assert chat_id_for_thread_id("tg-m5678") == -5678
    assert chat_id_for_thread_id("other-1234") is None


def test_split_telegram_message_respects_limit() -> None:
    text = "one two three four five six seven eight"
    chunks = split_telegram_message(text, max_length=10)
    assert chunks
    assert all(len(chunk) <= 10 for chunk in chunks)
    assert " ".join(chunks) == " ".join(text.split())


def test_split_telegram_message_handles_long_unbroken_text() -> None:
    text = "x" * 9000
    chunks = split_telegram_message(text, max_length=4096)
    assert [len(chunk) for chunk in chunks] == [4096, 4096, 808]


def test_build_run_input_sets_session_and_thread() -> None:
    run_input = build_run_input(text="hello", session_id="s1", thread_id="t1")
    assert run_input.session_id == "s1"
    assert run_input.thread_id == "t1"
    assert run_input.messages[0].role == "user"


def test_collect_assistant_text_from_stream_events() -> None:
    events = [
        {"type": "text-start", "id": "a"},
        {"type": "text-delta", "id": "a", "delta": "Hello"},
        {"type": "text-start", "id": "b"},
        {"type": "text-delta", "id": "b", "delta": "World"},
    ]

    async def generate():
        for event in events:
            yield event

    text = asyncio.run(collect_assistant_text(generate()))
    assert text == "Hello\n\nWorld"


def test_collect_assistant_text_raises_on_error_event() -> None:
    events = [
        {"type": "text-start", "id": "a"},
        {"type": "error", "errorText": "Boom"},
    ]

    async def generate():
        for event in events:
            yield event

    with pytest.raises(RuntimeError, match="Boom"):
        asyncio.run(collect_assistant_text(generate()))
