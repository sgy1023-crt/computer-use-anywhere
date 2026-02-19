# 🖥️ Windows Claude Computer Use

> 一个小白vibe coding的项目，能跑就行，别太认真😂
> *A project vibe-coded by a newbie. It runs, that's enough.*

---

## ⚠️ 免责声明 / Disclaimer

- 本项目**仅供学习和技术探讨**，不代表 Anthropic 官方立场
- 本项目**性价比极低**，搜个东西可能花你好几块钱，请做好心理准备。可能是windows目前并不兼容。
- 作者是小白，代码vibe coding出来的，出了问题别怪我😅
- This project is **for learning and technical discussion only**, not affiliated with Anthropic
- This project is **extremely cost-inefficient**. Be prepared to spend real money on simple tasks. This may be due to current Windows compatibility limitations.
- Author is a newbie, code was vibe-coded. Use at your own risk 😅

---

## 🤔 这是什么 / What is this?

一个运行在 **Windows 本地**的 Claude Computer Use 脚本。

它能让 Claude 使用官方的 Computer Use 功能，通过截图看到你的屏幕，然后控制鼠标和键盘帮你完成任务。

**最重要的特点：** 支持任何兼容 OpenAI function calling 协议的中转站，不需要直连 Anthropic 官方 API！

A local **Windows-native** Claude Computer Use script.

It lets Claude use the official Computer Use feature, see your screen via screenshots, then control your mouse and keyboard to complete tasks.

**Key feature:** Works with any API proxy that supports OpenAI-compatible function calling — no need to connect directly to Anthropic's official API!

---

## 💡 为什么要做这个 / Why build this?

官方的 Claude Computer Use 只有 Docker/Linux 版本，Windows 用户很难上手。并且最近官方发布了Claude Sonnet 4.6模型，在Claude Computer Use上的功能有了很大的提升，Sonnet 4.6 在 OSWorld 上是 72.5%。为了用这个最新模型体验最新的computer_20250124 beta 工具协议操作电脑的功能，则开始研究本项目。这个项目的初衷只是为了技术学习，并不是为了生产使用。

另外发现了一个坑：**OpenRouter 目前不支持 Anthropic 的 beta Computer Use 工具类型**（会直接报错或被忽略）。

所以用标准 function calling 重新实现了一遍，绕过了这个限制，让任何支持 function calling 的中转站都能用。

The official Claude Computer Use only has Docker/Linux support, making it hard for Windows users. Anthropic recently released Claude Sonnet 4.6 with major improvements to Computer Use — achieving 72.5% on OSWorld benchmarks. This project was started to experience the latest computer_20250124 beta tool protocol with this newest model. The goal is purely technical learning, not production use.

Also discovered a key issue: **OpenRouter does NOT currently support Anthropic's beta Computer Use tool types** (returns errors or ignores them).

So we reimplemented everything using standard function calling, bypassing this limitation and making it work with any compatible API proxy.

---

## 🚀 快速开始 / Quick Start

### 安装依赖 / Install dependencies

```bash
pip install httpx pyautogui pyperclip Pillow
```

### 配置 API / Configure API

在脚本里找到这一行，填入你的 API Key：

```python
OPENROUTER_KEY = "你的API Key"
```

或者设置环境变量：

```bash
set ANTHROPIC_API_KEY=你的Key
set ANTHROPIC_BASE_URL=https://你的中转站地址
```

### 运行 / Run

```bash
# 直接运行，交互式输入任务
python computer_use.py

# 直接指定任务
python computer_use.py --task "打开记事本写一首诗"

# 每步操作前确认（推荐新手使用）
python computer_use.py --confirm

# 换一个便宜点的模型
python computer_use.py --model "anthropic/claude-3.5-sonnet"
```

---

## ⚙️ 主要配置 / Config

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `SCALE` | 截图缩放比例，越小越省钱 | `0.75` |
| `JPEG_QUALITY` | 截图压缩质量 | `60` |
| `MAX_ITERATIONS` | 最大操作步数，防止无限烧钱 | `30` |
| `CONFIRM_MODE` | 每步操作前确认 | `False` |

---

## 💸 关于费用 / About Cost

说真的，**这玩意很贵**。

作者亲测：让它先识别我本地浏览器在哪里后打开浏览器搜索一个关键词，花了将近 2 块钱人民币还没完成任务。

原因是每一步操作都要截图，截图都要算 token，token 就是钱。

建议：**当技术学习用，别当生产工具用。** 真要自动化操作电脑，用其他更多的平替更香。

Honestly, **this thing is expensive**.

Author tested: asked it to find the local browser and open it to search for a keyword — cost nearly ¥2 RMB and the task still didn't complete.

Every action requires a screenshot, every screenshot costs tokens, tokens cost money.

Suggestion: **Use it for learning, not production.** For real automation, there are much more cost-effective alternatives out there.

## ⚠️ 注意 / Note
本项目不需要安装 `anthropic` 官方库，直接使用 `httpx` 发送原始 HTTP 请求。
This project does NOT require the `anthropic` SDK. It uses raw `httpx` HTTP requests instead.

## 💻 高分辨率屏幕 / High-DPI Support
本项目已内置 Windows 高DPI适配，2K/4K屏幕用户无需额外配置。
Built-in Windows High-DPI support. No extra configuration needed for 2K/4K screens.

---

## 🙏 希望大佬们能帮忙改进 / Call for Contributors

作者是小白，这个项目还有很多可以优化的地方，欢迎大佬们 PR！

比如：
- 更智能的截图策略（减少不必要的截图）
- 支持更多中转站
- 更好的错误处理
- 降低 token 消耗的方案
- 任何你觉得可以改进的地方😄

I'm a newbie and there's a lot of room for improvement. PRs are very welcome!

Ideas:
- Smarter screenshot strategy (reduce unnecessary captures)
- Support for more API proxies
- Better error handling
- Ways to reduce token consumption
- Anything you think could be better 😄

---

## 📋 相关项目 / Related Projects

- [anthropic-quickstarts](https://github.com/anthropics/anthropic-quickstarts) - Anthropic 官方示例（Docker版）
- [windows_claude_computer_use](https://github.com/CursorTouch/Windows-MCP) - 另一个 Windows 方向的尝试

---

## 📄 License

MIT — 随便用，随便改，随便分发，出了事别找我😂

*MIT — Use it, modify it, distribute it freely. Don't blame me if something goes wrong 😂*
