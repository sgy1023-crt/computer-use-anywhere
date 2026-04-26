# Claude 电脑操作代理

这是一个 Windows 本地版的 `computer use` 项目，目标不是复刻官方 Docker/X11 环境，而是把它做成真正能在你本机上直接跑、还能兼容中转站和官方协议的可视化工具。

## 现在有三种模式

- `兼容模式`
  - 走 OpenAI-compatible `chat/completions`
  - 适合中转站、任意支持视觉和工具调用的模型
  - 本质是 `截图 + function calling + 本地桌面执行器`
- `官方体验兼容模式`
  - 仍走 OpenAI-compatible `chat/completions`
  - 适合不支持 Anthropic Messages API、但想测试官方 computer use 风格的中转站
  - 只暴露单个 `computer` 工具，不启用 `browser_dom`
  - prompt 和循环按“观察截图 -> 执行一个 computer 动作 -> 再观察截图”的官方风格约束
- `官方模式`
  - 走 Anthropic `Messages API`
  - 自动带上 `anthropic-version`、`anthropic-beta` 和官方 `computer_xxx` 工具类型
  - 更接近 Anthropic 官方 `computer-use-demo`
  - 可切换 `官方纯原生` 和 `官方增强原生`
  - 纯原生只保留官方 computer 工具和截图回传
  - 增强原生仍不加自定义工具，但启用本地遮挡、越界、前台窗口和截图变化安全阀

## 当前能力

- Windows 本地截图、点击、双击、右键、拖拽、滚轮、按键、输入、等待
- 兼容模式支持 `activate_window`，可以按窗口标题关键词把目标应用切到前台
- 输入/回车等高风险动作会检查前台窗口，避免把内容输进代理窗口或错误窗口
- 每张截图会同时回传当前前台窗口标题和可见窗口标题列表，帮助模型确认自己到底在操作哪个窗口
- 越界坐标会被拦截，不会再被静默夹到屏幕边缘
- 执行后会提示截图是否发生可见变化，减少模型“自以为成功”
- 兼容常见脏参数：坐标可以是 `[x,y]`、`{"x":x,"y":y}` 或 `"x=..., y=..."`
- 执行动作出错时不会直接中断会话，会把错误和最新截图回传给模型修正
- 兼容模式新增 `browser_dom` 工具：可通过 Chrome/Edge 调试端口读取 DOM、导航、点击选择器、按文本点击、填写表单、等待文本/选择器、读取控件值、向控件发送回车
- 兼容模式支持“网页任务优先 DOM”：明显网页任务会先要求模型尝试 `browser_dom`，失败后再回退到截图点击
- 界面提供“启动调试 Edge”按钮，减少手动输入调试端口启动命令
- 界面提供“本机自检”按钮，能快速确认截图、Windows 桌面 API、浏览器 DOM 调试端口是否可用
- 启动前会做静态诊断，提示官方模式/兼容模式的接口路径、beta、tool 类型是否明显填反
- 每次会话会生成 `replay.jsonl` 和 `replay.html`，逐步记录模型文本、动作参数、执行前后截图和动作验证结果
- 每步执行后自动回传最新截图
- 默认自动隐藏代理窗口，减少“看着自己点自己”的误操作
- 中文界面、中文日志、中文过程面板
- 过程面板显示可见推理、动作理由、动作参数
- 官方模式会显示 `thinking` 元信息，但不会直接暴露原始隐藏思维链

## 运行

```powershell
python h:\python\claude-computer-use-proxy\run.py
```

如果你的 `python` 不在 PATH，就换成你本机能正常打开 Tk 界面的 Python 路径。

如果要启用浏览器 DOM 工具，Edge/Chrome 需要用调试端口启动，例如：

```powershell
Start-Process msedge.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir=%TEMP%\computer-use-edge'
```

打开后在界面里保持“启用浏览器 DOM 工具”，端口默认 `9222`。

## 打包 EXE

先确保当前 Python 已安装 PyInstaller：

```powershell
python -m pip install pyinstaller
```

默认打包为更稳定的文件夹版；加 `-Zip` 会同时生成便携压缩包：

```powershell
powershell.exe -ExecutionPolicy Bypass -File h:\python\claude-computer-use-proxy\scripts\build_exe.ps1 -Zip
```

产物位置：

```text
h:\python\claude-computer-use-proxy\dist\ClaudeComputerUseProxy\ClaudeComputerUseProxy.exe
h:\python\claude-computer-use-proxy\dist\ClaudeComputerUseProxy-portable.zip
```

如果没有安装 PyInstaller，也可以让脚本自动安装：

```powershell
powershell.exe -ExecutionPolicy Bypass -File h:\python\claude-computer-use-proxy\scripts\build_exe.ps1 -InstallMissing -Zip
```

如果一定要单文件版：

```powershell
powershell.exe -ExecutionPolicy Bypass -File h:\python\claude-computer-use-proxy\scripts\build_exe.ps1 -OneFile -Zip
```

EXE 运行时会把 `settings.json` 和 `sessions` 写在 EXE 所在目录旁边，方便复制和排查。

## 测试

```powershell
$env:PYTHONPATH='h:\python\claude-computer-use-proxy\src'
& 'C:\Users\SGY\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s 'h:\python\claude-computer-use-proxy\tests' -v
```

## 说明

- 兼容模式优先解决“中转站能跑”
- 官方模式优先解决“更像 Anthropic 官方 demo”
- 两套模式共用同一个 Windows 执行器和截图面板
