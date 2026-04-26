from __future__ import annotations

import base64
import ctypes
import io
import time
from pathlib import Path
from typing import Any, Iterable

from ctypes import wintypes

from PIL import Image, ImageChops, ImageDraw, ImageGrab, ImageStat

from .models import ActionResult, SessionConfig, Snapshot


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_int
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p
user32.OpenClipboard.argtypes = [ctypes.c_void_p]
user32.OpenClipboard.restype = ctypes.c_int
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.c_int
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.c_int
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.FindWindowW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
SW_RESTORE = 9
SW_SHOW = 5

SPECIAL_KEYS = {
    "alt": 0x12,
    "apps": 0x5D,
    "backspace": 0x08,
    "capslock": 0x14,
    "ctrl": 0x11,
    "control": 0x11,
    "delete": 0x2E,
    "del": 0x2E,
    "down": 0x28,
    "end": 0x23,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "home": 0x24,
    "insert": 0x2D,
    "left": 0x25,
    "menu": 0x12,
    "pagedown": 0x22,
    "pageup": 0x21,
    "pgdn": 0x22,
    "pgup": 0x21,
    "right": 0x27,
    "shift": 0x10,
    "space": 0x20,
    "tab": 0x09,
    "up": 0x26,
    "win": 0x5B,
    "windows": 0x5B,
}
for index in range(1, 13):
    SPECIAL_KEYS[f"f{index}"] = 0x6F + index

SUPPORTED_COMPUTER_ACTIONS = {
    "screenshot",
    "mouse_move",
    "left_click",
    "double_click",
    "right_click",
    "middle_click",
    "left_click_drag",
    "type",
    "key",
    "scroll",
    "wait",
    "activate_window",
}


