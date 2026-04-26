from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from .agent import AGENT_WINDOW_TITLE, ComputerUseAgent
from .models import (
    AgentEvent,
    PROVIDER_ANTHROPIC_OFFICIAL,
    PROVIDER_OFFICIAL_COMPATIBLE,
    PROVIDER_OPENAI_COMPATIBLE,
    ProviderConfig,
    SessionConfig,
)
from .provider import (
    ANTHROPIC_VERSION_DEFAULT,
    AnthropicOfficialProvider,
    guess_anthropic_computer_contract,
    provider_diagnostics,
)
from .runtime_diagnostics import format_runtime_diagnostic, run_local_preflight


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


ROOT = _app_root()
SETTINGS_PATH = ROOT / "settings.json"

BG = "#F6F2EA"
PANEL = "#FCF8F2"
PANEL_ALT = "#F8F2E8"
BORDER = "#DED4C7"
TEXT = "#2D261F"
MUTED = "#6D655B"
ACCENT = "#C96A4B"
ACCENT_ACTIVE = "#B45B3F"
ACCENT_SOFT = "#EFE2D2"
SUCCESS = "#2F6F50"
WARNING = "#A15D2E"
ERROR = "#A24334"
LOG_BG = "#F9F5EE"
OFFICIAL = "#8B5CF6"
OFFICIAL_SOFT = "#F0EAFE"


