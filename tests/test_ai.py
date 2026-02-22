"""Tests for the AI integration module."""

from unittest.mock import MagicMock, patch

import pytest

from ai import (
    AIRequest,
    UIContext,
    build_ai_context,
    build_system_prompt,
    build_tool_definitions,
    handle_ai_request,
)
from sequencer import ChatInterface


@pytest.fixture()
def chat():
    return ChatInterface()


class TestToolDefinitions:
    def test_tools_are_generated(self):
        tools = build_tool_definitions()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tools_have_seq_prefix(self):
        tools = build_tool_definitions()
        for tool in tools:
            assert tool["name"].startswith("seq_")

    def test_excluded_commands_not_in_tools(self):
        tools = build_tool_definitions()
        names = [t["name"] for t in tools]
        assert "seq_quit" not in names
        assert "seq_help" not in names
        assert "seq_undo" not in names

    def test_tools_have_schema(self):
        tools = build_tool_definitions()
        for tool in tools:
            assert "input_schema" in tool
            assert "description" in tool


class TestSystemPrompt:
    def test_builds_without_error(self):
        prompt = build_system_prompt()
        assert isinstance(prompt, str)

    def test_includes_context_files(self):
        prompt = build_system_prompt()
        # Should have some content from the context files if they exist
        assert len(prompt) > 0


class TestAIContext:
    def test_empty_state(self, chat):
        ctx = build_ai_context(chat, None)
        assert "CURRENT SONG STATE" in ctx

    def test_with_ui_context(self, chat):
        chat.handle("new drums 16 9")
        ui = UIContext(
            selectedPattern="drums",
            recentCommands=["new drums 16 9"],
        )
        ctx = build_ai_context(chat, ui)
        assert "drums" in ctx
        assert "UI CONTEXT" in ctx

    def test_no_ui_context(self, chat):
        ctx = build_ai_context(chat, None)
        assert "UI CONTEXT" not in ctx


class TestHandleAIRequest:
    def test_missing_api_key(self, chat):
        with patch.dict("os.environ", {}, clear=True), pytest.raises(
            ValueError, match="ANTHROPIC_API_KEY"
        ):
            handle_ai_request(chat, AIRequest(message="test"))

    def test_single_tool_call(self, chat):
        """Mock the Anthropic API to return a tool call, verify command executes."""
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "seq_new"
        mock_tool_block.input = {"args": "drums 16 9"}
        mock_tool_block.id = "tool_123"

        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ai.anthropic.Anthropic", return_value=mock_client),
        ):
            result = handle_ai_request(chat, AIRequest(message="create a drum pattern"))

        assert "new drums 16 9" in result["commands"]
        assert "drums" in chat.seq.patterns

    def test_text_response(self, chat):
        """Mock the API to return a text comment."""
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Here's your pattern!"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ai.anthropic.Anthropic", return_value=mock_client),
        ):
            result = handle_ai_request(chat, AIRequest(message="hello"))

        assert "Here's your pattern!" in result["comments"]
        assert result["commands"] == []

    def test_multi_round_tool_calls(self, chat):
        """Mock the API for a multi-round conversation with tool calls."""
        # Round 1: tool call
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "seq_new"
        mock_tool_block.input = {"args": "beat 16 9"}
        mock_tool_block.id = "tool_1"

        mock_response_1 = MagicMock()
        mock_response_1.content = [mock_tool_block]
        mock_response_1.stop_reason = "tool_use"

        # Round 2: text response (done)
        mock_text = MagicMock()
        mock_text.type = "text"
        mock_text.text = "Done!"

        mock_response_2 = MagicMock()
        mock_response_2.content = [mock_text]
        mock_response_2.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [mock_response_1, mock_response_2]

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ai.anthropic.Anthropic", return_value=mock_client),
        ):
            result = handle_ai_request(chat, AIRequest(message="make a beat"))

        assert len(result["commands"]) == 1
        assert "Done!" in result["comments"]
        assert mock_client.messages.create.call_count == 2
