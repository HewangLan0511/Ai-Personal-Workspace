# 插件开发指南（阶段9）

> 面向插件作者。读完这份文档 + 照抄 `plugins/examples/` 里的两个示例，就能写一个
> 能跑的 Personal Workspace 插件 —— **全程不需要改 core 一行代码**（这是本插件
> 架构成功的判据，12 §「声明性标准」）。

## 1. 心智模型：你的代码跑在哪、能碰什么

```
┌───────────────────────────── Tauri 主进程 ─────────────────────────────┐
│  core (Rust) —— 信任边界                                                │
│   · manifest 校验 / 安装卸载 / 权限判定 / 审计 / 数据隔离                │
└────────────▲────────────────────────────────────────────────────────────┘
             │ Tauri command（plugin_api：每次调用都过权限网关并写审计）
┌────────────┴────────────────────────────────────────────────────────────┐
│  UI webview（PluginHost 桥）                                            │
│   ┌─────────────────────────────┐                                       │
│   │ 沙箱 iframe（你的插件）      │  sandbox，无 allow-same-origin        │
│   │ 纯 HTML/JS/CSS，opaque origin │  —— 拿不到 cookie/DOM/数据库          │
│   └─────────────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

三条铁律（都有结构性保证，不靠自觉）：

1. **默认零权限**（红线 V4）：manifest 没声明的能力，调用一律
   `PERMISSION_DENIED`，且这次越权尝试会被写进审计。
2. **不碰数据库**（红线 V7）：你没有 SQL 通道。自己的数据用
   Data API（落 `plugins/<id>/data/*.json`，按 plugin_id 隔离）。
3. **一切能力过网关**：iframe → postMessage → PluginHost → core 网关 → 执行。
   每一次调用（成功/被拒/出错）都写 `plugin_audit`。

## 2. 目录与 manifest

```
com.example.<name>/
├── manifest.json     ← 必须
├── index.html        ← manifest.entry 指向的文件（iframe 加载它）
└── index.js
```

`manifest.json` 字段（契约 3.2.4）：

```json
{
  "pluginId": "com.example.pomodoro",   // 反向域名，[a-z0-9.-]
  "name": "番茄钟",
  "version": "1.0.0",                   // X.Y.Z
  "author": "you",
  "description": "一句话说明",
  "entry": "index.html",
  "permissions": ["data:own", "ui:widget"],
  "ui": { "type": "widget", "size": "small", "route": "index.html" },
  "minAppVersion": "0.1.0"
}
```

权限清单（声明即安装时授权，用户看得到）：

| 权限 | 能干什么 |
|------|----------|
| `ui:widget` | 出现在小组件窗口 / 调 `ui.notify` |
| `app:launch` | `system.appLaunch(nameOrId)` |
| `window:read` | `system.windowRead()` |
| `system:media` | `system.mediaNow()` / `system.mediaControl(action)` |
| `data:own` | `data.get/set/delete/keys`（自己的隔离目录） |
| `ai:invoke` | `ai.invoke(prompt)` —— **恒 consult 模式**，不注入用户数据 |
| `net:http` + scope 域名 | `net.http(url)`，仅 `http://`（不支持 https） |
| `file:read`/`file:write` + scope 目录 | 读写 scope 目录内的文件（≤1MB） |

`{permission, scope}` 对象形态可带范围：`{"permission": "net:http", "scope": ["api.example.com"]}`。

## 3. 桥协议（契约 3.2.7）

iframe 与宿主之间只有 postMessage。信封：

```js
// 你 → 宿主（⚠️ targetOrigin 必须是 '*'：第二个参数校验的是【接收方=父窗口】的
// origin（生产态为 http://tauri.localhost），不是你自己（iframe）的 origin。
// 写成 'http://pwplugin.localhost' 消息会被浏览器静默丢弃，宿主 10s 判超时）
window.parent.postMessage(
  { __pwPlugin: true, reqId: 1, api: 'system', method: 'mediaNow', payload: {} },
  '*'
);
// 宿主 → 你（同 reqId）
{ __pwPlugin: true, reqId: 1, ok: true, data: {...} }
{ __pwPlugin: true, reqId: 1, ok: false, error: { code, message } }
```

必须做的三件事：

1. **就绪上报**（加载后立刻）：
   `window.parent.postMessage({ __pwPlugin: true, ready: true }, '*')`
   —— 10 秒内没报，宿主标记"加载超时"。用 `'*'` 是安全的：宿主侧会校验
   消息来源 origin（`http://pwplugin.localhost`）与 iframe 登记表。
2. **崩溃上报**：`window.onerror` 里发
   `{ __pwPlugin: true, crash: { reason } }` —— 宿主上报 core 并标记"已停止"。
3. **只从 `http://pwplugin.localhost` 加载资源**：iframe 的 src 是
   `http://pwplugin.localhost/<pluginId>/<entry>`，同目录其他文件用相对路径引用即可。

> 两个示例（`plugins/examples/com.example.pomodoro` / `com.example.music`）把以上
> 脚手架都写好了（`pw.call()` 封装约 20 行），建议直接复制改造。

## 4. 安装与调试

1. 把插件目录拷进插件根（`%APPDATA%/PersonalWorkspace/plugins/`，或设
   `PW_PLUGINS_DIR` 覆盖）；zip 包也可以在「插件」页直接导入（防 zip-slip 解包）。
2. 「插件」页 → 扫描插件目录 → 安装（默认**禁用**）→ 手动启用。
3. 每次调用都会写审计：「插件」页点某插件的"审计"可以看到最近 20 条，
   包括被拒绝的越权尝试。
4. 调试技巧：`data.set` 写坏 key（带 `/` 之类）会被 400 拒绝并在审计留痕 ——
   审计是你的第一调试入口。

## 5. 边界与限制（如实告知）

- 无 `https`（core 无 TLS crate，`net.http` 对 https 明确报 `https_unsupported`）。
- 无持久 WebSocket、无后台运行：iframe 关闭即停，状态请落 Data API。
- `ai.invoke` 走 consult 模式：插件只能问 AI，不能让 AI 读你的工作区数据。
- 文件 API 只在 scope 目录内，且单文件 ≤1MB（读）/ 无大小承诺（写，建议小文件）。
- 插件崩溃（onerror）不影响主程序；宿主标"已停止"后可手动重启该 iframe。
