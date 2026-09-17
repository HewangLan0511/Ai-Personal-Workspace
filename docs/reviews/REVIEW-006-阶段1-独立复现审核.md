# REVIEW-006 · 阶段1 独立复现审核（审核方对 REVIEW-005 的复核）

| 项 | 内容 |
|----|------|
| 报告编号 | REVIEW-006 |
| 日期 | 2026-09-12 |
| 编写 | 肉编器001号（**架构 + 开发 + 审核 同一主体** —— 独立性限制见第〇章） |
| 审核对象 | `REVIEW-005-阶段1-复验报告.md` 的全部结论 + 其依据 `tools/verify_stage1.py` / `tools/gate.py` |
| 触发 | 白宇指令：「现在进行阶段一审核」 |
| 方法 | **不信汇报，只跑产物**：对 REVIEW-005 声称的每一项数字，用独立命令重新执行一遍；并审读核验脚本自身的断言强度 |
| 判定 | **机器可判部分：独立复现与 REPORT-005 完全一致，予以采信。**<br>**新发现 1 处标注过头（F-1）**：§6 第 3 行「`layout_locked` 冻结自动尺寸」标 ✅，但该半支**无任何机器验证**。建议降级为 ⚠️ 并登记 U-12。<br>**整体结论不变**：阶段1 的 ★ 核心机制（次数→尺寸）已端到端实测通过。 |

---

## 〇、独立性声明（同一限制，照旧必读）

角色合并（2026-09-12 18:20，见 `LEDGER.md` 治理变更记录）把架构/开发/审核压到同一主体。
因此本报告**仍不是独立第三方审核** —— 我复核的是"另一个我"写的报告。

但与 REVIEW-004/005 的自检不同，本报告做了两件自检通常不会做的事：

1. **重新执行**：REVIEW-005 里的每一个数字（门禁、测试、验收）都当"被告方证词"从零复跑，而不是引用；
2. **审读断言本身**：核验脚本是被告方写的"自证程序"，天然可能藏着弱断言/吞异常 —— 本报告逐条审它有没有把戏。

> 结论的可信度来自"任何人照文档重跑都能得到同样数字"，**不来自本报告的措辞**。

---

## 一、逐项复现：REVIEW-005 的声称 vs 我重跑的结果

### 1.1 门禁（声称：0F / 0W / 29P）

我独立执行 `python tools/gate.py --stage 1 --build`，原始输出留档 `.rev/gate.txt`：

```
✅ 门禁通过   FAIL=0  WARN=0  PASS=29
  [PASS] B100 — cargo check 通过
  [PASS] B110 — 前端 typecheck 通过
  [PASS] B120 — externalBin 产物就绪：binaries/service → service-x86_64-pc-windows-msvc.exe
  [PASS] A030 — ADR-001：system/build_sidecar.py 属构建脚本，豁免
  [PASS] W100 ×2 — logger.ts / useWidgets.ts 接线到位
```

**复现结果：一致。** 且 `B100 cargo check` 是**真编译**（不是"工具链缺失"的假 PASS，M-2 已修）。

### 1.2 Rust 单元测试（声称：6/6）

我独立执行 `cargo test --all --no-fail-fast`（18s）：

```
running 6 tests
test db::config::tests::every_registered_key_has_an_explicit_default ... ok
test db::config::tests::every_registered_key_has_an_explicit_type ... ok
test db::config::tests::layout_locked_is_boolean_and_enforced ... ok
test db::config::tests::type_rules_hold ... ok
test db::config::tests::unregistered_key_is_not_in_whitelist ... ok
test event_bus::tests::iso_now_carries_local_offset ... ok
test result: ok. 6 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

**复现结果：一致。** 另注意到 30 条 `dead_code` 警告（`AppRecord` / `launch` / `MODE_*` 事件常量等）—— 属阶段3/4 的预留骨架，非缺陷，但说明"架子先立起来"确实留了不少未接线符号（与 U-11 同源）。

### 1.3 验收核验脚本 · 核心部分（声称：8/8）

我独立执行 `python tools/verify_stage1.py`（release exe 7,216,640 B）：

```
PASS  1  应用能启动（窗口出现）
PASS  2  启动速度 < 3s          → 326 ms
PASS  6  自动建库 + migration   → config 表 13 行；schema_version=3；db.migration_version=1
PASS  5a sidecar 拉起 + /health → core port=54220, sidecar port=54223 → /health 200
PASS  5b 杀 sidecar 后主界面仍可用 → killed pids=[...]；core /health=200；窗口仍在
PASS  4a 配置写入（HTTP PUT ui.theme=dark）→ 原值='light'
PASS  4b 重启后主题仍为 dark     → 库中 ui.theme='"dark"'
PASS  1b 二次启动（热态）        → 308 ms
```

**复现结果：一致。**

### 1.4 验收核验脚本 · 路由 + ★ Widget（声称：验收 9/9，脚本 20/20）

我独立执行 `python tools/verify_stage1.py --routes-url http://localhost:5173 --widget-probe`（94s）：

