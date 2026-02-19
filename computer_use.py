"""
Claude Computer Use - 本地 Windows 控制脚本
通过 OpenRouter API 调用 Claude，使用标准函数工具实现 AI 操控本地电脑。

使用方法：
    python computer_use.py
    python computer_use.py --task "打开记事本写一首诗"
    python computer_use.py --confirm   # 每步操作前确认

环境变量：
    ANTHROPIC_API_KEY  - OpenRouter 的 API Key
    ANTHROPIC_BASE_URL - API 地址（默认 https://openrouter.ai/api）
"""

import httpx
import pyautogui
import pyperclip
import base64
import ctypes
import io
import json
import os
import sys
import time
import argparse
from PIL import ImageGrab

# ══════════════════════════════════════════════════════════════
#  配置
# ══════════════════════════════════════════════════════════════
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
OPENROUTER_KEY = "你的API（只要是支持function calling的中转站都可以）"
API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "") or OPENROUTER_KEY
MODEL    = "anthropic/claude-sonnet-4.6"

# 截图缩放比例，越小越省 token（0.5 = 缩小到一半）
SCALE = 0.75

# JPEG 压缩质量（1-100），越低体积越小但画质越差，60 是较好平衡点
JPEG_QUALITY = 60

# API 请求超时（秒）
API_TIMEOUT = 180

# 请求失败重试次数
MAX_RETRIES = 3

# 最大迭代次数，防止无限循环烧钱
MAX_ITERATIONS = 30

# 是否每步操作前要求确认
CONFIRM_MODE = False

# 调试模式：是否保存每一步的截图到本地
DEBUG = True

# ══════════════════════════════════════════════════════════════
#  Windows DPI 感知（确保高分屏下坐标正确）
# ══════════════════════════════════════════════════════════════
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  初始化 PyAutoGUI
# ══════════════════════════════════════════════════════════════
pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.1

SW, SH = pyautogui.size()
DW, DH = int(SW * SCALE), int(SH * SCALE)

# ══════════════════════════════════════════════════════════════
#  系统提示词
# ══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""你正在通过工具控制一台 Windows 电脑。

屏幕信息：
- 真实分辨率: {SW}x{SH}
- 截图分辨率: {DW}x{DH}（缩放比例: {SCALE}）
- 你返回的坐标应该基于截图分辨率 ({DW}x{DH})

操作系统注意事项：
- 这是 Windows 系统，使用 Windows 风格的路径（如 C:\\Users\\...）
- 使用 Windows 快捷键（如 Win+E 打开资源管理器，Win+R 运行命令）
- 开始菜单和任务栏在屏幕底部

重要操作技巧（必须遵守）：
- 打开程序时，优先使用 Win 键 → 输入程序名 → 回车。不要在任务栏上找图标，任务栏图标太小可能看不清。
- 打开网址时，优先用 Win+R → 输入网址 → 回车，或者先用上述方法打开浏览器再操作地址栏。
- 不要连续多次调用 screenshot，一次截图后就应该分析内容并执行操作。
- 每次操作后会自动返回截图，无需手动再次截图。
- 如果某个操作失败了，换一种方法重试，不要反复用同样的方法。

工作流程：
1. 每次回复你都会收到最新截图
2. 分析屏幕内容，规划操作步骤
3. 一次只调用一个工具，等待结果后再决定下一步
4. 需要点击某个位置时，先看截图确定坐标，坐标是基于{DW}x{DH}的截图
5. 完成任务后说明完成

