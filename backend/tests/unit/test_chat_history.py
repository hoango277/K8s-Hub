"""Tests for title generation and reloading history as context.

No database: uses fake objects carrying exactly the attributes the functions
need to read.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.db.models.thread import TITLE_MAX
from app.modules.nl_command.agent import history_to_messages
from app.services.thread_service import DEFAULT_TITLE, title_from


@dataclass
class FakeMessage:
    role: str
    content: str
    status: str = "complete"


# --------------------------------------------------------------------------
# Titles
# --------------------------------------------------------------------------


def test_title_is_taken_from_question():
    assert title_from("Scale deployment api to 3") == "Scale deployment api to 3"


def test_title_collapses_extra_whitespace():
    assert title_from("  pod   api   failing\n\nwhy  ") == "pod api failing why"


def test_empty_title_uses_default():
    assert title_from("   \n  ") == DEFAULT_TITLE


def test_long_title_is_trimmed_to_fit_db_column():
    """Trimming even one character too few would break the INSERT for exceeding
    the VARCHAR length."""
    title = title_from("a" * 500)

    assert len(title) <= TITLE_MAX
    assert title.endswith("…")


def test_title_at_exact_limit_is_not_trimmed():
    intact = "b" * TITLE_MAX
    assert title_from(intact) == intact


# --------------------------------------------------------------------------
# History -> messages for the model
# --------------------------------------------------------------------------


def test_keeps_order_and_roles():
    messages = history_to_messages(
        [
            FakeMessage("user", "what's wrong with pod api"),
            FakeMessage("assistant", "Checking"),
            FakeMessage("user", "anything else"),
        ]
    )

    assert [type(m) for m in messages] == [HumanMessage, AIMessage, HumanMessage]
    assert [m.content for m in messages] == [
        "what's wrong with pod api",
        "Checking",
        "anything else",
    ]


def test_drops_empty_messages():
    """The assistant record is created BEFORE it speaks, so when history is
    reloaded for that same turn its content is still empty. Some providers
    return an error when sent an empty message."""
    messages = history_to_messages(
        [FakeMessage("user", "question"), FakeMessage("assistant", "", status="streaming")]
    )

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)


@pytest.mark.parametrize("status", ["streaming", "error"])
def test_drops_incomplete_answers(status: str):
    """A half-finished answer must not be fed back as context — the model would
    think it had finished saying it and carry on from the middle."""
    messages = history_to_messages(
        [FakeMessage("assistant", "I was looking at", status=status)]
    )

    assert messages == []


def test_drops_system_role():
    """The system prompt is assembled at runtime, not taken from history —
    otherwise there would be two copies stacked on top of each other."""
    messages = history_to_messages([FakeMessage("system", "you are an assistant")])

    assert messages == []
