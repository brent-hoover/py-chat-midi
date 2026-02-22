"""AI tool-use integration for the MIDI Chat Sequencer."""

import os
from pathlib import Path

import anthropic
from pydantic import BaseModel

from sequencer import DRUM_MAP, SCALE_INTERVALS, ChatInterface, _command_registry

# Commands the AI should NOT have access to (meta/dangerous/irrelevant)
_AI_EXCLUDED_COMMANDS = {
    "quit",
    "exit",
    "help",
    "ports",
    "midi",
    "fold",
    "unfold",
    "undo",
    "redo",
    "history",
}


def build_tool_definitions() -> list[dict]:
    """Generate Anthropic tool definitions from the command registry."""
    tools = []
    for cmd_def in _command_registry:
        if cmd_def.hidden or cmd_def.name in _AI_EXCLUDED_COMMANDS:
            continue
        desc = cmd_def.description
        if cmd_def.usage:
            desc += f"\nUsage: {cmd_def.usage}"
        if cmd_def.hint_args:
            desc += f"\nArguments: {' '.join(cmd_def.hint_args)}"

        tool = {
            "name": f"seq_{cmd_def.name}",
            "description": desc,
            "input_schema": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "The command arguments as you would type them. "
                            "For example, for 'put': 'drums 0,4,8,12 kick 100'"
                        ),
                    }
                },
                "required": [],
            },
        }
        tools.append(tool)
    return tools


_CONTEXT_DIR = Path(__file__).parent / "context"


def _load_context_file(name: str) -> str:
    """Load a context markdown file, returning empty string if missing/empty."""
    path = _CONTEXT_DIR / name
    if path.exists():
        return path.read_text().strip()
    return ""


def build_system_prompt() -> str:
    """Build the system prompt for the AI assistant.

    Context files in context/ can use {drum_names} and {scale_names} placeholders.
    """
    sorted_drums = sorted(DRUM_MAP.items(), key=lambda x: x[1])
    drum_names = ", ".join(f"{name}={note}" for name, note in sorted_drums)
    scale_names = ", ".join(SCALE_INTERVALS.keys())
    template_vars = {"drum_names": drum_names, "scale_names": scale_names}

    # Load external context files
    agent_ctx = _load_context_file("AGENT.md")
    project_ctx = _load_context_file("PROJECT.md")
    background_ctx = _load_context_file("BACKGROUND.md")
    user_ctx = _load_context_file("USER.md")

    sections = []

    if agent_ctx:
        sections.append(agent_ctx)

    if project_ctx:
        sections.append(project_ctx.format(**template_vars))

    if background_ctx:
        sections.append(background_ctx)

    if user_ctx:
        sections.append(user_ctx)

    return "\n\n".join(sections)


def build_ai_context(chat: ChatInterface, ui_ctx: "UIContext | None") -> str:
    """Build the song context block appended to the system prompt."""
    parts = []

    song_desc = chat.seq.describe()
    if song_desc.strip():
        parts.append("CURRENT SONG STATE:\n" + song_desc)

    if ui_ctx:
        ui_lines = []
        if ui_ctx.selectedPattern:
            ui_lines.append(f"User is viewing pattern: {ui_ctx.selectedPattern}")
        if ui_ctx.recentCommands:
            recent = ui_ctx.recentCommands[-10:]
            ui_lines.append("Recent commands:\n  " + "\n  ".join(recent))
        if ui_lines:
            parts.append("UI CONTEXT:\n" + "\n".join(ui_lines))

    return "\n\n".join(parts)


# Pre-build tool definitions (they don't change at runtime)
_AI_TOOLS = build_tool_definitions()


class UIContext(BaseModel):
    selectedPattern: str | None = None
    playing: bool = False
    bpm: float = 120
    patternNames: list[str] = []
    recentCommands: list[str] = []


class AIRequest(BaseModel):
    message: str
    context: UIContext | None = None


def handle_ai_request(chat: ChatInterface, req: AIRequest) -> dict:
    """Process an AI request: call Claude with tools, execute commands, return results.

    Returns dict with keys: commands, comments, output.
    Does NOT broadcast state — caller is responsible for that.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    system = build_system_prompt()
    context_block = build_ai_context(chat, req.context)
    if context_block:
        system = system + "\n\n" + context_block

    ai_client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": req.message}]

    commands = []
    comments = []
    all_output = []
    max_rounds = 10

    for _ in range(max_rounds):
        response = ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            tools=_AI_TOOLS,
            messages=messages,
        )

        tool_results = []
        for block in response.content:
            if block.type == "text" and block.text.strip():
                comments.append(block.text.strip())
            elif block.type == "tool_use":
                cmd_name = block.name.removeprefix("seq_")
                args = block.input.get("args", "")
                cmd_line = f"{cmd_name} {args}".strip() if args else cmd_name
                commands.append(cmd_line)
                cont, output = chat.handle(cmd_line)
                all_output.extend(output)

                result_text = "\n".join(output) if output else "OK"
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

        if response.stop_reason == "end_turn" or not tool_results:
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return {
        "commands": commands,
        "comments": comments,
        "output": all_output,
    }
