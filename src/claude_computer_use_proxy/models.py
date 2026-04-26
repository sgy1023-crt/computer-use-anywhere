from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
PROVIDER_OFFICIAL_COMPATIBLE = "official_compatible"
PROVIDER_ANTHROPIC_OFFICIAL = "anthropic_official"


@dataclass(slots=True)
class ProviderConfig:
    provider_kind: str = PROVIDER_OPENAI_COMPATIBLE
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    max_tokens: int = 2048
    temperature: float = 0.2
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    anthropic_version: str = "2023-06-01"
    anthropic_beta: str = ""
    anthropic_tool_type: str = ""
    enable_thinking: bool = False
    thinking_budget: int = 2048


@dataclass(slots=True)
class SessionConfig:
    scale: float = 0.8
    jpeg_quality: int = 70
    max_steps: int = 30
    confirm_actions: bool = True
    hide_window_while_running: bool = True
    mask_own_window: bool = True
    own_window_title: str = "Claude 电脑操作代理"
    official_enhanced: bool = True
    browser_dom_enabled: bool = True
    browser_dom_first: bool = True
    browser_debug_host: str = "127.0.0.1"
    browser_debug_port: int = 9222
    session_root: Path | None = None


@dataclass(slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class AssistantReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    assistant_message: dict[str, Any] | None = None
    reasoning_summary: str = ""


@dataclass(slots=True)
class Snapshot:
    path: Path
    data_url: str
    width: int
    height: int
    actual_width: int
    actual_height: int
    foreground_window_title: str = ""
    visible_window_titles: list[str] = field(default_factory=list)

    @property
    def image_base64(self) -> str:
        return self.data_url.split(",", 1)[1]


@dataclass(slots=True)
class ActionResult:
    message: str
    snapshot: Snapshot


@dataclass(slots=True)
class AgentEvent:
    kind: str
    message: str
    snapshot_path: Path | None = None
    payload: dict[str, Any] = field(default_factory=dict)