def _set_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class WindowsDesktopController:
    def __init__(self, settings: SessionConfig) -> None:
        _set_dpi_awareness()
        self.settings = settings
        self.session_root = settings.session_root or Path.cwd() / "sessions" / time.strftime("%Y%m%d-%H%M%S")
        self.session_root.mkdir(parents=True, exist_ok=True)
        self._snapshot_index = 0
        self._last_masked_regions_actual: list[tuple[int, int, int, int]] = []
        self._last_masked_regions_capture: list[tuple[int, int, int, int]] = []
        self.actual_width = int(user32.GetSystemMetrics(0))
        self.actual_height = int(user32.GetSystemMetrics(1))
        self.capture_width = max(1, int(round(self.actual_width * self.settings.scale)))
        self.capture_height = max(1, int(round(self.actual_height * self.settings.scale)))

    def capture_snapshot(self, label: str = "snapshot") -> Snapshot:
        image = ImageGrab.grab()
        actual_width, actual_height = image.size
        self.actual_width = actual_width
        self.actual_height = actual_height
        foreground_window_title = self.get_foreground_window_title()
        visible_window_titles = self.list_visible_window_titles()
        self._last_masked_regions_actual = []
        if self.settings.mask_own_window:
            masked_rect = self._mask_own_window(image)
            if masked_rect is not None:
                self._last_masked_regions_actual = [masked_rect]
        self.capture_width = max(1, int(round(actual_width * self.settings.scale)))
        self.capture_height = max(1, int(round(actual_height * self.settings.scale)))
        self._last_masked_regions_capture = []
        for rect in self._last_masked_regions_actual:
            capture_rect = self._capture_rect_from_actual(rect)
            if capture_rect is not None:
                self._last_masked_regions_capture.append(capture_rect)
        if self.settings.scale != 1.0:
            image = image.resize((self.capture_width, self.capture_height))

        self._snapshot_index += 1
        path = self.session_root / f"{self._snapshot_index:03d}_{label}.jpg"
        buffer = io.BytesIO()
        image.convert("RGB").save(path, format="JPEG", quality=self.settings.jpeg_quality, optimize=True)
        image.convert("RGB").save(buffer, format="JPEG", quality=self.settings.jpeg_quality, optimize=True)
        return Snapshot(
            path=path,
            data_url=f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}",
            width=image.size[0],
            height=image.size[1],
            actual_width=actual_width,
            actual_height=actual_height,
            foreground_window_title=foreground_window_title,
            visible_window_titles=visible_window_titles,
        )

    def execute(self, arguments: dict[str, Any]) -> ActionResult:
        action = str(arguments.get("action") or "").strip().lower()
        modifiers = self._normalize_keys(arguments.get("modifiers"))
        self._press_down(modifiers)
        try:
            message = self._perform(action, arguments)
        finally:
            self._release(modifiers)
        time.sleep(self._post_action_delay(action, arguments))
        snapshot = self.capture_snapshot(action or "action")
        return ActionResult(message=message, snapshot=snapshot)

    def is_action_targeting_masked_region(self, arguments: dict[str, Any]) -> bool:
        action = str(arguments.get("action") or "").strip().lower()
        if action in {"left_click", "double_click", "right_click", "middle_click", "mouse_move", "scroll"}:
            coordinate = self._optional_coordinate(arguments.get("coordinate"))
            if coordinate != (None, None):
                return self._coordinate_in_masked_region(*coordinate)
        if action in {"left_click_drag", "drag"}:
            start = self._optional_coordinate(arguments.get("start_coordinate"))
            end = self._optional_coordinate(arguments.get("end_coordinate"))
            start_blocked = start != (None, None) and self._coordinate_in_masked_region(*start)
            end_blocked = end != (None, None) and self._coordinate_in_masked_region(*end)
            return start_blocked or end_blocked
        return False

    def is_supported_action(self, arguments: dict[str, Any]) -> bool:
        action = str(arguments.get("action") or "").strip().lower()
        return action in SUPPORTED_COMPUTER_ACTIONS

    def has_out_of_bounds_coordinate(self, arguments: dict[str, Any]) -> bool:
        return bool(self._out_of_bounds_points(arguments))

    def coordinate_bounds_message(self, arguments: dict[str, Any]) -> str:
        points = self._out_of_bounds_points(arguments)
        if not points:
            return ""
        point_text = "；".join(f"{name}={coordinate}" for name, coordinate in points)
        return (
            f"模型给出的坐标超出当前截图范围 {self.capture_width}x{self.capture_height}：{point_text}。"
            "本工具不会把越界坐标静默夹到屏幕边缘，以免误点。"
            "请只使用最新截图内的坐标重新选择动作。"
        )

    def unsupported_action_message(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action") or "").strip()
        supported = "、".join(sorted(SUPPORTED_COMPUTER_ACTIONS))
        if action:
            return f"当前不支持的 computer 操作是“{action}”。请改用以下基础动作之一：{supported}。"
        return f"你返回的 computer 动作缺少 action 字段。请改用以下基础动作之一：{supported}。"

    def masked_region_message(self, arguments: dict[str, Any]) -> str:
        return (
            f"你选择的操作目标位于“{self.settings.own_window_title}”窗口的遮挡区域内。"
            "该区域当前不可见，不能假设后方有什么页面或控件。"
            "请基于最新截图重新选择一个在可见区域内的动作。"
        )

    def requires_foreground_app(self, arguments: dict[str, Any]) -> bool:
        action = str(arguments.get("action") or "").strip().lower()
        if action == "type":
            return True
        if action == "key":
            keys = self._normalize_keys(arguments.get("keys"))
            if not keys:
                return False
            blocked = {"enter", "tab", "space", "backspace", "delete"}
            return any(token in blocked for token in keys)
        return False

    def is_own_window_foreground(self) -> bool:
        return self._titles_match(self.get_foreground_window_title(), self.settings.own_window_title)

    def is_foreground_safe_for_action(self, arguments: dict[str, Any]) -> bool:
        if not self.requires_foreground_app(arguments):
            return True
        current_title = self.get_foreground_window_title()
        if self._titles_match(current_title, self.settings.own_window_title):
            return False
        expected_title = self._expected_window_title(arguments)
        if expected_title and not self._title_contains(current_title, expected_title):
            return False
        return True

    def ensure_expected_window_foreground(self, arguments: dict[str, Any]) -> str:
        if not self.requires_foreground_app(arguments):
            return ""
        expected_title = self._expected_window_title(arguments)
        if not expected_title:
            return ""
        current_title = self.get_foreground_window_title()
        if self._title_contains(current_title, expected_title) and not self._titles_match(current_title, self.settings.own_window_title):
            return ""
        return self.activate_window_by_title(expected_title)

    def foreground_guard_message(self, arguments: dict[str, Any]) -> str:
        current_title = self.get_foreground_window_title() or "未知窗口"
        action_label = self.describe(arguments)
        expected_title = self._expected_window_title(arguments)
        if self._titles_match(current_title, self.settings.own_window_title):
            return (
                f"当前前台窗口仍然是“{current_title}”，这是代理工具自己的窗口。"
                f"因此不能继续执行“{action_label}”这种输入类动作。"
                "请先用 activate_window 激活真正的目标窗口，或基于最新截图选择可见区域内的动作。"
            )
        if expected_title:
            return (
                f"模型声明该动作应在“{expected_title}”里执行，但当前前台窗口是“{current_title}”。"
                f"为避免把“{action_label}”输入到错误窗口，本次操作已被拦截。"
                "请先用 activate_window 激活目标窗口，再根据最新截图重新决策。"
            )
        return (
            f"当前前台窗口是“{current_title}”，目标应用还没有被可靠确认。"
            f"因此不能继续执行“{action_label}”这种输入类动作。"
            "请先把真正的目标窗口切到前台，再根据最新截图重新决策。"
        )

    def describe(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action") or "").strip().lower()
        coordinate = arguments.get("coordinate")
        start_coordinate = arguments.get("start_coordinate")
        end_coordinate = arguments.get("end_coordinate")
        if action in {"left_click", "double_click", "right_click", "middle_click", "mouse_move"} and coordinate:
            action_name = {
                "left_click": "左键单击",
                "double_click": "左键双击",
                "right_click": "右键单击",
                "middle_click": "中键单击",
                "mouse_move": "移动鼠标",
            }.get(action, action)
            return f"{action_name} @ {coordinate}"
        if action == "left_click_drag" and start_coordinate and end_coordinate:
            return f"左键拖拽 {start_coordinate} -> {end_coordinate}"
        if action == "type":
            text = str(arguments.get("text") or "")
            suffix = "..." if len(text) > 80 else ""
            return f"输入文本 \"{text[:80]}{suffix}\""
        if action == "key":
            return f"按键 {arguments.get('keys')}"
        if action == "scroll":
            return f"滚轮 amount={arguments.get('scroll_amount')} @ {coordinate}"
        if action == "wait":
            delay = arguments.get("seconds") if arguments.get("seconds") is not None else arguments.get("duration_ms")
            unit = "秒" if arguments.get("seconds") is not None else "毫秒"
            return f"等待 {delay}{unit}"
        if action == "activate_window":
            return f"激活窗口 “{arguments.get('window_title') or arguments.get('title') or ''}”"
        return action or "未知操作"

    def _perform(self, action: str, arguments: dict[str, Any]) -> str:
        if action == "screenshot":
            return "已捕获最新截图。"
        if action == "mouse_move":
            x, y = self._require_coordinate(arguments.get("coordinate"))
            self._move(x, y)
            return f"已将鼠标移动到截图坐标 ({x}, {y})。"
        if action == "left_click":
            x, y = self._require_coordinate(arguments.get("coordinate"))
            self._click(x, y, times=1, button="left")
            return f"已在 ({x}, {y}) 左键单击。"
        if action == "double_click":
            x, y = self._require_coordinate(arguments.get("coordinate"))
            self._click(x, y, times=2, button="left")
            return f"已在 ({x}, {y}) 左键双击。"
        if action == "right_click":
            x, y = self._require_coordinate(arguments.get("coordinate"))
            self._click(x, y, times=1, button="right")
            return f"已在 ({x}, {y}) 右键单击。"
        if action == "middle_click":
            x, y = self._require_coordinate(arguments.get("coordinate"))
            self._click(x, y, times=1, button="middle")
            return f"已在 ({x}, {y}) 中键单击。"
        if action in {"left_click_drag", "drag"}:
            start_x, start_y = self._require_coordinate(arguments.get("start_coordinate"))
            end_x, end_y = self._require_coordinate(arguments.get("end_coordinate"))
            self._drag(start_x, start_y, end_x, end_y)
            return f"已从 ({start_x}, {start_y}) 拖拽到 ({end_x}, {end_y})。"
        if action == "type":
            text = str(arguments.get("text") or "")
            if not text:
                raise ValueError("type 操作需要提供 text。")
            self._paste_text(text)
            return f"已输入 {len(text)} 个字符。"
        if action == "key":
            keys = self._normalize_keys(arguments.get("keys"))
            if not keys:
                raise ValueError("key 操作需要提供 keys。")
            self._hotkey(keys)
            return f"已按下按键：{keys}。"
        if action == "scroll":
            amount = int(arguments.get("scroll_amount") or 0)
            x, y = self._optional_coordinate(arguments.get("coordinate"))
            self._scroll(amount, x, y)
            return f"已滚动 {amount} 格。"
        if action == "wait":
            seconds = self._seconds(arguments)
            time.sleep(seconds)
            return f"已等待 {seconds:.2f} 秒。"
        if action == "activate_window":
            window_title = str(arguments.get("window_title") or arguments.get("title") or "").strip()
            if not window_title:
                raise ValueError("activate_window 操作需要提供 window_title。")
            return self.activate_window_by_title(window_title)
        raise ValueError(f"不支持的 computer 操作：{action}")

    def activate_window_by_title(self, window_title: str) -> str:
        query = window_title.strip()
        if not query:
            raise ValueError("窗口标题不能为空。")
        match = self._find_window_by_title(query)
        if match is None:
            current_title = self.get_foreground_window_title() or "未知窗口"
            return f"没有找到标题包含“{query}”的可见窗口。当前前台窗口：{current_title}。"

        hwnd, matched_title = match
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.25)
        current_title = self.get_foreground_window_title() or "未知窗口"
        if self._title_contains(current_title, query) or self._titles_match(current_title, matched_title):
            return f"已激活窗口“{current_title}”。"
        return f"已尝试激活窗口“{matched_title}”，但当前前台窗口是“{current_title}”。请根据最新截图确认。"

    def list_visible_window_titles(self, *, limit: int = 12) -> list[str]:
        titles: list[str] = []
        seen: set[str] = set()
        for _hwnd, title in self._visible_windows():
            if self._titles_match(title, self.settings.own_window_title):
                continue
            normalized = title.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            titles.append(title)
            if len(titles) >= limit:
                break
        return titles

    @staticmethod
    def describe_snapshot_change(before: Snapshot, after: Snapshot) -> str:
        score = WindowsDesktopController._snapshot_difference_score(before.path, after.path)
        if score is None:
            return "截图变化：无法比较。"
        if score < 1.0:
            return "截图变化：几乎没有变化，上一动作可能没有产生可见效果。"
        if score < 4.0:
            return "截图变化：变化很小，请仔细确认上一动作是否真正生效。"
        if score < 12.0:
            return "截图变化：有轻微变化。"
        return "截图变化：明显变化。"

    def _mask_own_window(self, image) -> tuple[int, int, int, int] | None:
        title = (self.settings.own_window_title or "").strip()
        if not title:
            return None
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return None
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        clipped = self._clip_rect(rect.left, rect.top, rect.right, rect.bottom, image.size[0], image.size[1])
        if clipped is None:
            return None
        left, top, right, bottom = clipped
        draw = ImageDraw.Draw(image)
        draw.rectangle((left, top, right, bottom), fill=(236, 231, 223), outline=(176, 162, 148), width=2)
        pad = 18
        inner_left = min(right - 8, left + pad)
        inner_top = min(bottom - 8, top + pad)
        inner_right = max(inner_left + 20, right - pad)
        inner_bottom = max(inner_top + 20, bottom - pad)
        draw.rectangle((inner_left, inner_top, inner_right, inner_bottom), outline=(196, 182, 168), width=1)
        return clipped

    def _move(self, x: int, y: int) -> None:
        rx, ry = self.to_real_coordinate(x, y)
        user32.SetCursorPos(rx, ry)

    def _click(self, x: int, y: int, *, times: int, button: str) -> None:
        self._move(x, y)
        down_flag, up_flag = {
            "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }[button]
        for _ in range(times):
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            time.sleep(0.08)

    def _drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        start_rx, start_ry = self.to_real_coordinate(start_x, start_y)
        end_rx, end_ry = self.to_real_coordinate(end_x, end_y)
        user32.SetCursorPos(start_rx, start_ry)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.06)
        steps = 12
        for index in range(1, steps + 1):
            x = int(start_rx + (end_rx - start_rx) * index / steps)
            y = int(start_ry + (end_ry - start_ry) * index / steps)
            user32.SetCursorPos(x, y)
            time.sleep(0.01)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def _scroll(self, amount: int, x: int | None, y: int | None) -> None:
        if x is not None and y is not None:
            self._move(x, y)
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(amount) * WHEEL_DELTA, 0)

    def _hotkey(self, keys: list[str]) -> None:
        self._press_down(keys)
        self._release(keys)

    def _paste_text(self, text: str) -> None:
        self._set_clipboard_text(text)
        self._hotkey(["ctrl", "v"])

    def _press_down(self, keys: Iterable[str]) -> None:
        for token in keys:
            vk = self._vk_code(token)
            user32.keybd_event(vk, user32.MapVirtualKeyW(vk, 0), 0, 0)
            time.sleep(0.01)

    def _release(self, keys: Iterable[str]) -> None:
        for token in reversed(list(keys)):
            vk = self._vk_code(token)
            user32.keybd_event(vk, user32.MapVirtualKeyW(vk, 0), KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)

    def to_real_coordinate(self, x: int, y: int) -> tuple[int, int]:
        return (
            self.translate_coordinate(x, capture_size=self.capture_width, actual_size=self.actual_width),
            self.translate_coordinate(y, capture_size=self.capture_height, actual_size=self.actual_height),
        )

    @staticmethod
    def get_foreground_window_title() -> str:
        hwnd = user32.GetForegroundWindow()
        return WindowsDesktopController._window_title(hwnd)

    def _find_window_by_title(self, query: str) -> tuple[int, str] | None:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            return None
        for hwnd, title in self._visible_windows():
            if self._titles_match(title, self.settings.own_window_title):
                continue
            if normalized_query in title.casefold():
                return hwnd, title
        return None

    @staticmethod
    def _visible_windows() -> list[tuple[int, str]]:
        windows: list[tuple[int, str]] = []

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = WindowsDesktopController._window_title(hwnd)
            if title:
                windows.append((hwnd, title))
            return True

        enum_proc = EnumWindowsProc(callback)
        user32.EnumWindows(enum_proc, 0)
        return windows

    @staticmethod
    def _window_title(hwnd: int) -> str:
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()

    @staticmethod
    def translate_coordinate(value: int, *, capture_size: int, actual_size: int) -> int:
        if capture_size <= 0:
            raise ValueError("capture_size must be positive.")
        clamped = max(0, min(int(value), capture_size - 1))
        return int(round((clamped / max(1, capture_size - 1)) * max(1, actual_size - 1)))

    @staticmethod
    def to_capture_coordinate(value: int, *, actual_size: int, capture_size: int) -> int:
        if actual_size <= 0:
            raise ValueError("actual_size must be positive.")
        clamped = max(0, min(int(value), actual_size - 1))
        return int(round((clamped / max(1, actual_size - 1)) * max(1, capture_size - 1)))

    @staticmethod
    def _clip_rect(left: int, top: int, right: int, bottom: int, width: int, height: int) -> tuple[int, int, int, int] | None:
        clipped_left = max(0, min(left, width))
        clipped_top = max(0, min(top, height))
        clipped_right = max(0, min(right, width))
        clipped_bottom = max(0, min(bottom, height))
        if clipped_right - clipped_left < 4 or clipped_bottom - clipped_top < 4:
            return None
        return clipped_left, clipped_top, clipped_right, clipped_bottom

    def _capture_rect_from_actual(self, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
        left, top, right, bottom = rect
        clipped = self._clip_rect(left, top, right, bottom, self.actual_width, self.actual_height)
        if clipped is None:
            return None
        clipped_left, clipped_top, clipped_right, clipped_bottom = clipped
        capture_left = self.to_capture_coordinate(clipped_left, actual_size=self.actual_width, capture_size=self.capture_width)
        capture_top = self.to_capture_coordinate(clipped_top, actual_size=self.actual_height, capture_size=self.capture_height)
        capture_right = self.to_capture_coordinate(max(clipped_left + 1, clipped_right - 1), actual_size=self.actual_width, capture_size=self.capture_width)
        capture_bottom = self.to_capture_coordinate(max(clipped_top + 1, clipped_bottom - 1), actual_size=self.actual_height, capture_size=self.capture_height)
        return capture_left, capture_top, capture_right, capture_bottom

    def _coordinate_in_masked_region(self, x: int | None, y: int | None) -> bool:
        if x is None or y is None:
            return False
        for left, top, right, bottom in self._last_masked_regions_capture:
            if left <= int(x) <= right and top <= int(y) <= bottom:
                return True
        return False

    def _out_of_bounds_points(self, arguments: dict[str, Any]) -> list[tuple[str, tuple[int, int]]]:
        action = str(arguments.get("action") or "").strip().lower()
        fields: tuple[str, ...]
        if action in {"left_click", "double_click", "right_click", "middle_click", "mouse_move", "scroll"}:
            fields = ("coordinate",)
        elif action in {"left_click_drag", "drag"}:
            fields = ("start_coordinate", "end_coordinate")
        else:
            fields = ()
        points: list[tuple[str, tuple[int, int]]] = []
        for field in fields:
            x, y = self._optional_coordinate(arguments.get(field))
            if x is None or y is None:
                continue
            if not self._coordinate_in_capture_bounds(x, y):
                points.append((field, (int(x), int(y))))
        return points

    def _coordinate_in_capture_bounds(self, x: int, y: int) -> bool:
        return 0 <= int(x) < self.capture_width and 0 <= int(y) < self.capture_height

    @staticmethod
    def _titles_match(left: str, right: str) -> bool:
        return (left or "").strip().casefold() == (right or "").strip().casefold()

    @staticmethod
    def _title_contains(title: str, query: str) -> bool:
        normalized_title = (title or "").strip().casefold()
        normalized_query = (query or "").strip().casefold()
        return bool(normalized_title and normalized_query and normalized_query in normalized_title)

    @staticmethod
    def _expected_window_title(arguments: dict[str, Any]) -> str:
        return str(arguments.get("expected_window_title") or arguments.get("target_window_title") or "").strip()

    @staticmethod
    def _snapshot_difference_score(before_path: Path, after_path: Path) -> float | None:
        try:
            with Image.open(before_path) as before_image, Image.open(after_path) as after_image:
                before_small = before_image.convert("L").resize((96, 54))
                after_small = after_image.convert("L").resize((96, 54))
                diff = ImageChops.difference(before_small, after_small)
                mean = ImageStat.Stat(diff).mean[0]
                return float(mean)
        except Exception:
            return None

    @staticmethod
    def _seconds(arguments: dict[str, Any]) -> float:
        if arguments.get("seconds") is not None:
            return max(0.0, float(arguments["seconds"]))
        if arguments.get("duration_ms") is not None:
            return max(0.0, float(arguments["duration_ms"]) / 1000.0)
        return 1.0

    @staticmethod
    def _post_action_delay(action: str, arguments: dict[str, Any]) -> float:
        if action == "wait":
            return 0.0
        if action == "activate_window":
            return 0.35
        if action == "key":
            keys = WindowsDesktopController._normalize_keys(arguments.get("keys"))
            if any(key in {"enter", "return"} for key in keys):
                return 0.8
            if any(key in {"tab", "space"} for key in keys):
                return 0.35
        if action in {"left_click", "double_click", "right_click", "middle_click"}:
            return 0.35
        if action == "type":
            return 0.25
        return 0.2

    @staticmethod
    def _normalize_keys(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [chunk.strip().lower() for chunk in raw.split("+") if chunk.strip()]
        if isinstance(raw, list):
            return [str(item).strip().lower() for item in raw if str(item).strip()]
        return []

    @staticmethod
    def _require_coordinate(raw: Any) -> tuple[int, int]:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValueError("Expected a coordinate [x, y].")
        return int(raw[0]), int(raw[1])

    @staticmethod
    def _optional_coordinate(raw: Any) -> tuple[int | None, int | None]:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            return None, None
        return int(raw[0]), int(raw[1])

    @staticmethod
    def _vk_code(token: str) -> int:
        token = token.strip().lower()
        if token in SPECIAL_KEYS:
            return SPECIAL_KEYS[token]
        if len(token) == 1:
            if token.isalnum():
                return ord(token.upper())
            code = user32.VkKeyScanW(ord(token))
            return int(code & 0xFF)
        raise ValueError(f"Unsupported key token: {token}")

    @staticmethod
    def _set_clipboard_text(text: str) -> None:
        payload = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not handle:
            raise ctypes.WinError()
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            raise ctypes.WinError()
        ctypes.memmove(locked, payload, len(payload))
        kernel32.GlobalUnlock(handle)
        opened = False
        for _ in range(8):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.05)
        if not opened:
            kernel32.GlobalFree(handle)
            raise ctypes.WinError()
        keep_handle = True
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                raise ctypes.WinError()
            keep_handle = False
        finally:
            user32.CloseClipboard()
            if keep_handle:
                kernel32.GlobalFree(handle)