```
PASS  3 /dashboard 渲染（标识 'Dashboard'）  marker=True nav=齐全 dom_len=11982
PASS  3 /ai 渲染（标识 'AI 助手'）           marker=True nav=齐全 dom_len=8055
PASS  3 /learning … /project … /profile … /life … /device … /plugins … /settings
PASS  8 ★ Widget 动态布局（点击→次数→尺寸）
      点击序列 use=['0','3','10'] size=['small','medium','large']（期望 ['small','medium','large']）
      最终落库='{"weather":10}'；落库值演变=['{"weather":1}','{"weather":10}']；clickErrors=[]
```

**复现结果：一致。** 9 条路由 + 1 条 ★ 项全部 PASS，★ 项的"点击→次数→尺寸"是**真实点击**（CDP 驱动 Edge），非模拟。

### 1.5 交付物（声称：msi + nsis）

独立枚举：

```
core/target/release/personal-workspace-core.exe            7,216,640 B
core/binaries/service-x86_64-pc-windows-msvc.exe           9,062,595 B
core/target/release/bundle/msi/…_0.1.0_x64_en-US.msi
core/target/release/bundle/nsis/…_0.1.0_x64-setup.exe
```

**复现结果：一致。**（文件大小量与 REPORT-005 §1.4 的 11.77MB / 10.80MB 同量级。）

### 1.6 补充核查：主路径能否落库（REVIEW-005 未单列，我补查）

★ 项的"使用次数写入 `config` 的 `ui.dashboard.usage`"要求主路径**键已登记**，否则 `ConfigService::set` 会按白名单拒绝、静默降级。我核对 `core/src/db/config.rs`：

```rust
pub const KEYS: &[&str] = &[ ..., "ui.dashboard.usage", "ui.dashboard.layout_locked", ... ];
pub fn expected_type(key: &str) -> &'static str {
    "ui.dashboard.usage"          => "object",
    "ui.dashboard.layout_locked"  => "boolean",
}
```

**结论：两键均已登记且类型明确，主路径可落地。** 这条排除了"UI 写了但 core 拒收"的隐患。

---

## 二、断言强度审读（审核的真正增值点）

核验脚本由被审方编写，天然可能"自证清白"。我逐段读 `tools/verify_stage1.py`（764 行），结论：**没有发现吞异常、弱断言或静默跳过的把戏**。具体：

| 检查点 | 脚本做法 | 评价 |
|--------|----------|------|
| ★ 项是否真实交互 | Edge CDP 建 WebSocket（手搓 RFC6455 帧）→ `Runtime.evaluate` 执行 `body.click()` | ✅ 真点击，非改 DOM 作弊 |
| 落库判据 | **轮询到收敛**（`weather===10` 才 break），而非"读到非空即过" | ✅ 直击 REVIEW-003 C-01 的并发写覆盖坑 |
| 数据库读取 | `sqlite3 connect('file:…?mode=ro', uri=True)` 只读 | ✅ 不违反"单一写入者" |
| 路由计数 | 用 `href="/x"` 而非 `class="nav-item"` 前缀计数（激活态会重排 class → 恒为 6） | ✅ 已踩过坑并写进注释 |
| Edge 缺失 | `find_edge()` 返回 None → 明确报 FAIL 并说明原因 | ✅ 不静默跳过 |
| 失败不掩盖 | 顶层 `except` 把异常记为 FAIL 项，`all_ok` 与各项取与 | ✅ 异常不会变成 PASS |
| 清理 | sidecar 显式 `taskkill`（只杀 baseline 之外的新 PID）；临时目录 rmtree | ✅ 不误伤、不残留 |

**唯一偏软处**：路由白屏判据 `app_filled = 'id="app"' in dom and len(dom) > 1500`。1500 字节阈值是启发式，理论上可被"渲染了但内容错"蒙混。但它与 `marker in dom`（页面标识文本）+ 7 个 nav href 齐全**联合判定**，实际强度足够；且 9 条路由的 `dom_len` 都在 7.9KB~12KB，远超阈值、量级一致。**不构成缺陷，记录备查。**

---

## 三、新发现（REVIEW-005 的 U 清单未覆盖的部分）

