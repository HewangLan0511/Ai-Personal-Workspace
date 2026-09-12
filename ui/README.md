# ui/ —— Personal Workspace 前端

Vue 3 + TypeScript + Vite + Pinia + Vue Router。

## 运行

```bash
npm install
npm run dev         # http://localhost:5173
npm run typecheck   # vue-tsc --noEmit（门禁 B110 会跑这条）
npm run build       # vue-tsc + vite build
```

Tauri 集成：
- `core/tauri.conf.json` 的 `build.devUrl` 指向 `http://localhost:5173`
- `build.frontendDist` 指向本目录的 `dist/`（npm run build 产出）

## 目录

```
src/
├── api/            core HTTP 客户端 + 配置服务封装（含离线降级）
├── components/     TopBar / NavSide / StatusBar / WidgetCard
├── composables/    useWidgets
├── router/         9 路由（含 /plugins 占位）
├── stores/         nav / settings / widgets（pinia）
├── styles/         base.css（CSS 变量 + 主题）
├── utils/          logger（无 console 残留）
├── views/          9 页面骨架
├── widgets/        7 Widget + fallback
├── App.vue
└── main.ts
```

## 配置键（写入 core SQLite config 表）

| 键 | 默认 | 说明 |
|----|------|------|
| `ui.theme` | `"light"` | 主题 |
| `ui.nav.collapsed` | `false` | 侧栏折叠状态 |
| `ui.dashboard.widgets` | `[]` | Widget 顺序与布局（layout_locked 触发） |
| `app.autostart` | `false` | 开机自启 |
| `app.data_dir` | `""` | 数据目录 |
| `ai.default_provider` | `""` | 默认 AI Provider |
| `privacy.telemetry` | `false` | 匿名遥测（默认关闭） |
| `runtime.http_port` | `null` | core HTTP 端口（运行期注入） |

## 离线降级

core 不可达时，配置读写自动走 `localStorage`，UI 顶部显示"⚠ 降级模式"提示。
核心恢复后由阶段2 的对账逻辑把本地变更同步回 SQLite（本阶段仅本地累积）。

## 已知限制（阶段1）

- 工作模式 / 软件库 / AI / 学习 / 档案 / 生活 / 设备 / 插件 各页面为骨架占位。
- 频繁 Widget、当前项目 Widget 展示空状态（依赖阶段2、阶段6 接入）。