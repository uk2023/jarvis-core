"""JARVIS Coding Agent -- repo-scale autonomous coding subsystem.

See BLUEPRINT.md (repo root) for the full design and phase status.
Public entry point: run_coding_agent() in core/orchestration/companion_tools.py,
which is what tool_registry.py's "run_coding_agent" WRITE_TOOL calls.
"""

from .agent import CodingAgent
from .contracts import CodingTask, ToolCall, ToolResult, VerificationResult
from .tool_contract import ToolRegistry, ToolSpec
from . import approval, packaging, repo_tools

__all__ = [
    "CodingAgent", "CodingTask", "ToolCall", "ToolResult", "VerificationResult",
    "ToolRegistry", "ToolSpec", "approval", "packaging", "repo_tools",
]
