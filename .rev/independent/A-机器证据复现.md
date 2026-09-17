# 独立审核员 A · 阶段1 机器证据复现报告

> 独立立场：未读任何评审历史，对开发方声称一律从零复跑、不信其为真。

## 一、结论总览（三类）

**① 已独立复现确认**
- 门禁 `gate.py --stage 1 --build`：确实 **0 FAIL / 29 PASS**（我跑出的 2 个 WARN 是自己的 `.rev/*.log` 被 H011 抓到，删掉后即为 0 WARN）。
- `cargo test --all`：**6/6 通过**（5 个 config schema 不变量 + 1 个时区工具）。
- 验收脚本 `verify_stage1.py`：真实启动 release exe + sidecar，应用能启动、DB 自动建库（schema_version=3）、sidecar /health=200、主题经 HTTP PUT 后落库 SQLite（4b 实测 `ui.theme='"dark"'`）、★Widget 经 Edge CDP **真实点击** 0→3→10 次、尺寸 small→medium→large、调序锁定半支也通过。
- 四类产物均真实存在：exe / sidecar / msi / nsis。

**② 与声称不符**
- 声称「验收 20/20 PASS」，但当前脚本实际只产出 **19 项**（全部 PASS，exit 0）。「20」无法从该脚本复现，属计数夸大/陈旧。
- 声称 ★Widget「已持久化」。**实测仅为浏览器 localStorage**：dev 模式 `inTauri()=false` 且 core HTTP 无 CORS 头，写入降级到 `localStorage['pw.config.ui.dashboard.usage']`（见 `configService.ts:9-14,51-59`），**从未触达 SQLite**。所谓「持久化」是一次性 Edge 临时 profile 内的 localStorage，窗口关掉即随 `shutil.rmtree` 销毁，不等于落库持久化。
- 门禁 29 PASS 中 **25 项为「文件/目录存在」检查**（S000/S100/S110×10/A030/B120 等），只占 4 项是实质检查（cargo check、typecheck、2 个引用性 W100）。「文件存在 ≠ 功能存在」——门禁脚本自身注释也承认这点。

**③ 证据不足 / 无法判定**
- 验收项 3「无白屏」判据偏弱（见下），仅能确认「页面较大且含导航」，不能确认「主内容区真实渲染」；本次 dom_len 8k–12k 显示确有内容，但判据本身对白屏缺乏区分度。
- `cargo test` 6/6 但**范围很窄**：无窗口创建、无 sidecar 拉起、无 HTTP API、无 migration 执行、无 widget 逻辑的单测。

## 二、门禁原始输出（节选）

```
✅ 门禁通过   FAIL=0  WARN=2  PASS=29        # 2 WARN=我自己 .rev/*.log 触发 H011
[PASS] B100 — cargo check 通过
[PASS] B110 — 前端 typecheck 通过
[PASS] B120 — externalBin 产物就绪：binaries/service → service-x86_64-pc-windows-msvc.exe
[PASS] W100 — ui/src/utils/logger.ts 已被 ui/src/api/client.ts 引用（接线到位）
[PASS] W100 — ui/src/composables/useWidgets.ts 已被 .../DashboardView.vue 引用
[WARN] H011 — 临时/日志文件混入仓库  @ .rev/cargotest_run.log   # 自产污染
# 其余 25 PASS = S000×5 + S100×8 + S110×10 + A030×1（均为存在性检查）
```

## 三、cargo test 原始输出（节选）

```
running 6 tests
test db::config::tests::every_registered_key_has_an_explicit_default ... ok
test db::config::tests::every_registered_key_has_an_explicit_type ... ok
test db::config::tests::layout_locked_is_boolean_and_enforced ... ok
test db::config::tests::type_rules_hold ... ok
test db::config::tests::unregistered_key_is_not_in_whitelist ... ok
test event_bus::tests::iso_now_carries_local_offset ... ok
test result: ok. 6 passed; 0 failed; 0 ignored
```

## 四、验收脚本原始输出（节选，exit 0）

