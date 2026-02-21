from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.ui.vercel_ai.request_types import FileUIPart, TextUIPart

from lattis.telegram import (
    build_run_input,
    chat_id_for_thread_id,
    collect_assistant_text,
    extract_telegram_media_refs,
    normalize_media_type,
    split_telegram_message,
    to_data_url,
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


def test_build_run_input_accepts_file_parts() -> None:
    run_input = build_run_input(
        parts=[
            TextUIPart(text="describe this"),
            FileUIPart(media_type="image/jpeg", url="data:image/jpeg;base64,AAA="),
        ],
        session_id="s1",
        thread_id="t1",
    )
    assert run_input.messages[0].parts[0].type == "text"
    assert run_input.messages[0].parts[1].type == "file"


def test_build_run_input_requires_content() -> None:
    with pytest.raises(ValueError, match="At least one user message part is required"):
        build_run_input(session_id="s1", thread_id="t1")


def test_extract_telegram_media_refs_photo_prefers_largest() -> None:
    message = {
        "photo": [
            {"file_id": "small", "file_size": 100},
            {"file_id": "large", "file_size": 2000},
        ]
    }
    refs = extract_telegram_media_refs(message)
    assert len(refs) == 1
    assert refs[0].file_id == "large"
    assert refs[0].media_type == "image/jpeg"


def test_extract_telegram_media_refs_audio_video_document() -> None:
    message = {
        "video": {"file_id": "vid", "mime_type": "video/mp4", "file_size": 111},
        "audio": {"file_id": "aud", "mime_type": "audio/mpeg", "file_size": 222},
        "voice": {"file_id": "voc", "mime_type": "audio/ogg", "file_size": 333},
        "document": {
            "file_id": "doc",
            "file_name": "notes.pdf",
            "mime_type": "application/pdf",
            "file_size": 444,
        },
    }
    refs = extract_telegram_media_refs(message)
    assert [item.file_id for item in refs] == ["vid", "voc", "aud", "doc"]
    assert [item.media_type for item in refs] == ["video/mp4", "audio/ogg", "audio/mpeg", "application/pdf"]


def test_normalize_media_type_uses_filename_for_octet_stream() -> None:
    assert normalize_media_type("application/octet-stream", filename="photo.png") == "image/png"
    assert normalize_media_type("application/octet-stream", filename=None) == "application/octet-stream"


def test_to_data_url_has_expected_prefix() -> None:
    url = to_data_url(b"hello", media_type="text/plain")
    assert url.startswith("data:text/plain;base64,")


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
