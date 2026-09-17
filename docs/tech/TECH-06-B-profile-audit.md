# TECH-06-B · Part 2 —— 个人档案数据真实结构审计（只读，零代码修改）

> 日期：2026-09-16 · 性质：**审计**（本文件不含任何代码改动）
> 触发：TECH-06-B Part 2「开始前只读审计」
> 审计方法：**实读** `database/schema.sql`、`core/migrations/0006_profile.sql`、`core/src/profile/{mod,repository,export}.rs`、
> `ui/src/api/profileService.ts`、`ui/src/stores/profile.ts`、`ui/src/views/ProfileView.vue`，
> 并对全仓做 `profile_ext` / `profile_fields` 字符串检索（结果见 §〇）。

---

## 〇 审计总判

**指令里点名的三张表，只有一张真实存在。**

| 指令提到的表 | 仓库实况 |
|---|---|
| `profile_basic` | ✅ **存在**（`database/schema.sql:116`，0001 建库即有） |
| `profile_ext` | ❌ **全仓 0 命中**（检索 `.rs/.sql/.ts/.vue/.py/.md/.json`） |
| `profile_fields` | ❌ **全仓 0 命中** |

真实结构是**四张类型化表 + 一张建议队列表**，不是"basic + ext + fields"三段式：

```
profile_basic        单行（id=1）姓名/方向/兴趣/签名        ← 本轮审计主对象
profile_skills       技能（name 唯一 / level / category）
profile_projects     项目经历（tech_stack 为 JSON 数组文本）
profile_timeline     时间线事件
pending_suggestions  待确认建议队列（0006 新建，红线 V3 的表级落实）
```

---

## 一 五问逐条回答（全部有文件行号证据）

### 1. 昵称是否真实存储？—— ✅ 真实存储，但语义是 `name`（姓名）

- 列：`profile_basic.name TEXT`（`schema.sql:118`）。
- 读：`repository.rs:209` `SELECT name, direction, interests, motto, updated_at FROM profile_basic WHERE id = 1`。
- 写：`repository.rs:246` `basic_save(&BasicInput)` → `ON CONFLICT(id) DO UPDATE SET name=?1, ...`（upsert 单行）。
- UI：`ProfileView.vue:46/49` 的 `onboarding.name` / `basicForm.name` 直接绑定；`stores/profile.ts` 的
  `basic` 含 `name`。

**结论**：昵称**已经**真实落库（不是 mock、不是 localStorage）。所谓"昵称无法扩展"不是"没存"，而是
**字段集合封闭**（见 §二）。

### 2. 个性签名是否有字段？—— ✅ 有，就是 `motto`

- 列：`profile_basic.motto TEXT`（`schema.sql:121`）。
- Rust 单测直接把它当签名验：`repository.rs:822-831` 先存 `motto: "少废话"` 再 `basic_save` 改成
  `"改签名"` 并断言读回相等。
- UI：`ProfileView.vue:141` `signatureLeft = SIGNATURE_MAX - basicForm.motto.length`（有长度上限），
  `:512-514` `data-pw-motto` 渲染 `「{{ basic.motto }}」`；`export.rs:30-31` 导出为 Markdown 引用块
  `> {motto}`。

**结论**：签名字段齐备且全链路（DB → repo → 导出 → UI）已接。**不需要新增字段。**

### 3. 标签是否支持数组？—— ✅ 支持数组，但字段语义是"兴趣"不是通用"标签"

- 存储：`profile_basic.interests TEXT`，**存 JSON 数组字符串** ——
  写侧 `repository.rs:273` `serde_json::to_value(&interests)?`（数组直接序列化进 TEXT 列），
  读侧 `repository.rs:228-231`：值为字符串时 `serde_json::from_str::<Vec<String>>`（解析失败**降级为空数组**，
  不抛错）、值为数组时逐项取字符串。
- API：`profileService.ts:20` `interests: string[]`（**已经是数组类型**），`:29` `BasicInput.interests?: string[]`
  注释明确"不传 = 保持原值；传数组（可空）= 覆盖"。
- UI：`ProfileView.vue:197` `tagDraft = [...basic.value.interests]`、`:256` 保存 `interests: [...tagDraft]`、
  `:515` `data-pw-tags` 渲染。

**结论**：**数组能力已具备**（JSON-in-TEXT），且同款先例还有 `profile_projects.tech_stack`
（`schema.sql:140` TEXT + `profileService.ts:60` `techStack: string[]`）。
**唯一的不精确之处是语义**：这列叫 `interests`（兴趣），被 UI 当通用"标签"用。若将来要做"任意标签"，两条路：
① 就地把它改名为语义中性的字段（要动契约，代价 = 迁移 + 三处同步）；
② 新增一列/一张表承载"标签"，`interests` 保持原语义。**本轮不实施**（需求只要"审计"，且 B 阶段禁止大迁移）。

### 4. 头像如何存储？—— config 键 `profile.avatar`（单值偏好，不是列、不是二进制）

- 落点：`core/src/db/config.rs:122` 已登记键 `"profile.avatar"`，`expected_type = "string"`（`:179`），
  默认 `""`（`:239`）。