```
PASS  1 应用能启动（窗口出现）              窗口标题含 'Personal Workspace'
PASS  2 启动速度 < 3s                        651 ms
PASS  6 首次启动自动建库 + migration         config 表 13 行；schema_version=3
PASS  5a sidecar 拉起 + /health 200          core port=50253, sidecar port=50304 → /health 200
PASS  5b 杀掉 sidecar 后主界面仍可用          core /health=200；窗口仍在
PASS  4a 配置写入（HTTP PUT ui.theme=dark）  原值='light' → ok:true
PASS  4b 重启后主题仍为 dark（持久化）        库中 ui.theme='"dark"'   ← 真·SQLite 持久化
PASS  3 /dashboard../settings                9 条 marker=True nav=齐全 dom_len=8k~12k
PASS  2b 顶栏含 [设置][最小化]
PASS  8 ★ Widget 动态布局
   A｜use=['0','3','10'] size=['small','medium','large']
      最终落库='{"weather":10}' 落库值演变=['{"weather":1}','{"weather":10}']
   B｜调序锁定(设备状态): 起始 small → 锁后=true → 锁定态点5次 use=5 size=仍 small
      → 解冻后 size=medium / lock=false
```
注：第 8 项「落库」实为 `localStorage`（见下方断言审计），非 SQLite。

## 五、断言强度审计

**gate.py**：真检查 = `cargo check`(B100)、`npm run typecheck`(B110)、W100 引用性扫描，以及内容扫描（密钥 V1 / 调试残留 Q001 / UI 直连 DB V7 / 硬编码路径 A020 / ADR-001 A031 进程拉起 / unwrap·panic 漂移 R001）。这些确实读文件内容/跑编译器。可被轻易绕过的是 **S/A/B 存在性检查**：放空文件即可 PASS，不验内容。门禁给出「通过」信号真实，但 25/29 的 PASS 无功能含义。

**verify_stage1.py**：未发现把异常吞成 PASS 的代码——路由每条包 try/except→FAIL；探针 `except`→FAIL；找不到 Edge→FAIL（非静默跳过）；`all_ok` 汇总包含所有项。Widget 探针设计扎实：真实 CDP 点击、断言 `size-*` class、调序锁定用「锁定态点 5 次尺寸仍 small」做有区分度断言、轮询 localStorage 收敛到 weather===10。两处硬伤：
1. 路由「无白屏」= `marker in dom`（与 nav 文本重复）+ 7 个 `href` + `len(dom)>1500`。nav 健全但**主内容区白屏**的页面仍可能 PASS（`len>1500` 太弱，错误页也满足）。
2. Widget「持久化」只验 localStorage（dev 降级），**未验 SQLite**，却与「已持久化」混为一谈。

## 六、产物枚举（独立确认）

| 产物 | 路径 | 大小 |
|---|---|---|
| 主程序 | core/target/release/personal-workspace-core.exe | 7,216,640 B |
| sidecar | core/binaries/service-x86_64-pc-windows-msvc.exe | 9,062,595 B |
| msi | core/target/release/bundle/msi/Personal Workspace_0.1.0_x64_en-US.msi | 12,345,344 B |
| nsis | core/target/release/bundle/nsis/Personal Workspace_0.1.0_x64-setup.exe | 11,329,431 B |

注意：门禁**不**校验 msi/nsis（B120 只查 externalBin），二者由先前 `npm run tauri build` 产出，靠本次独立枚举确认。

## 七、最终判定

**阶段1 的机器证据不足以无保留地支撑「通过」。**

主体功能可复现：应用启动、DB 自动建库、sidecar 健康、主题经 HTTP 真实落库 SQLite、编译与类型检查通过、★Widget 动态布局经真实点击验证了尺寸随次数变化与调序锁定。但开发方声称存在**两处与实测不符/夸大**：

1. 验收脚本实为 **19 项通过（exit 0）**，并非声称的「20/20」；
2. ★Widget 的「已持久化」**仅验证到浏览器 localStorage**（dev 模式 CORS 降级，从未落 SQLite），声称「持久化」夸大；此外验收项 3「无白屏」判据过弱、门禁 29 PASS 中 25 项仅为存在性检查。

建议：修正声称口径（19 项、Widget 持久化标注为 localStorage 降级），并补强两项断言（路由改判「主内容区真实节点」而非 `len>1500`；Widget 持久化改读 SQLite config 表）后，再判定阶段1通过。
