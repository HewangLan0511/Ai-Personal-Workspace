"""把"真实 Tauri 桌面应用实机核验"章节追加到 edge-headless-ui-verify skill。"""
from pathlib import Path

P = Path(r"C:\Users\baiyu\.workbuddy\skills\edge-headless-ui-verify\SKILL.md")
ADD = """

---

## 十五、真实 Tauri / Electron 桌面应用的「实机核验」（Windows 实测清单）

**第 0 步：先分清两种完全不同的病因**（这一步常常直接给出答案）

- 症状「App 还是旧 UI」有两种可能：① 源码里真有两套 UI；② **用户打开的是旧安装件**。
- 判据极廉价：`安装目录\\app.exe` 的 size/mtime vs `target/release/app.exe` 与 `dist` 的 mtime。
  若安装件明显更旧 → 病因是②，处置是**重装刷新**（NSIS `/S` 静默升级），不是删代码。

**决定性轻量证据：exe 内嵌资产键（明文，即使资产内容是 Brotli）**

```python
import re
keys = set(re.findall(rb"/assets/[A-Za-z0-9_.\\-]+\\.(?:js|css)", open(exe, "rb").read()))
# 与 dist/index.html 里 <script src> 的入口 chunk 对比 → 即知嵌的是哪一版 UI
```

比截图/点击都稳，建议作为第一证据。

**WebView2 的硬限制（别在这里浪费时间）**

- CDP 端点只在启动后 ~5 秒可用（浏览器进程被替换后端口消失）→ **不能**支撑多页交互验收。
- 要开调试端口必须用环境变量 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=N`。
- ws 握手**不能带 `Origin`**（带了 403）；访问 `127.0.0.1` 必须绕沙箱代理
  （`build_opener(ProxyHandler({}))`），否则拿到 502 并误判"端点没起"。
- 消息级点击（`SendMessageW(hwnd, WM_LBUTTON*)` / `PostMessage`）Chromium **不响应** → 只认真实输入。

**真实鼠标点击要三条同时成立**

1. 进程声明 DPI 感知：`ctypes.windll.shcore.SetProcessDpiAwareness(2)`
   （否则客户区是虚拟尺寸、抓屏用物理坐标 → 坐标整体错位）；
2. `ImageGrab.grab(bbox=..., all_screens=True)`；
3. 窗口真的在最前 —— Windows 拒绝后台进程 `SetForegroundWindow`（`AttachThreadInput`/ALT 解锁也不可靠）；
   `HWND_TOPMOST` 必须传 `ctypes.c_void_p(-1)`（当 int 传会在 64 位被截断，**静默失败**）。
- 桌面被用户其他窗口覆盖时真实点击**无法完成**：脚本必须做**落点归属校验**
  （`WindowFromPoint` → 根窗口是否本 App / 落点窗口进程是否本 App），失败就**如实报「未完成」**，
  绝不伪造"点击通过"。
- 截图：`PrintWindow` 对 WebView2 常返回白面 → 判据用「中心区灰阶标准差 < 3 则回退屏幕抓取」。

**窗口识别**

- Tauri 的 webview 是主窗口的**子窗口**：`WRY_WEBVIEW` → `Chrome_WidgetWin_0/1` → `Chrome_RenderWidgetHostHWND`；
  顶层的同名 `Chrome_*` 窗口**可能属于别的应用**（别拿它当自己的）。
- 枚举窗口时排除 `ConsoleWindowClass`（release 版可能带控制台窗口，会被误选成"主窗口"）。
- 想把"当前页面"做成外部可读信号：前端 `router.afterEach` 调 `getCurrentWindow().setTitle(...)`
  （需 `core:window:allow-set-title`，生成在 `gen/schemas/capabilities.json`），再用 `GetWindowTextW` 读；
  **注意**该信号本机实测存在"标题不变"的未定性问题，不能当唯一判据。
"""

s = P.read_text(encoding="utf-8")
if "## 十五、真实 Tauri / Electron" not in s:
    P.write_text(s.rstrip() + ADD, encoding="utf-8")
    print("APPENDED", len(P.read_text(encoding='utf-8').splitlines()))
else:
    print("ALREADY PRESENT")
