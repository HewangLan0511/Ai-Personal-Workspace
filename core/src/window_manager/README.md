# window_manager —— 窗口管理系统（阶段3）

> **ADR-001：窗口控制 = Rust**（`windows` crate）。
> `system/` 下不得出现窗口/进程实现；门禁 `A031` 按**能力名**扫描（`SetWindowPos`/`EnumWindows`/…）会拦。

---

## 模块划分

| 文件 | 职责 | 对应指令 |
|------|------|----------|
| `layout.rs` | 归一化坐标 → 像素（**纯函数**，无 Win32 依赖） | 07 §4 + 验收项 10 |
| `monitor.rs` | 显示器枚举 / 工作区 / DPI 感知声明 | 07 §4 + 验收项 7/8 |
| `window.rs` | 窗口查找 / 定位 / 激活 | 07 §1/§2/§3 |
| `apply.rs` | 编排：槽位→窗口→定位→激活 + 重试 + 事件 | 07 §工程要求 |
| `mod.rs` | 布局文件读写（`config/layouts/*.json`） | 07 §5 |

---

## 对外 API

### 布局
| 命令 | HTTP | 说明 |
|------|------|------|
| `layouts_list()` | `GET /api/v1/layouts` | 内置布局全文（含槽位与侧栏） |
| `layout_get(name)` | `GET /api/v1/layouts/{name}` | 单个布局 |
| `layout_apply(name, monitor?)` | `POST /api/v1/layouts/{name}/apply` | 应用布局（可覆盖目标显示器） |

### 窗口
| 命令 | HTTP | 说明 |
|------|------|------|
| `windows_list()` | `GET /api/v1/windows` | 全部可管理顶层窗口 |
| `windows_find(pid?, title?)` | `GET /api/v1/windows?pid=&title=` | 查找（pid 优先；**无窗口返回 null**） |
| `windows_rect(hwnd)` | `GET /api/v1/windows/{hwnd}` | 当前像素矩形 |
| `windows_place(hwnd, rect, …)` | `POST /api/v1/windows/{hwnd}` | 定位（`maximized` 可选） |
| `windows_activate(hwnd)` | `POST /api/v1/windows/{hwnd}/activate` | 激活并置前 |

### 显示器
`monitors_list()` / `GET /api/v1/monitors`

---

## 注意事项（都是踩过的坑）

### 1. DPI 感知**必须最先声明**
`main.rs` 在创建任何窗口前调用 `enable_dpi_awareness()`
（`SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`）。

漏掉它，系统按 96 DPI **虚拟化**坐标返回，125%/150% 缩放下布局比例会整体偏小 ——
且现象隐蔽：只在非 100% 缩放的机器上出现。本机是 **125%**（DPI 120），验收项 8 专测这条。

### 2. 定位前先取消最大化
`IsZoomed`/`IsIconic` 为真时直接 `SetWindowPos` **无效**（07 §2 明确点名）。
`window::place()` 会先 `SW_RESTORE`。

### 3. 激活要绕过前台锁定
Windows 不让后台进程随便抢前台。`window::activate()` 用
`AttachThreadInput(本线程, 目标线程, true)` → `BringWindowToTop` → `SetForegroundWindow` → 解除 attach。

> ⚠️ `AttachThreadInput` 在 windows crate 0.59 里位于 **`Win32::System::Threading`**，
> 不在 `Win32::UI::Input::KeyboardAndMouse`（查了 crate 源码才找到）。

### 4. z 序与激活顺序（**当前按契约实现，未单独断言层级**）
契约 3.2.2 规定「`z` 越小越靠后」。`activate()` 因此按 **z 升序**逐个激活
（先激活靠后的，最后激活靠前的 → z 最大的落在最上层）。

07 §3 原文对顺序存疑并注明"需实测确定"。**现状：逻辑与契约一致，但验收脚本只验证
"目标窗口成为前台窗口"（验收项 5），没有断言多窗口层叠的相对次序** —— 若要严格保证层叠，
需要引入 `SetWindowPos(HWND_TOP)` 的显式 z 序调用，属后续增强。

### 5. 多显示器降级
`monitor` 索引不存在时**降级到主显示器**并置 `degraded_monitor=true`（07 §4），
`apply` 结果里能直接看到，同时打 `WARN` 日志。

---

## 验收步骤

```bash
# 1. 编译 release
cd core && cargo build --release && cd ..

# 2. 端到端验收（07 的 10 项验收标准）
python tools/verify_stage3.py

# 3. 纯函数单测（验收项 10）
cd core && cargo test window_manager::layout
```

`verify_stage3.py` 的做法：复制 `notepad.exe` 成 4 份不同文件名（`VT-A.exe`…）启动，
得到 4 个 pid 干净、互不干扰的 GUI 窗口，然后**用 `GetWindowRect` 读回实际位置**比对 ——
不采信接口自述的"我移动了"。

> 为什么不用 calc/mspaint：UWP 别名的真实窗口属于 `ApplicationFrameHost.exe`，pid 对不上；
> cmd 在 Win11 里常被 Windows Terminal 接管。**复制同一 PE 多次**最可控。

---

## 已知限制

- **拖拽式布局编辑器未实现**：当前 UI 是"列表 + 预览 + 一键应用"（07 §6 的"网格画布拖拽划分"尚未做）。
- **自定义布局保存未实现**：只读 `config/layouts/*.json`；写回需新增保存接口。
- 层叠次序（见上文 §4）未做机器断言。