@dataclass(slots=True)
class ApprovalRequest:
    summary: str
    ready: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(AGENT_WINDOW_TITLE)
        self.root.geometry("1540x960")
        self.root.minsize(1280, 800)
        self.root.configure(bg=BG)

        self.events: queue.Queue[AgentEvent | ApprovalRequest] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.preview_image: ImageTk.PhotoImage | None = None
        self.current_session_root: Path | None = None
        self.run_hidden = False
        self.mode_widgets: dict[str, dict[str, tk.Widget]] = {}

        self.settings = self._load_settings()
        self._build_style()
        self._build_ui()
        self._apply_settings()
        self.root.after(120, self._drain_queue)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))

        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(14, 8),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_ACTIVE), ("pressed", ACCENT_ACTIVE), ("disabled", "#D8CBBE")],
            foreground=[("disabled", "#F6F2EA")],
        )

        style.configure(
            "Soft.TButton",
            background=PANEL_ALT,
            foreground=TEXT,
            borderwidth=1,
            padding=(14, 8),
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "Soft.TButton",
            background=[("active", "#F2EADF"), ("pressed", "#EDE1D1"), ("disabled", "#F4EFE7")],
            foreground=[("disabled", "#A89D8E")],
        )

        style.configure("Soft.TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("Soft.TCheckbutton", background=[("active", PANEL)])

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=18, pady=18)
        shell.grid_columnconfigure(0, weight=0)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(1, weight=1)

        self._build_topbar(shell)
        self._build_sidebar(shell)
        self._build_main(shell)

    def _build_topbar(self, parent: tk.Widget) -> None:
        topbar = tk.Frame(parent, bg=BG)
        topbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        topbar.grid_columnconfigure(0, weight=1)

        left = tk.Frame(topbar, bg=BG)
        left.grid(row=0, column=0, sticky="w")
        tk.Label(
            left,
            text=AGENT_WINDOW_TITLE,
            bg=BG,
            fg=TEXT,
            font=("Microsoft YaHei UI", 22, "bold"),
        ).pack(anchor="w")
        self.subtitle_var = tk.StringVar(value="三模式：兼容中转站 / 官方体验兼容 / Anthropic 官方")
        tk.Label(
            left,
            textvariable=self.subtitle_var,
            bg=BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        right = tk.Frame(topbar, bg=BG)
        right.grid(row=0, column=1, sticky="e")
        self.status_badge = tk.Label(
            right,
            text="空闲",
            bg=ACCENT_SOFT,
            fg=ACCENT_ACTIVE,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=6,
        )
        self.status_badge.pack(anchor="e")
        self.session_hint = tk.Label(
            right,
            text="尚未开始会话",
            bg=BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        )
        self.session_hint.pack(anchor="e", pady=(6, 0))

    def _build_sidebar(self, parent: tk.Widget) -> None:
        sidebar = tk.Frame(parent, bg=BG, width=460)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(0, weight=1)
        sidebar.grid_rowconfigure(1, weight=0)
        sidebar.grid_columnconfigure(0, weight=1)

        scroll_shell = tk.Frame(sidebar, bg=BG)
        scroll_shell.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        scroll_shell.grid_rowconfigure(0, weight=1)
        scroll_shell.grid_columnconfigure(0, weight=1)

        self.sidebar_canvas = tk.Canvas(scroll_shell, bg=BG, highlightthickness=0, bd=0, relief="flat")
        sidebar_scrollbar = ttk.Scrollbar(scroll_shell, orient="vertical", command=self.sidebar_canvas.yview)
        self.sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)
        self.sidebar_canvas.grid(row=0, column=0, sticky="nsew")
        sidebar_scrollbar.grid(row=0, column=1, sticky="ns")

        self.sidebar_content = tk.Frame(self.sidebar_canvas, bg=BG)
        self.sidebar_window = self.sidebar_canvas.create_window((0, 0), window=self.sidebar_content, anchor="nw")
        self.sidebar_content.bind("<Configure>", self._on_sidebar_content_configure)
        self.sidebar_canvas.bind("<Configure>", self._on_sidebar_canvas_configure)
        self.sidebar_canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

        self.provider_kind_var = tk.StringVar(value=PROVIDER_OPENAI_COMPATIBLE)
        self.hero_title_var = tk.StringVar()
        self.hero_body_var = tk.StringVar()
        self.contract_hint_var = tk.StringVar()

        hero = self._card(self.sidebar_content, bg=PANEL_ALT, pady=16)
        hero.pack(fill="x", pady=(0, 12))
        tk.Label(
            hero,
            textvariable=self.hero_title_var,
            bg=PANEL_ALT,
            fg=TEXT,
            font=("Microsoft YaHei UI", 15, "bold"),
            justify="left",
        ).pack(anchor="w")
        tk.Label(
            hero,
            textvariable=self.hero_body_var,
            bg=PANEL_ALT,
            fg=MUTED,
            font=("Microsoft YaHei UI", 10),
            justify="left",
            wraplength=390,
        ).pack(anchor="w", pady=(8, 12))
        chips = tk.Frame(hero, bg=PANEL_ALT)
        chips.pack(fill="x", pady=(0, 12))
        for text in ("实时截图", "前台校验", "网页 DOM", "中文过程"):
            tk.Label(
                chips,
                text=text,
                bg="#EFE2D2",
                fg=ACCENT_ACTIVE,
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=10,
                pady=5,
            ).pack(side="left", padx=(0, 8))
        mode_row = tk.Frame(hero, bg=PANEL_ALT)
        mode_row.pack(fill="x")
        self._build_mode_switch(mode_row)

        connection_card = self._card(self.sidebar_content)
        connection_card.pack(fill="x", pady=(0, 12))
        self._card_title(connection_card, "连接与模型")

        self.base_url_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.model_var.trace_add("write", lambda *_args: self._refresh_contract_hint())
        self._add_entry(connection_card, "接口地址", self.base_url_var)
        self._add_entry(connection_card, "API Key", self.api_key_var, show="*")
        self._add_entry(connection_card, "模型", self.model_var)

        self.official_card = self._card(self.sidebar_content)
        self._card_title(self.official_card, "Anthropic 官方协议")
        self.anthropic_version_var = tk.StringVar()
        self.anthropic_beta_var = tk.StringVar()
        self.anthropic_tool_type_var = tk.StringVar()
        self.official_enhanced_var = tk.BooleanVar(value=True)
        self.enable_thinking_var = tk.BooleanVar(value=False)
        self.thinking_budget_var = tk.StringVar()
        self._add_entry(self.official_card, "anthropic-version", self.anthropic_version_var)
        self._add_entry(self.official_card, "anthropic-beta", self.anthropic_beta_var)
        self._add_entry(self.official_card, "computer tool 类型", self.anthropic_tool_type_var)
        ttk.Checkbutton(
            self.official_card,
            text="官方增强原生（安全阀 + 桌面状态）",
            variable=self.official_enhanced_var,
            style="Soft.TCheckbutton",
        ).pack(anchor="w", pady=(4, 2))
        ttk.Checkbutton(
            self.official_card,
            text="启用官方 thinking 元信息",
            variable=self.enable_thinking_var,
            style="Soft.TCheckbutton",
        ).pack(anchor="w", pady=(4, 4))
        self._add_entry(self.official_card, "thinking token 预算", self.thinking_budget_var, width=18)
        tk.Label(
            self.official_card,
            textvariable=self.contract_hint_var,
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
            justify="left",
            wraplength=390,
        ).pack(anchor="w", pady=(2, 0))

        runtime_card = self._card(self.sidebar_content)
        runtime_card.pack(fill="x", pady=(0, 12))
        self._card_title(runtime_card, "运行参数")
        self.scale_var = tk.StringVar()
        self.jpeg_quality_var = tk.StringVar()
        self.max_steps_var = tk.StringVar()
        self.confirm_var = tk.BooleanVar(value=False)
        self.hide_window_var = tk.BooleanVar(value=True)
        self.browser_dom_var = tk.BooleanVar(value=True)
        self.browser_dom_first_var = tk.BooleanVar(value=True)
        self.browser_debug_host_var = tk.StringVar()
        self.browser_debug_port_var = tk.StringVar()
        self._add_entry(runtime_card, "截图缩放", self.scale_var, width=18)
        self._add_entry(runtime_card, "JPEG 质量", self.jpeg_quality_var, width=18)
        self._add_entry(runtime_card, "最大步数", self.max_steps_var, width=18)
        ttk.Checkbutton(runtime_card, text="逐步确认每次操作", variable=self.confirm_var, style="Soft.TCheckbutton").pack(anchor="w", pady=(4, 2))
        ttk.Checkbutton(runtime_card, text="运行时自动隐藏本窗口（推荐）", variable=self.hide_window_var, style="Soft.TCheckbutton").pack(anchor="w", pady=(2, 2))
        ttk.Checkbutton(runtime_card, text="启用浏览器 DOM 工具（兼容模式）", variable=self.browser_dom_var, style="Soft.TCheckbutton").pack(anchor="w", pady=(2, 2))
        ttk.Checkbutton(runtime_card, text="网页任务优先使用 DOM（推荐）", variable=self.browser_dom_first_var, style="Soft.TCheckbutton").pack(anchor="w", pady=(2, 2))
        self._add_entry(runtime_card, "浏览器调试地址", self.browser_debug_host_var, width=18)
        self._add_entry(runtime_card, "浏览器调试端口", self.browser_debug_port_var, width=18)
        browser_actions = tk.Frame(runtime_card, bg=PANEL)
        browser_actions.pack(fill="x", pady=(0, 10))
        ttk.Button(browser_actions, text="启动调试 Edge", command=self.on_launch_debug_edge, style="Soft.TButton").pack(side="left")
        ttk.Button(browser_actions, text="本机自检", command=self.on_run_local_diagnostics, style="Soft.TButton").pack(side="left", padx=(8, 0))
        tk.Label(
            runtime_card,
            text="浏览器 DOM 需要 Edge/Chrome 用 --remote-debugging-port=9222 启动；不可用时会自动回退到截图操作。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
            wraplength=390,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        self.advanced_card = self._card(self.sidebar_content)
        self.advanced_card.pack(fill="x", pady=(0, 12))
        self._card_title(self.advanced_card, "附加请求设置")
        self.extra_headers_text = self._add_text(self.advanced_card, "额外请求头 JSON", lines=4)
        self.extra_body_text = self._add_text(self.advanced_card, "额外请求体 JSON", lines=4)

        task_card = self._card(sidebar)
        task_card.grid(row=1, column=0, sticky="ew")
        self._card_title(task_card, "任务与操作")
        self.task_text = self._styled_text(task_card, height=6)
        self.task_text.pack(fill="x", pady=(2, 12))

        actions = tk.Frame(task_card, bg=PANEL)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="开始运行", command=self.on_start, style="Accent.TButton")
        self.stop_button = ttk.Button(actions, text="停止", command=self.on_stop, style="Soft.TButton", state="disabled")
        self.open_session_button = ttk.Button(actions, text="打开会话目录", command=self.on_open_session, style="Soft.TButton", state="disabled")
        self.start_button.pack(side="left")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.open_session_button.pack(side="left", padx=(8, 0))

    def _build_main(self, parent: tk.Widget) -> None:
        main_shell = tk.Frame(parent, bg=BG)
        main_shell.grid(row=1, column=1, sticky="nsew")
        main_shell.grid_rowconfigure(0, weight=1)
        main_shell.grid_columnconfigure(0, weight=1)

        self.main_canvas = tk.Canvas(main_shell, bg=BG, highlightthickness=0, bd=0, relief="flat")
        main_scrollbar = ttk.Scrollbar(main_shell, orient="vertical", command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=main_scrollbar.set)
        self.main_canvas.grid(row=0, column=0, sticky="nsew")
        main_scrollbar.grid(row=0, column=1, sticky="ns")

        self.main_content = tk.Frame(self.main_canvas, bg=BG)
        self.main_window = self.main_canvas.create_window((0, 0), window=self.main_content, anchor="nw")
        self.main_content.bind("<Configure>", self._on_main_content_configure)
        self.main_canvas.bind("<Configure>", self._on_main_canvas_configure)

        main = self.main_content
        main.grid_rowconfigure(0, weight=0)
        main.grid_rowconfigure(1, weight=0)
        main.grid_rowconfigure(2, weight=1)
        main.grid_rowconfigure(3, weight=0)
        main.grid_columnconfigure(0, weight=1)

        insight = self._card(main, bg=PANEL_ALT, pady=14)
        insight.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(insight, text="运行状态", bg=PANEL_ALT, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self.status_var = tk.StringVar(value="空闲")
        tk.Label(insight, textvariable=self.status_var, bg=PANEL_ALT, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(3, 8))
        self.meta_var = tk.StringVar(value="等待任务启动")
        tk.Label(insight, textvariable=self.meta_var, bg=PANEL_ALT, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(anchor="w")

        analysis_card = self._card(main)
        analysis_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self._card_title(analysis_card, "公开思考链（原文）")
        self.reasoning_text = tk.Text(
            analysis_card,
            height=5,
            wrap="word",
            state="disabled",
            bg="#FFFDFC",
            fg=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            font=("Microsoft YaHei UI", 10),
            padx=10,
            pady=10,
        )
        self.reasoning_text.pack(fill="both", expand=True)
        tk.Label(
            analysis_card,
            text="动作摘要",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w", pady=(10, 6))
        self.analysis_text = tk.Text(
            analysis_card,
            height=4,
            wrap="word",
            state="disabled",
            bg="#FFFDFC",
            fg=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            font=("Microsoft YaHei UI", 10),
            padx=10,
            pady=10,
        )
        self.analysis_text.pack(fill="both", expand=True)

        preview_card = self._card(main)
        preview_card.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        preview_card.grid_rowconfigure(1, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        top = tk.Frame(preview_card, bg=PANEL)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self._card_title(top, "实时截图", pack=False).grid(row=0, column=0, sticky="w")
        tk.Label(top, text="模型的坐标判断会基于这张缩放后的截图", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).grid(row=0, column=1, sticky="e")

        image_shell = tk.Frame(preview_card, bg="#F3ECE1", highlightbackground=BORDER, highlightthickness=1, bd=0)
        image_shell.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        image_shell.grid_rowconfigure(0, weight=1)
        image_shell.grid_columnconfigure(0, weight=1)

        self.preview_label = tk.Label(
            image_shell,
            text="暂无截图\n开始运行后，这里会显示最新画面",
            bg="#F3ECE1",
            fg=MUTED,
            font=("Microsoft YaHei UI", 12),
            justify="center",
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)

        log_card = self._card(main)
        log_card.grid(row=3, column=0, sticky="ew")
        self._card_title(log_card, "事件日志")
        log_shell = tk.Frame(log_card, bg=LOG_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        log_shell.pack(fill="both", expand=True, pady=(2, 0))
        log_shell.grid_columnconfigure(0, weight=1)
        log_shell.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_shell,
            wrap="word",
            state="disabled",
            height=10,
            bg=LOG_BG,
            fg=TEXT,
            relief="flat",
            bd=0,
            font=("Consolas", 10),
            insertbackground=TEXT,
            padx=12,
            pady=12,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_shell, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self._configure_log_tags()
        self._configure_reasoning_tags()

    def _build_mode_switch(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, bg=PANEL_ALT)
        row.pack(fill="x")
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, weight=1)
        self._create_mode_option(
            row,
            0,
            PROVIDER_OPENAI_COMPATIBLE,
            "兼容模式",
            "适合中转站",
        )
        self._create_mode_option(
            row,
            1,
            PROVIDER_OFFICIAL_COMPATIBLE,
            "官方体验",
            "中转站可用",
        )
        self._create_mode_option(
            row,
            2,
            PROVIDER_ANTHROPIC_OFFICIAL,
            "官方模式",
            "Anthropic 协议",
        )

    def _create_mode_option(self, parent: tk.Widget, column: int, kind: str, title: str, subtitle: str) -> None:
        card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, bd=0, padx=12, pady=10, cursor="hand2")
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
        card.grid_columnconfigure(1, weight=1)

        circle = tk.Canvas(card, width=18, height=18, bg=PANEL, highlightthickness=0, bd=0, cursor="hand2")
        circle.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10))
        label = tk.Label(card, text=title, bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2")
        label.grid(row=0, column=1, sticky="w")
        hint = tk.Label(card, text=subtitle, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9), cursor="hand2")
        hint.grid(row=1, column=1, sticky="w")

        for widget in (card, circle, label, hint):
            widget.bind("<Button-1>", lambda _event, value=kind: self._set_provider_kind(value))

        self.mode_widgets[kind] = {"card": card, "circle": circle, "label": label, "hint": hint}

    def _set_provider_kind(self, kind: str) -> None:
        self.provider_kind_var.set(kind)
        self._refresh_mode_ui()

    def _refresh_mode_ui(self) -> None:
        selected = self.provider_kind_var.get()
        for kind, widgets in self.mode_widgets.items():
            active = kind == selected
            official_tone = kind in {PROVIDER_ANTHROPIC_OFFICIAL, PROVIDER_OFFICIAL_COMPATIBLE}
            card_bg = OFFICIAL_SOFT if active and official_tone else (ACCENT_SOFT if active else PANEL)
            card_fg = OFFICIAL if active and official_tone else (ACCENT_ACTIVE if active else TEXT)
            card = widgets["card"]
            circle = widgets["circle"]
            label = widgets["label"]
            hint = widgets["hint"]
            card.configure(bg=card_bg, highlightbackground=(OFFICIAL if active and official_tone else (ACCENT if active else BORDER)))
            label.configure(bg=card_bg, fg=card_fg)
            hint.configure(bg=card_bg, fg=MUTED)
            circle.configure(bg=card_bg)
            circle.delete("all")
            outline = OFFICIAL if official_tone else ACCENT
            circle.create_oval(2, 2, 16, 16, outline=outline, width=2, fill=outline if active else card_bg)

        if selected == PROVIDER_ANTHROPIC_OFFICIAL:
            self.hero_title_var.set("Anthropic 官方 computer use")
            self.hero_body_var.set("这套模式直接走 Anthropic Messages API、官方 beta 头和官方 computer 工具协议；可切换纯原生或增强原生。")
            self.subtitle_var.set("三模式：当前为 Anthropic 官方模式")
            self.official_card.pack(fill="x", pady=(0, 12), before=self.advanced_card)
        elif selected == PROVIDER_OFFICIAL_COMPATIBLE:
            self.hero_title_var.set("官方体验兼容模式")
            self.hero_body_var.set("底层仍走 OpenAI-compatible 中转站，但按官方 computer use 的单 computer 工具循环执行；适合比较官方风格效果。")
            self.subtitle_var.set("三模式：当前为官方体验兼容模式")
            self.official_card.pack_forget()
        else:
            self.hero_title_var.set("兼容中转站的代理式 computer use")
            self.hero_body_var.set("这套模式保留中转站兼容，同时增加网页 DOM 工具。网页任务先读 DOM，桌面任务再走截图和本地执行器。")
            self.subtitle_var.set("三模式：当前为兼容中转站模式")
            self.official_card.pack_forget()
        self._refresh_contract_hint()

    def _refresh_contract_hint(self) -> None:
        beta, tool_type = guess_anthropic_computer_contract(self.model_var.get().strip())
        self.contract_hint_var.set(f"按当前模型建议自动填充：anthropic-beta={beta}，tool={tool_type}")
        if self.provider_kind_var.get() == PROVIDER_ANTHROPIC_OFFICIAL:
            if not self.anthropic_version_var.get().strip():
                self.anthropic_version_var.set(ANTHROPIC_VERSION_DEFAULT)
            if not self.anthropic_beta_var.get().strip():
                self.anthropic_beta_var.set(beta)
            if not self.anthropic_tool_type_var.get().strip():
                self.anthropic_tool_type_var.set(tool_type)

    def _card(self, parent: tk.Widget, *, bg: str = PANEL, pady: int = 14) -> tk.Frame:
        return tk.Frame(parent, bg=bg, highlightbackground=BORDER, highlightthickness=1, bd=0, padx=16, pady=pady)

    def _card_title(self, parent: tk.Widget, text: str, *, pack: bool = True) -> tk.Label:
        label = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=TEXT, font=("Microsoft YaHei UI", 11, "bold"))
        if pack:
            label.pack(anchor="w", pady=(0, 10))
        return label

    def _styled_entry(self, parent: tk.Widget, variable: tk.StringVar, *, show: str | None = None, width: int = 40) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            show=show or "",
            relief="flat",
            bd=0,
            bg="#FFFDFC",
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=("Microsoft YaHei UI", 10),
        )

    def _styled_text(self, parent: tk.Widget, *, height: int) -> tk.Text:
        return tk.Text(
            parent,
            height=height,
            wrap="word",
            relief="flat",
            bd=0,
            bg="#FFFDFC",
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=("Microsoft YaHei UI", 10),
            padx=10,
            pady=10,
        )

    def _add_entry(self, parent: tk.Widget, label: str, variable: tk.StringVar, *, show: str | None = None, width: int = 40) -> tk.Entry:
        tk.Label(parent, text=label, bg=parent.cget("bg"), fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 4))
        entry = self._styled_entry(parent, variable, show=show, width=width)
        entry.pack(fill="x", pady=(0, 10), ipady=8)
        return entry

    def _add_text(self, parent: tk.Widget, label: str, *, lines: int) -> tk.Text:
        tk.Label(parent, text=label, bg=parent.cget("bg"), fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 4))
        widget = self._styled_text(parent, height=lines)
        widget.pack(fill="x", pady=(0, 10))
        return widget

    def _configure_log_tags(self) -> None:
        self.log_text.tag_configure("prefix", foreground=MUTED)
        self.log_text.tag_configure("系统", foreground=MUTED)
        self.log_text.tag_configure("状态", foreground=ACCENT_ACTIVE)
        self.log_text.tag_configure("模型", foreground=TEXT)
        self.log_text.tag_configure("摘要", foreground=ACCENT_ACTIVE)
        self.log_text.tag_configure("执行", foreground=SUCCESS)
        self.log_text.tag_configure("截图", foreground=ACCENT_ACTIVE)
        self.log_text.tag_configure("警告", foreground=WARNING)
        self.log_text.tag_configure("错误", foreground=ERROR)
        self.log_text.tag_configure("完成", foreground=SUCCESS)
        self.log_text.tag_configure("确认", foreground=ACCENT_ACTIVE)
        self.log_text.tag_configure("诊断", foreground=WARNING)

    def _configure_reasoning_tags(self) -> None:
        self.reasoning_text.tag_configure("label", foreground=MUTED)
        self.reasoning_text.tag_configure("title", foreground=MUTED, font=("Microsoft YaHei UI", 9, "bold"))
        self.reasoning_text.tag_configure("公开思考", foreground=TEXT, spacing3=8)
        self.reasoning_text.tag_configure("派生说明", foreground=ACCENT_ACTIVE, spacing3=8)

    def _on_sidebar_content_configure(self, _event: tk.Event) -> None:
        self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all"))

    def _on_sidebar_canvas_configure(self, event: tk.Event) -> None:
        self.sidebar_canvas.itemconfigure(self.sidebar_window, width=event.width)

    def _on_main_content_configure(self, _event: tk.Event) -> None:
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_main_canvas_configure(self, event: tk.Event) -> None:
        self.main_canvas.itemconfigure(self.main_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return
        current = widget
        while current is not None:
            if current == self.sidebar_canvas or current == self.sidebar_content:
                self.sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            if current == self.main_canvas or current == self.main_content:
                self.main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            current = getattr(current, "master", None)

    def _apply_settings(self) -> None:
        self.provider_kind_var.set(str(self.settings.get("provider_kind") or PROVIDER_OPENAI_COMPATIBLE))
        self.base_url_var.set(str(self.settings.get("base_url") or os.environ.get("ANTHROPIC_BASE_URL") or "https://openrouter.ai/api"))
        self.model_var.set(str(self.settings.get("model") or os.environ.get("COMPUTER_USE_MODEL") or "anthropic/claude-sonnet-4.6"))
        self.api_key_var.set(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or "")
        self.anthropic_version_var.set(str(self.settings.get("anthropic_version") or ANTHROPIC_VERSION_DEFAULT))
        self.anthropic_beta_var.set(str(self.settings.get("anthropic_beta") or ""))
        self.anthropic_tool_type_var.set(str(self.settings.get("anthropic_tool_type") or ""))
        self.official_enhanced_var.set(bool(self.settings.get("official_enhanced", True)))
        self.enable_thinking_var.set(bool(self.settings.get("enable_thinking", False)))
        self.thinking_budget_var.set(str(self.settings.get("thinking_budget") or "2048"))
        self.scale_var.set(str(self.settings.get("scale") or "0.8"))
        self.jpeg_quality_var.set(str(self.settings.get("jpeg_quality") or "70"))
        self.max_steps_var.set(str(self.settings.get("max_steps") or "30"))
        self.confirm_var.set(bool(self.settings.get("confirm_actions", False)))
        self.hide_window_var.set(bool(self.settings.get("hide_window_while_running", True)))
        self.browser_dom_var.set(bool(self.settings.get("browser_dom_enabled", True)))
        self.browser_dom_first_var.set(bool(self.settings.get("browser_dom_first", True)))
        self.browser_debug_host_var.set(str(self.settings.get("browser_debug_host") or "127.0.0.1"))
        self.browser_debug_port_var.set(str(self.settings.get("browser_debug_port") or "9222"))
        self.extra_headers_text.delete("1.0", "end")
        self.extra_headers_text.insert("1.0", str(self.settings.get("extra_headers_json") or "{}"))
        self.extra_body_text.delete("1.0", "end")
        self.extra_body_text.insert("1.0", str(self.settings.get("extra_body_json") or "{}"))
        self.task_text.delete("1.0", "end")
        self.task_text.insert("1.0", str(self.settings.get("last_task") or ""))
        self._set_reasoning_placeholder("这里显示模型每一步原样公开说出来的话，不直接暴露原始隐藏思维链。")
        self._set_analysis_text("这里显示动作理由、参数和官方 thinking 元信息。")
        self._refresh_mode_ui()

    def on_start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            provider_config, session_config, task = self._collect_inputs()
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        self._save_settings(task)
        self.stop_event = threading.Event()
        self.current_session_root = session_config.session_root
        self.session_hint.configure(text=f"会话目录：{session_config.session_root.name}")
        mode_name = self._mode_name(provider_config.provider_kind)
        self.meta_var.set(f"模式：{mode_name} · 模型：{provider_config.model} · 最大步数：{session_config.max_steps}")
        self._append_log("系统", f"会话目录：{session_config.session_root}")
        self._append_log("系统", f"运行模式：{mode_name}")
        if provider_config.provider_kind == PROVIDER_ANTHROPIC_OFFICIAL:
            preview_provider = AnthropicOfficialProvider(provider_config)
            self._append_log("系统", f"anthropic-version={preview_provider.version}")
            self._append_log("系统", f"anthropic-beta={preview_provider.beta_header}")
            self._append_log("系统", f"computer tool={preview_provider.tool_type}")
            self._append_log("系统", f"官方模式：{'增强原生' if session_config.official_enhanced else '纯原生'}")
        elif provider_config.provider_kind == PROVIDER_OFFICIAL_COMPATIBLE:
            self._append_log("系统", "官方体验兼容：走 OpenAI-compatible 中转站，但只暴露单 computer 工具并禁用 DOM。")
        elif session_config.browser_dom_enabled:
            self._append_log(
                "系统",
                f"浏览器 DOM：已启用，调试端口 {session_config.browser_debug_host}:{session_config.browser_debug_port}",
            )
            if session_config.browser_dom_first:
                self._append_log("系统", "网页任务 DOM 优先：已启用，明显网页任务会先要求模型尝试 browser_dom。")
        if session_config.hide_window_while_running:
            self._append_log("系统", "已启用运行时自动隐藏窗口。")
        diagnostics = provider_diagnostics(provider_config)
        if diagnostics:
            for message in diagnostics:
                self._append_log("诊断", message)
        else:
            self._append_log("诊断", "启动前静态检查未发现明显协议配置问题。")
        self._clear_public_reasoning()
        self._set_reasoning_placeholder("等待模型输出第一句公开思考。这里会按步骤保留原文。")
        self._set_analysis_text("准备开始。这里会显示当前动作的摘要、参数和官方 thinking 元信息。")
        self._set_running(True)

        if session_config.hide_window_while_running:
            self._hide_window_for_run()
            self.root.after(180, lambda: self._start_worker(provider_config, session_config, task))
        else:
            self._start_worker(provider_config, session_config, task)

    def _start_worker(self, provider_config: ProviderConfig, session_config: SessionConfig, task: str) -> None:
        self.worker = threading.Thread(
            target=self._run_agent,
            args=(provider_config, session_config, task),
            daemon=True,
        )
        self.worker.start()

    def on_stop(self) -> None:
        self.stop_event.set()
        self._update_status("正在停止...", tone="warning")
        self._append_log("系统", "已请求停止。")

    def on_open_session(self) -> None:
        if not self.current_session_root or not self.current_session_root.exists():
            return
        os.startfile(str(self.current_session_root))

    def on_launch_debug_edge(self) -> None:
        try:
            port = int(self.browser_debug_port_var.get().strip() or "9222")
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("端口有误", "浏览器调试端口必须在 1 到 65535 之间。", parent=self.root)
            return
        edge_path = self._find_edge_executable()
        if not edge_path:
            messagebox.showerror("未找到 Edge", "没有找到 msedge.exe。你也可以手动用 --remote-debugging-port 启动 Chrome/Edge。", parent=self.root)
            return
        user_data_dir = Path(tempfile.gettempdir()) / "computer-use-edge-profile"
        args = [
            edge_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--new-window",
            "about:blank",
        ]
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            messagebox.showerror("启动失败", str(exc), parent=self.root)
            return
        self._append_log("系统", f"已启动调试 Edge：127.0.0.1:{port}")

    def on_run_local_diagnostics(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("正在运行", "请先停止当前任务，再做本机自检。", parent=self.root)
            return
        try:
            session_config = self._collect_session_config_for_diagnostics()
        except ValueError as exc:
            messagebox.showerror("自检参数有误", str(exc), parent=self.root)
            return
        self._append_log("诊断", "开始本机自检：截图、桌面控制、浏览器 DOM。")
        threading.Thread(target=self._run_local_diagnostics, args=(session_config,), daemon=True).start()

    def _run_local_diagnostics(self, session_config: SessionConfig) -> None:
        for item in run_local_preflight(session_config):
            self.events.put(AgentEvent(kind="diagnostic", message=format_runtime_diagnostic(item)))

    @staticmethod
    def _find_edge_executable() -> str:
        found = shutil.which("msedge.exe") or shutil.which("msedge")
        if found:
            return found
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return ""

    def _hide_window_for_run(self) -> None:
        self.run_hidden = True
        self.root.update_idletasks()
        self.root.iconify()

    def _restore_window_if_hidden(self) -> None:
        if not self.run_hidden:
            return
        self.run_hidden = False
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def _run_agent(self, provider_config: ProviderConfig, session_config: SessionConfig, task: str) -> None:
        try:
            agent = ComputerUseAgent(
                provider_config,
                session_config,
                event_callback=self.events.put,
                stop_event=self.stop_event,
                confirm_callback=self._request_approval if session_config.confirm_actions else None,
            )
            agent.run(task)
        except Exception as exc:
            self.events.put(AgentEvent(kind="error", message=str(exc)))

    def _request_approval(self, summary: str) -> bool:
        request = ApprovalRequest(summary=summary)
        self.events.put(request)
        request.ready.wait()
        return request.approved

    def _collect_inputs(self) -> tuple[ProviderConfig, SessionConfig, str]:
        provider_kind = self.provider_kind_var.get().strip() or PROVIDER_OPENAI_COMPATIBLE
        base_url = self.base_url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        model = self.model_var.get().strip()
        task = self.task_text.get("1.0", "end").strip()
        if not base_url:
            raise ValueError("接口地址不能为空。")
        if not api_key:
            raise ValueError("API Key 不能为空。")
        if not model:
            raise ValueError("模型不能为空。")
        if not task:
            raise ValueError("任务不能为空。")

        scale = float(self.scale_var.get().strip())
        if scale <= 0 or scale > 1:
            raise ValueError("截图缩放必须在 0 到 1 之间。")
        jpeg_quality = int(self.jpeg_quality_var.get().strip())
        if jpeg_quality < 40 or jpeg_quality > 95:
            raise ValueError("JPEG 质量必须在 40 到 95 之间。")
        max_steps = int(self.max_steps_var.get().strip())
        if max_steps <= 0:
            raise ValueError("最大步数必须大于 0。")
        browser_debug_port = int(self.browser_debug_port_var.get().strip() or "9222")
        if browser_debug_port <= 0 or browser_debug_port > 65535:
            raise ValueError("浏览器调试端口必须在 1 到 65535 之间。")
        browser_debug_host = self.browser_debug_host_var.get().strip() or "127.0.0.1"

        extra_headers = self._parse_json_object(self.extra_headers_text.get("1.0", "end").strip(), "额外请求头 JSON")
        extra_body = self._parse_json_object(self.extra_body_text.get("1.0", "end").strip(), "额外请求体 JSON")

        anthropic_version = self.anthropic_version_var.get().strip() or ANTHROPIC_VERSION_DEFAULT
        anthropic_beta = self.anthropic_beta_var.get().strip()
        anthropic_tool_type = self.anthropic_tool_type_var.get().strip()
        thinking_budget = int(self.thinking_budget_var.get().strip() or "2048")
        if thinking_budget <= 0:
            raise ValueError("thinking token 预算必须大于 0。")

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        session_root = ROOT / "sessions" / timestamp
        provider = ProviderConfig(
            provider_kind=provider_kind,
            base_url=base_url,
            api_key=api_key,
            model=model,
            extra_headers={str(key): str(value) for key, value in extra_headers.items()},
            extra_body=extra_body,
            anthropic_version=anthropic_version,
            anthropic_beta=anthropic_beta,
            anthropic_tool_type=anthropic_tool_type,
            enable_thinking=self.enable_thinking_var.get(),
            thinking_budget=thinking_budget,
        )
        session = SessionConfig(
            scale=scale,
            jpeg_quality=jpeg_quality,
            max_steps=max_steps,
            confirm_actions=self.confirm_var.get(),
            hide_window_while_running=self.hide_window_var.get(),
            official_enhanced=self.official_enhanced_var.get(),
            browser_dom_enabled=self.browser_dom_var.get(),
            browser_dom_first=self.browser_dom_first_var.get(),
            browser_debug_host=browser_debug_host,
            browser_debug_port=browser_debug_port,
            session_root=session_root,
        )
        return provider, session, task

    def _collect_session_config_for_diagnostics(self) -> SessionConfig:
        scale = float(self.scale_var.get().strip())
        if scale <= 0 or scale > 1:
            raise ValueError("截图缩放必须在 0 到 1 之间。")
        jpeg_quality = int(self.jpeg_quality_var.get().strip())
        if jpeg_quality < 40 or jpeg_quality > 95:
            raise ValueError("JPEG 质量必须在 40 到 95 之间。")
        browser_debug_port = int(self.browser_debug_port_var.get().strip() or "9222")
        if browser_debug_port <= 0 or browser_debug_port > 65535:
            raise ValueError("浏览器调试端口必须在 1 到 65535 之间。")
        return SessionConfig(
            scale=scale,
            jpeg_quality=jpeg_quality,
            browser_dom_enabled=self.browser_dom_var.get(),
            browser_dom_first=self.browser_dom_first_var.get(),
            browser_debug_host=self.browser_debug_host_var.get().strip() or "127.0.0.1",
            browser_debug_port=browser_debug_port,
        )

    @staticmethod
    def _parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} 必须是合法 JSON。") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} 必须是 JSON 对象。")
        return parsed

    def _drain_queue(self) -> None:
        while True:
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, ApprovalRequest):
                approved = self._show_approval_dialog(item.summary)
                item.approved = approved
                item.ready.set()
                self._append_log("确认", f"{item.summary} -> {'允许' if approved else '拒绝'}")
                continue
            self._consume_event(item)
        self.root.after(120, self._drain_queue)

    def _consume_event(self, event: AgentEvent) -> None:
        if event.kind == "snapshot" and event.snapshot_path:
            self._show_image(event.snapshot_path)

        if event.kind == "status":
            self._update_status(event.message, tone="working")
        elif event.kind == "finished":
            self._restore_window_if_hidden()
            self._update_status("已完成", tone="success")
            self.meta_var.set(event.message or "任务完成。")
            self._set_running(False)
            session_root = event.payload.get("session_root")
            if session_root:
                self.current_session_root = Path(session_root)
                self.open_session_button.configure(state="normal")
                self.session_hint.configure(text=f"会话目录：{self.current_session_root.name}")
            replay_path = event.payload.get("replay_path")
            if replay_path:
                self._append_log("系统", f"复盘文件：{replay_path}")
        elif event.kind == "error":
            self._restore_window_if_hidden()
            self._update_status("运行出错", tone="error")
            self._set_running(False)
            messagebox.showerror("运行出错", event.message, parent=self.root)
        elif event.kind == "warning":
            self.meta_var.set(event.message)
        elif event.kind == "diagnostic":
            self.meta_var.set(event.message)
        elif event.kind == "assistant":
            self.meta_var.set("模型已返回新判断")
            self._append_public_reasoning(
                event.message,
                derived=bool(event.payload.get("derived")),
                step=event.payload.get("step"),
                thought_seconds=event.payload.get("thought_seconds"),
            )
        elif event.kind == "analysis":
            self.meta_var.set("已生成本步过程摘要")
            self._set_analysis_text(event.message)
        elif event.kind == "snapshot" and event.snapshot_path:
            self.meta_var.set(f"最新截图：{event.snapshot_path.name}")

        self._append_log(self._prefix_text(event.kind), event.message)

    def _set_analysis_text(self, text: str) -> None:
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("1.0", text)
        self.analysis_text.configure(state="disabled")

    def _set_reasoning_placeholder(self, text: str) -> None:
        self.reasoning_text.configure(state="normal")
        self.reasoning_text.delete("1.0", "end")
        self.reasoning_text.insert("1.0", text, ("label",))
        self.reasoning_text.configure(state="disabled")

    def _clear_public_reasoning(self) -> None:
        self.reasoning_text.configure(state="normal")
        self.reasoning_text.delete("1.0", "end")
        self.reasoning_text.configure(state="disabled")

    def _append_public_reasoning(
        self,
        text: str,
        *,
        derived: bool = False,
        step: int | None = None,
        thought_seconds: float | None = None,
    ) -> None:
        content = (text or "").strip()
        if not content:
            return
        current = self.reasoning_text.get("1.0", "end").strip()
        if current.startswith("这里显示模型每一步原样公开说出来的话") or current.startswith("等待模型输出第一句公开思考"):
            self._clear_public_reasoning()
        tag = "派生说明" if derived else "公开思考"
        if step is None:
            header = "派生公开说明" if derived else "模型公开思考"
        else:
            if thought_seconds is None:
                timing = "思考中"
            else:
                timing = f"思考 {thought_seconds:.1f} 秒"
            prefix = "派生说明" if derived else "Thought"
            header = f"第 {step} 步 · {prefix} · {timing}"
        self.reasoning_text.configure(state="normal")
        self.reasoning_text.insert("end", f"{header}\n", ("title",))
        self.reasoning_text.insert("end", f"{content}\n\n", (tag,))
        self.reasoning_text.see("end")
        self.reasoning_text.configure(state="disabled")

    def _show_approval_dialog(self, summary: str) -> bool:
        self._restore_window_if_hidden()
        dialog = tk.Toplevel(self.root)
        dialog.title("操作确认")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(bg=BG)

        approved = {"value": False}
        card = tk.Frame(dialog, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, bd=0, padx=18, pady=18)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(card, text="即将执行以下操作", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        tk.Label(card, text="你开启了逐步确认，因此这一步需要你点一下。", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(4, 10))

        message = tk.Text(
            card,
            width=60,
            height=5,
            wrap="word",
            bg="#FFFDFC",
            fg=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            font=("Microsoft YaHei UI", 10),
            padx=10,
            pady=10,
        )
        message.pack(fill="both", expand=True)
        message.insert("1.0", summary)
        message.configure(state="disabled")

        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x", pady=(12, 0))

        def allow() -> None:
            approved["value"] = True
            dialog.destroy()

        def reject() -> None:
            approved["value"] = False
            dialog.destroy()

        ttk.Button(buttons, text="允许这次操作", command=allow, style="Accent.TButton").pack(side="left")
        ttk.Button(buttons, text="拒绝这次操作", command=reject, style="Soft.TButton").pack(side="left", padx=(8, 0))
        dialog.protocol("WM_DELETE_WINDOW", reject)
        dialog.update_idletasks()
        dialog.geometry(f"+{self.root.winfo_rootx() + 140}+{self.root.winfo_rooty() + 120}")
        self.root.wait_window(dialog)
        return approved["value"]

    def _show_image(self, path: Path) -> None:
        image = Image.open(path)
        max_width = max(520, self.preview_label.winfo_width() - 32)
        max_height = max(360, self.preview_label.winfo_height() - 32)
        image.thumbnail((max_width, max_height))
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_image, text="")

    def _append_log(self, prefix: str, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{prefix}] ", ("prefix", prefix))
        self.log_text.insert("end", f"{message}\n", (prefix,))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _prefix_text(kind: str) -> str:
        return {
            "snapshot": "截图",
            "status": "状态",
            "assistant": "模型",
            "analysis": "摘要",
            "tool": "执行",
            "warning": "警告",
            "finished": "完成",
            "error": "错误",
            "diagnostic": "诊断",
        }.get(kind, "系统")

    def _update_status(self, text: str, *, tone: str) -> None:
        self.status_var.set(text)
        if tone == "success":
            bg, fg = "#DDEEDF", SUCCESS
        elif tone == "warning":
            bg, fg = "#F2E4D4", WARNING
        elif tone == "error":
            bg, fg = "#F0DEDA", ERROR
        elif self.provider_kind_var.get() in {PROVIDER_ANTHROPIC_OFFICIAL, PROVIDER_OFFICIAL_COMPATIBLE}:
            bg, fg = OFFICIAL_SOFT, OFFICIAL
        else:
            bg, fg = ACCENT_SOFT, ACCENT_ACTIVE
        self.status_badge.configure(text=text, bg=bg, fg=fg)

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        if running:
            self._update_status("运行中", tone="working")

    @staticmethod
    def _mode_name(provider_kind: str) -> str:
        return {
            PROVIDER_ANTHROPIC_OFFICIAL: "Anthropic 官方",
            PROVIDER_OFFICIAL_COMPATIBLE: "官方体验兼容",
            PROVIDER_OPENAI_COMPATIBLE: "兼容中转站",
        }.get(provider_kind, "兼容中转站")

    def _load_settings(self) -> dict[str, Any]:
        if not SETTINGS_PATH.exists():
            return {}
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_settings(self, task: str) -> None:
        payload = {
            "provider_kind": self.provider_kind_var.get().strip(),
            "base_url": self.base_url_var.get().strip(),
            "model": self.model_var.get().strip(),
            "anthropic_version": self.anthropic_version_var.get().strip(),
            "anthropic_beta": self.anthropic_beta_var.get().strip(),
            "anthropic_tool_type": self.anthropic_tool_type_var.get().strip(),
            "official_enhanced": self.official_enhanced_var.get(),
            "enable_thinking": self.enable_thinking_var.get(),
            "thinking_budget": self.thinking_budget_var.get().strip(),
            "scale": self.scale_var.get().strip(),
            "jpeg_quality": self.jpeg_quality_var.get().strip(),
            "max_steps": self.max_steps_var.get().strip(),
            "confirm_actions": self.confirm_var.get(),
            "hide_window_while_running": self.hide_window_var.get(),
            "browser_dom_enabled": self.browser_dom_var.get(),
            "browser_dom_first": self.browser_dom_first_var.get(),
            "browser_debug_host": self.browser_debug_host_var.get().strip(),
            "browser_debug_port": self.browser_debug_port_var.get().strip(),
            "extra_headers_json": self.extra_headers_text.get("1.0", "end").strip() or "{}",
            "extra_body_json": self.extra_body_text.get("1.0", "end").strip() or "{}",
            "last_task": task,
        }
        SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def launch() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
