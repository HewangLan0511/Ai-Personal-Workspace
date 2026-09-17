#!/usr/bin/env node
/**
 * Tauri CLI 转发器。
 *
 * 为什么需要它：`tauri.conf.json`、`Cargo.toml` 都在 `core/`，而 `npm run` 的
 * cwd 恒为包目录 `ui/` —— 直接跑 CLI 会找不到工程。本脚本把 cwd 切到 `core/`
 * 后再转发全部参数，使 `npm run tauri dev|build`（04 验收标准 1 / 7 的原始命令）可用。
 *
 * ⚠️ 路径基准的两套规则（实测确认，别记混）：
 *   - `frontendDist` / `externalBin` / `icon`：相对 **tauri.conf.json 所在目录**（即 `core/`）
 *     ⇒ `../ui/dist`、`binaries/service`；
 *   - `beforeDevCommand` / `beforeBuildCommand` 的 **cwd 是仓库根**，不是 `core/`
 *     ⇒ 写 `npm --prefix ui run dev`、`python system/build_sidecar.py`。
 *   曾经把后者也按 `core/` 理解（写成 `--prefix ../ui`），结果被解析到
 *   `C:\Users\<用户>\Desktop\ui` 而失败 —— 这是靠文件探针实测出来的，不是推出来的。
 *
 * 用法：
 *   npm run tauri dev
 *   npm run tauri build
 *   npm run tauri build -- --no-bundle      # 只出 exe，不打安装包
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const coreDir = path.resolve(here, '..', '..', 'core')
const cliEntry = path.resolve(here, '..', 'node_modules', '@tauri-apps', 'cli', 'tauri.js')

const result = spawnSync(process.execPath, [cliEntry, ...process.argv.slice(2)], {
  cwd: coreDir,
  stdio: 'inherit',
})

if (result.error) {
  console.error(`[tauri] 启动失败：${result.error.message}`)
  process.exit(1)
}
process.exit(result.status ?? 1)