REVIEW-005 的 §5 已自曝 U-7（事件未桥接）/ U-8（重启后尺寸未断言）/ U-9（dev 未跑）/ U-11（符号级查不了），我逐条核对后**确认表述属实、无粉饰** —— 这一点本身值得肯定（呼应上一轮 REVIEW-003 的"自曝"传统）。

以下是我这轮**新发现**的：

| ID | 项 | 级别 | 说明 |
|----|----|:----:|------|
| **F-1** | **★ 验收项 8 的「调序锁定」半支无任何机器验证，却被标 ✅** | 一般 | 04 验收项 8 原文含两个子要求：(a) 点击→次数→尺寸；(b) **手动调序后 `layout_locked=true` 且不再自动改尺寸**。CDP 探针只点 `.widget-body`（走 `recordUse`），**从不触发 `moveUp/moveDown`**；前端连 `test` 脚本都没有（`ui/package.json` 仅 dev/build/typecheck/preview/tauri）。而 REVIEW-005 §6 六维表第 3 行把「`layout_locked` 冻结自动尺寸」标为 ✅ —— 属"代码读过就标过"，证据强度低于同表其他 ✅ 格。**实现本身是对的**（`autoSize()` 在 `layoutLocked` 时直接 return false，`moveUp/moveDown` 置位并持久化），但"标注口径"与"机器可判"不一致。**建议**：§6 该格降级为 ⚠️，并在 §5 补 `U-12`；`verify_stage1.py` 的探针容易扩：在点击后追加"触发一次调序按钮 → 断言 `ui.dashboard.layout_locked` 落库为 true → 再点 7 次断言尺寸不变"。 |
| **F-2** | 探针的"落库"是**浏览器降级层**，非 `config` 表、也非 invoke 主路径 | 一般 | 探针断言 `localStorage['pw.config.ui.dashboard.usage']`。核对 `client.ts` 注释：浏览器直开时，core HTTP API **不发 CORS 头**（有意为之），跨源 fetch 被拦 ⇒ 实际生效的是**localStorage 降级**。故：★ 项的"次数→尺寸"逻辑得到端到端验证，但"**写入 config 表 / 走 invoke**"这条真实主路径**在本阶段无任何运行时断言**，仅靠 typecheck + 门禁 W100 接线。这与 U-8/U-9/U-11 同源（皆属 M-3「存在冒充正确」的残留）。**建议**：登记为 U-13，阶段2 引入前端测试运行器后优先补。 |

> F-1 / F-2 都**不推翻**阶段1 的通过结论 —— ★ 的核心可判机制（高频大、低频小）已真实点击实测。
> 它们影响的是"✅ 这个词的成色"，不是"阶段1 有没有做完"。

---

## 四、判定

| 维度 | 复现结果 | 采信 |
|------|----------|:----:|
| 门禁 0F/0W/29P | 独立重跑一致 | ✅ 采信 |
| cargo test 6/6 | 独立重跑一致 | ✅ 采信 |
| 验收脚本核心 8/8 | 独立重跑一致 | ✅ 采信 |
| 验收脚本 路由+★ 20/20 | 独立重跑一致 | ✅ 采信 |
| 交付物（exe/sidecar/msi/nsis） | 独立枚举一致 | ✅ 采信 |
| 主路径键登记（补充核查） | 两键均已登记 | ✅ 采信 |
| 断言强度（脚本审读） | 无吞异常/弱断言把戏 | ✅ 采信 |
| **§6「layout_locked 冻结」标 ✅** | **无机器证据（F-1）** | ⚠️ **降级为"代码审查通过、未机器验证"** |

**总判定：阶段1「机器验收通过」成立。** REVIEW-005 的通过结论**予以确认**，并附加两条更正（F-1 降级、F-2 登记）。

**制度保留（不变）**：本判定由"同一主体 + 机器门禁"作出，**不具备独立审核效力**（M-5 未裁决）。若白宇需要真正的独立审核，请另起实例重审 —— 这是制度层问题，代码层修不了。

---

## 五、回填建议（供监制执行）

1. `LEDGER.md`：新增 `L-020`（F-1，`layout_locked` 半支无机器验证，阶段2 补探针）；审核历史加 006 行。
2. `REVIEW-005` §6 第 3 行：`layout_locked 冻结自动尺寸` 的 ✅ → ⚠️（附"未机器验证"）。
3. `REVIEW-005` §5：补 `U-12`（=F-1）、`U-13`（=F-2）。
4. `04-阶段指令-基础框架.md` 验收项 8 的补记：注明"调序锁定"半支当前由代码审查覆盖，探针待补。
5. **M-5 仍待白宇裁决** —— 未变。

---

*本报告由审核方复现产出；机器可判部分以 `tools/gate.py` 与 `tools/verify_stage1.py` 的**可复跑输出**为准，不以本报告措辞为准。*