- 语义：**空串 = 用昵称首字母**；非空 = 一个预设 emoji 字符（`ProfileView.vue:62` `AVATAR_KEY`、
  `:140` `avatarChar = avatar || name.charAt(0)`、`:283-287` 写入走 `put_config`）。
- `profile_basic` 表**没有** `avatar` 列（`schema.sql:116-123` 六列逐一核对），且 `ProfileView.vue:57`
  注释写明"没有头像列。头像是一个单值偏好"。

**结论**：头像**没有**二进制入 DB（符合本轮红线），当前形态是"单字符偏好"。
**文件路径/资源 ID 引用方案**（本轮要求的方向）与现有形态**兼容且只是"值域扩展"**：
键不变、类型不变（仍 string）、默认值不变，只是把"emoji 字符"这一值域扩展成
"emoji | 文件路径 | 资源 ID"。**零迁移**（config 表已在，键已登记）。
若做此扩展，需要同步的只有两处：① UI 的头像选择器加"选图片"入口；② `ProfileView.vue` 的
`avatarChar` 渲染分支（emoji→字符 / 路径→`<img>`）。**本轮不实施**（指令只要求"建议"，Part 3 未授权动档案 UI）。

### 5. 扩展档案是否需要 JSON 字段？—— ❌ 不需要，且**加 JSON 列是倒退**

三条证据链：

1. **"局部数组"已有更轻的承载方式**：`interests` / `tech_stack` 都是 TEXT 存 JSON 数组 ——
   证明"某行内的一组值"用 TEXT 即可，**不必**升级成"结构化 JSON 文档列"。
2. **"结构化扩展"已有正确形态**：技能/项目/时间线是三张**类型化表**（列名、类型、约束都在 schema 里），
   `pending_suggestions.payload` 存 JSON 是**例外**且理由充分（确认前结构未知，确认时才落正式表，
   由 `repository.rs` 的 `apply_suggestion` 按 kind 校验）。把"正式档案"也改成 JSON 列，
   等于把**校验、查询、导出**的责任全部推给前端 —— `export.rs` 的 Markdown 导出会退化为
   "遍历未知 JSON"，`ai_context`（喂给 AI 的档案上下文）也无法再写类型化 SQL。
3. **单值偏好另有通道**：`config` 键（`profile.avatar` 即先例）承载"非结构化单值"，
   不该进档案表。

**给未来的建议**（本轮零实施）：若确有"用户自定义键值字段"需求，**新增一张
`profile_fields(profile_id, field_key, value, ...)` 表**（正好对上指令里那个不存在的表名），
而不是给 `profile_basic` 加 JSON 列 —— 表形态可用 SQL 查询、可逐字段校验、可按字段做导出白名单。
在它出现之前，"扩展"应走**既有三表加列**的既有路径（0006 就是这么干的：`ALTER TABLE profile_skills ADD COLUMN category`）。

---

## 二 "档案字段无法真正扩展"的真实根因（Part 1 之外的登记项）

扩展一个档案字段今天需要**动四处 + 一次迁移**：

| # | 落点 | 现状 |
|---|---|---|
| 1 | `database/schema.sql` + 新迁移 | `ALTER TABLE ... ADD COLUMN` |
| 2 | `core/src/profile/repository.rs` | `BasicInput` 结构体、`basic_get` 的 SELECT、`basic_save` 的 INSERT/UPDATE |
| 3 | `ui/src/api/profileService.ts` | `ProfileBasic` / `BasicInput` 接口 |
| 4 | `ui/src/views/ProfileView.vue` | 表单 + 渲染 |

另有**隐含第 5 处**：`pending_suggestions` 的 `kind` 取值域（`timeline|skill|project`）是
**代码白名单**（`core/src/profile/mod.rs` 的 apply 分发），新增档案维度必须同步扩它，否则
采集器永远建议不出新字段。

**这不是缺陷，是"契约"的代价** —— 每个字段都是契约（`model.ts` 的同款哲学）。但应**显式**承认：
"无法真正扩展"= **扩展是显式契约变更，不是配置项**。本轮不改变这一点（Part 3 禁止），只在
`TECH-06-B-model-persistence.md` 的"下一阶段建议"里登记为候选方向。

---

## 三 本轮结论

| 问题 | 答案 | 是否需要本轮动手 |
|---|---|---|
| 昵称真实存储？ | ✅ `profile_basic.name` | 否 |
| 签名字段？ | ✅ `profile_basic.motto`，全链路已接 | 否 |
| 标签数组？ | ✅ `interests`（TEXT 存 JSON 数组），语义是"兴趣" | 否（语义扩展另立项） |
| 头像存储？ | config 键 `profile.avatar`（string，非列非二进制） | 否（值域扩展另立项，零迁移） |
| 扩展档案要 JSON 字段？ | ❌ 不需要；JSON 列是倒退，扩展走"加列/加表/加 config 键" | 否 |

**Part 2 = 纯审计，零代码、零迁移、零 UI 改动** —— 与指令"开始前只读审计"一致。
