# Skin Engine Runtime（skin-system.md v1.0 落地）

> 日期：2026-09-14 · 状态：**已交付，验收 12/12**
> 工具：`tools/verify_skin_engine.py`（Edge headless + CDP）· 结果：`tools/skin-verify-results.json`
> 前置：TECH-01 Motion Runtime（`docs/tech/motion-runtime.md`）

## 一、架构位置（TECH-01 §十八 预留接口的实现）

```
Core Motion（不可变安全规则）
  → Motion Guard（data-motion / data-perf：硬设最终变量 —— 永远高于 Skin）
  → Skin Motion Profile（skin.ts：只写 --mt-skin-* 通道变量 + --accent）
  → Component Motion
```

## 二、核心机制：通道层（Guard 优先级的结构性保证）

`motion-tokens.css` 的 `:root` 最终值改为经通道转发（Guard 档位块一字未动）：

```css
--mt-intensity: var(--mt-skin-intensity, 1);
--mt-dur-quick: var(--mt-skin-dur-quick, 120ms);
/* Gate / instant / 派生幅度（press-scale / hover-lift）不设通道，Skin 无从触碰 */
```

- Skin 只写 `--mt-skin-*`（documentElement 内联样式）；
- `[data-motion='reduced'/'off']` 与 `[data-perf='emergency']` **硬设最终值**，
  不引用通道 —— skin intensity > 1 在 reduced/off 下被完全覆盖，
  无 JS 特判，T4/T5 实测（1.35 → 0.35 / 0）；
- 不引入 skin.css： Skin 值全部经内联自定义属性下发。

## 三、白名单（§四）

| 允许 | 范围 |
|------|------|
| intensity / drift / scaleOn | 0–2（intensity 允许 >1，Lively=1.35） |
| blur | 0–1 |
| duration | quick/base/panel/scene/cinematic 整数 ms 0–1000；**instant 不开放** |
| easing | standard/entry/exit（cubic-bezier/steps/关键字，x∈[0,1]） |
| stagger | 0–200 ms |
| accent | hex / rgb / hsl |

| 禁止（出现即整个 skin 拒绝） | 说明 |
|------|------|
| gate / dwell | Interactive Gate 与 Dwell 不开放 |
| instant / pressScale / hoverLift / cinema | instant 与派生幅度不可触碰 |
| layout / spacing / typography / radius / shadow / opacity / amplitude | 本轮范围外 |

未知字段 → 忽略 + warning；缺字段 → 缺省（Default 行为）；
schemaVersion ≠ 1 → 拒绝。

## 四、Loader / Registry / Apply

- **Loader**（`loadSkin`）：解析 + 白名单校验，返回 `{ok, warnings, errors, skin}`，
  非法值整单拒绝、不产生半套状态；
- **Registry**：内置 `default`（无覆盖）/ `calm`（intensity .7 / drift .4 / blur .2 / stagger 18 / accent #5b8def）
  / `lively`（intensity 1.35 / drift 1.5 / stagger 32 / quick 100ms / accent #ff6b3d）；
  `registerSkin` 可注册经 Loader 校验的自定义 skin；
- **Apply**（`applySkin(id)`）：只做 `data-skin` 属性 + 通道内联变量更新；
  **Default = 删除 data-skin + 精确移除本 skin 写入的属性**，即恢复；
  不调用 Page Transition / Cinema / View Transition / WAAPI（T6/T7 实证）。

## 五、验收（verify_skin_engine.py 12/12）

| 用例 | 结果 |
|------|------|
| T1 Default 无覆盖（无 data-skin、无内联通道、:root 原值） | PASS |
| T2a/b Calm·Lively 切换变量生效，Gate/instant 恒 240ms/0ms | PASS |
| T2c clear 恢复（accent/intensity 回基线） | PASS |
| T3 七类非法 skin（schema v2/gate/typography/instant/越界/非法 accent/easing）全拒绝，当前 skin 不变；未知字段忽略+warning | PASS |
| T4 reduced 压过 lively：intensity 1.35→**0.35**，回 standard 恢复 1.35 | PASS |
| T5 off 压过 skin：intensity/drift/blur=0，按钮 transition 0s | PASS |
| T6 切 skin childList=0、仅 :root 属性 ⊆{style,data-skin}（对照组差分排除页面异步噪声） | PASS |
| T7 vtCalls 不变、pendingAnims=false、零 transform/opacity 类动画 | PASS |

## 六、边界与未解决风险

1. **skin-system.md 原文不在本仓库**（同 #22 基线错位）——按任务规格实现；
   若原文在另一工作区，需同步入库后对齐字段命名（`scaleOn` vs `scale-on` 等）。
2. **accent 为主题无关覆盖**：经内联样式压过 tokens.css 的明暗主题映射，
   明暗两套主题共用 skin accent。若未来要求分主题 accent，需扩通道（schema 变更，本轮不做）。
3. **accent 切换的颜色微渐变**：按钮 `background-color var(--mt-dur-quick)` 会随变量
   传播渐变 —— 属组件级状态反馈而非 motion scene（T7 实测放行并记录）。
4. `DIV.dashboard` 偶发自身 style 写入（widget store 异步落地）与 Skin 无关，
   T6 用对照组差分排除；若后续该噪声变高频需另查。
5. 按指令**未实现**：skin 编辑器 / skin 市场 / 外部上传 UI / schema v2。