可用工具：
- screenshot: 截取当前屏幕
- click: 点击指定坐标（支持左键、右键、双击）
- type_text: 在当前位置输入文字
- press_key: 按下键盘按键（支持组合键如 ctrl+c）
- scroll: 滚动鼠标滚轮
- mouse_move: 移动鼠标到指定位置
- drag: 从一个位置拖拽到另一个位置
- wait: 等待指定秒数"""

# ══════════════════════════════════════════════════════════════
#  标准函数工具定义（OpenAI 格式）
# ══════════════════════════════════════════════════════════════
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "截取当前屏幕截图。每次操作后自动截图，你也可以主动调用来查看当前屏幕状态。",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": f"点击屏幕指定坐标。坐标基于 {DW}x{DH} 截图分辨率。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": f"X坐标 (0-{DW})"},
                    "y": {"type": "integer", "description": f"Y坐标 (0-{DH})"},
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "鼠标按键，默认 left"
                    },
                    "clicks": {
                        "type": "integer",
                        "description": "点击次数，1=单击，2=双击，3=三击，默认1"
                    }
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "在当前光标位置输入文字（支持中英文）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文字"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "按下键盘按键。支持单键（如 enter, tab, esc）和组合键（如 ctrl+c, alt+f4, win+e）。用+号连接多个键。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "string", "description": "按键名称，组合键用+连接，如 ctrl+a, ctrl+shift+s, win+r, alt+tab, enter, esc, f5"}
                },
                "required": ["keys"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "在指定位置滚动鼠标滚轮。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X坐标"},
                    "y": {"type": "integer", "description": "Y坐标"},
                    "direction": {"type": "string", "enum": ["up", "down"], "description": "滚动方向"},
                    "amount": {"type": "integer", "description": "滚动量，默认3"}
                },
                "required": ["x", "y", "direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_move",
            "description": f"移动鼠标到指定坐标（不点击）。坐标基于 {DW}x{DH} 截图。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X坐标"},
                    "y": {"type": "integer", "description": "Y坐标"}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "drag",
            "description": "从起点拖拽到终点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_x": {"type": "integer", "description": "起点X"},
                    "start_y": {"type": "integer", "description": "起点Y"},
                    "end_x":   {"type": "integer", "description": "终点X"},
                    "end_y":   {"type": "integer", "description": "终点Y"}
                },
                "required": ["start_x", "start_y", "end_x", "end_y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "等待指定秒数（用于等待加载等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number", "description": "等待秒数，默认2"}
                },
                "required": []
            }
        }
    },
]

# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def take_screenshot() -> str:
    """截取当前屏幕，缩放后转为 base64 JPEG"""
    img = ImageGrab.grab()
    img = img.resize((DW, DH))
    buf = io.BytesIO()
    img = img.convert("RGB")
    
    if DEBUG:
        # 调试模式保存截图到指定文件夹
        script_dir = os.path.dirname(os.path.abspath(__file__))
        debug_dir = os.path.join(script_dir, "截图保存路径")
        os.makedirs(debug_dir, exist_ok=True)
        debug_filename = os.path.join(debug_dir, f"debug_step_{int(time.time())}.jpg")
        img.save(debug_filename, quality=80)
        print(f"    💾 [Debug] 截图已保存: {debug_filename}")

    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    size_kb = len(buf.getvalue()) / 1024
    print(f"    📦 截图大小: {size_kb:.0f} KB")
    return base64.standard_b64encode(buf.getvalue()).decode()


def scale_to_real(x, y):
    """将截图坐标转换为真实屏幕坐标"""
    return int(x / SCALE), int(y / SCALE)


def log_action(action: str, detail: str = ""):
    prefix = {"screenshot": "  📸 ", "click": "  🖱️ ", "type_text": "  ⌨️ ",
              "press_key": "  ⌨️ ", "scroll": "  🔄 ", "mouse_move": "  🖱️ ",
              "drag": "  🖱️ ", "wait": "  ⏳ "}.get(action, "  🔧 ")
    print(f"{prefix}{action} {detail}")


def confirm_action(action: str, detail: str) -> bool:
    if not CONFIRM_MODE or action == "screenshot":
        return True
    resp = input(f"  ⚠️  即将执行 [{action}] {detail}，继续？(Y/n): ").strip().lower()
    return resp in ("", "y", "yes")


def execute_tool(name: str, args: dict) -> str:
    """执行工具调用，返回截图的 base64"""
    if name == "screenshot":
        log_action("screenshot")
        return take_screenshot()

    elif name == "click":
        x, y = args["x"], args["y"]
        rx, ry = scale_to_real(x, y)
        button = args.get("button", "left")
        clicks = args.get("clicks", 1)
        detail = f"({x},{y})→真实({rx},{ry}) {button} x{clicks}"
        log_action("click", detail)
        if not confirm_action("click", detail):
            return take_screenshot()
        if button == "right":
            pyautogui.rightClick(rx, ry)
        elif button == "middle":
            pyautogui.middleClick(rx, ry)
        else:
            pyautogui.click(rx, ry, clicks=clicks)

    elif name == "type_text":
        text = args["text"]
        detail = f'"{text[:50]}{"..." if len(text) > 50 else ""}"'
        log_action("type_text", detail)
        if not confirm_action("type_text", detail):
            return take_screenshot()
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")

    elif name == "press_key":
        keys_raw = args["keys"]
        keys = [k.strip().lower() for k in keys_raw.split("+")]
        # 常用按键映射
        key_map = {"return": "enter", "backspace": "backspace", "delete": "delete",
                   "escape": "esc", "space": "space", "super": "win", "windows": "win",
                   "capslock": "capslock", "pageup": "pageup", "pagedown": "pagedown",
                   "printscreen": "printscreen"}
        keys = [key_map.get(k, k) for k in keys]
        detail = f'[{" + ".join(keys)}]'
        log_action("press_key", detail)
        if not confirm_action("press_key", detail):
            return take_screenshot()
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)

    elif name == "scroll":
        x, y = args.get("x", DW//2), args.get("y", DH//2)
        rx, ry = scale_to_real(x, y)
        direction = args.get("direction", "down")
        amount = args.get("amount", 3)
        detail = f"{direction} x{amount} at ({x},{y})"
        log_action("scroll", detail)
        if not confirm_action("scroll", detail):
            return take_screenshot()
        dy = amount if direction == "up" else -amount
        pyautogui.scroll(dy, x=rx, y=ry)

    elif name == "mouse_move":
        x, y = args["x"], args["y"]
        rx, ry = scale_to_real(x, y)
        detail = f"({x},{y})→真实({rx},{ry})"
        log_action("mouse_move", detail)
        if not confirm_action("mouse_move", detail):
            return take_screenshot()
        pyautogui.moveTo(rx, ry, duration=0.2)

    elif name == "drag":
        sx, sy = args["start_x"], args["start_y"]
        ex, ey = args["end_x"], args["end_y"]
        rsx, rsy = scale_to_real(sx, sy)
        rex, rey = scale_to_real(ex, ey)
        detail = f"({sx},{sy})→({ex},{ey})"
        log_action("drag", detail)
        if not confirm_action("drag", detail):
            return take_screenshot()
        pyautogui.mouseDown(rsx, rsy)
        time.sleep(0.1)
        pyautogui.moveTo(rex, rey, duration=0.3)
        pyautogui.mouseUp()

    elif name == "wait":
        seconds = args.get("seconds", 2)
        log_action("wait", f"{seconds}s")
        time.sleep(seconds)

    else:
        log_action("unknown", f"未知工具: {name}")

    time.sleep(0.4)
    return take_screenshot()


# ══════════════════════════════════════════════════════════════
#  主循环
# ══════════════════════════════════════════════════════════════

def run(task: str):
    """执行 Computer Use 任务的主循环（使用 OpenAI 兼容 API）"""

    http_client = httpx.Client(timeout=httpx.Timeout(API_TIMEOUT, connect=30.0))

    api_url = f"{BASE_URL}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "HTTP-Referer": "https://github.com/anthropics/anthropic-quickstarts",
        "X-Title": "Claude Computer Use Local Script",
    }

    # 截取初始屏幕截图
    print("📸 正在截取初始屏幕截图...")
    initial_screenshot = take_screenshot()

    # 构建初始消息
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": task},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{initial_screenshot}",
                    },
                },
            ],
        },
    ]

    print(f"\n{'═' * 60}")
    print(f"  🤖 Claude Computer Use (标准工具模式)")
    print(f"  📺 屏幕: {SW}x{SH} → 缩放: {DW}x{DH} (×{SCALE})")
    print(f"  🌐 API: {api_url}")
    print(f"  🧠 模型: {MODEL}")
    print(f"  🔄 最大迭代: {MAX_ITERATIONS}")
    print(f"  📝 任务: {task}")
    print(f"{'═' * 60}\n")

    iteration = 0
    while iteration < MAX_ITERATIONS:
        iteration += 1
        print(f"── 迭代 {iteration}/{MAX_ITERATIONS} ──")

        # 构建请求体
        payload = {
            "model": MODEL,
            "max_tokens": 4096,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
        }

        # 带重试的 API 请求
        resp_json = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"  📡 正在请求 API... (尝试 {attempt}/{MAX_RETRIES})")
                http_resp = http_client.post(api_url, headers=headers, json=payload)

                if http_resp.status_code != 200:
                    error_text = http_resp.text
                    print(f"\n❌ API 返回 HTTP {http_resp.status_code}")
                    print(f"  响应: {error_text[:500]}")
                    if http_resp.status_code >= 500 and attempt < MAX_RETRIES:
                        wait = attempt * 5
                        print(f"  🔄 {wait} 秒后重试...")
                        time.sleep(wait)
                        continue
                    break

                resp_json = http_resp.json()
                break

            except httpx.TimeoutException as e:
                print(f"  ⏳ 第 {attempt} 次请求超时: {e}")
                if attempt < MAX_RETRIES:
                    wait = attempt * 5
                    print(f"  🔄 {wait} 秒后重试...")
                    time.sleep(wait)
                else:
                    print(f"\n❌ 已重试 {MAX_RETRIES} 次仍然超时，放弃。")
            except Exception as e:
                print(f"\n❌ 请求异常: {e}")
                break

        if resp_json is None:
            break

        # 检查 API 层面的错误
        if "error" in resp_json:
            err = resp_json["error"]
            if isinstance(err, dict):
                print(f"\n❌ API 错误: [{err.get('type', 'unknown')}] {err.get('message', '')}")
            else:
                print(f"\n❌ API 错误: {err}")
            break

        # 解析 OpenAI 格式响应
        choices = resp_json.get("choices", [])
        if not choices:
            print("\n❌ 响应中没有 choices")
            break

        choice = choices[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        # 打印 Claude 的文本回复
        text_content = message.get("content", "")
        if text_content:
            print(f"\n💬 Claude: {text_content}\n")

        # 检查是否完成（没有工具调用 = 任务完成）
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            print("\n✅ 任务完成！")
            break

        # 将 assistant 消息加入历史
        messages.append(message)

        # 处理工具调用
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            tool_id   = tc.get("id", "")

            # 解析参数
            try:
                tool_args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_args = {}

            print(f"  🔧 工具调用: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:100]})")

            # 执行工具
            img_b64 = execute_tool(tool_name, tool_args)

            # 将工具结果加入历史（包含截图）
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": [
                    {"type": "text", "text": f"操作 {tool_name} 已执行完毕。以下是最新的屏幕截图："},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{img_b64}",
                        },
                    },
                ],
            })

    else:
        print(f"\n⚠️  达到最大迭代次数 ({MAX_ITERATIONS})，已停止。")

    print(f"\n📊 共执行了 {iteration} 次迭代。")
    http_client.close()


# ══════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude Computer Use - 本地 Windows 控制")
    parser.add_argument("--task",     type=str, help="要执行的任务")
    parser.add_argument("--confirm",  action="store_true", help="每步操作前确认")
    parser.add_argument("--base-url", type=str, help="API 地址")
    parser.add_argument("--model",    type=str, help="模型名称")
    parser.add_argument("--scale",    type=float, help="截图缩放比例")
    parser.add_argument("--max-iter", type=int, help="最大迭代次数")
    args = parser.parse_args()

    if args.confirm:
        CONFIRM_MODE = True
    if args.base_url:
        BASE_URL = args.base_url
    if args.model:
        MODEL = args.model
    if args.scale:
        SCALE = args.scale
        DW, DH = int(SW * SCALE), int(SH * SCALE)
    if args.max_iter:
        MAX_ITERATIONS = args.max_iter

    # 获取 API Key
    if not API_KEY:
        API_KEY = input("🔑 请输入 OpenRouter API Key: ").strip()
        if not API_KEY:
            print("❌ 未提供 API Key，退出。")
            sys.exit(1)

    # 获取任务
    task = args.task or input("📝 请输入任务: ").strip()
    if not task:
        print("❌ 未输入任务，退出。")
        sys.exit(1)

    print(f"\n🚀 开始执行任务...")
    print(f"💡 提示: 鼠标移到屏幕左上角可紧急中止脚本")
    print(f"💡 提示: Ctrl+C 也可以中止")

    try:
        run(task)
    except KeyboardInterrupt:
        print("\n\n🛑 用户中断。")
    except pyautogui.FailSafeException:
        print("\n\n🛑 FailSafe 触发（鼠标移到了左上角）。")
    except Exception as e:
        print(f"\n\n💥 未知错误: {e}")
        import traceback
        traceback.print_exc()
