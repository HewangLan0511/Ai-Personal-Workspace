# TECH-06-B 交付报告：模型数据持久化 + 档案真实数据审计

> 状态：**已完成（B 段收口，未进入 C）** ｜ 契约：**v12 → v13** ｜ 验收：`tools/verify_tech06b.py` **48/48** ｜ 回归：**11/11 套件全绿**

---

## 0. 范围声明

本报告只覆盖 TECH-06-B 的 Part 1（模型清单持久化）与 Part 2（个人档案只读审计）。
**Part 3 所列六项（模型市场 / 自动下载 / Agent 执行 / 插件商城 / 工作空间真实恢复 / life 插件体系）本轮一律未实现**，需要各自的设计阶段。

---

## 1. 文件变化列表

### 新增（3 个）

| 文件 | 作用 |
|---|---|
| `ui/src/ai/model/archive.ts` | 归档形态**唯一定义**：`ARCHIVE_KEY` / `serializeArchive` / `parseArchive` / `materializeArchiveRecord`。纯模块（零框架依赖，可被 Node 直编） |
| `tools/verify_tech06b.py` | Part 1 验收脚本（四层证据：Node 直驱 / 静态 / dist 动态 / 真 core 双启动） |
| `docs/tech/TECH-06-B-profile-audit.md` | Part 2 档案审计（只读，未改任何档案代码） |

### 修改（7 个）

| 文件 | 变化 |
|---|---|
| `ui/src/ai/model/registry.ts` | `ArchivePort` 接口 + `loadArchive()`（hydrate 时恢复）+ `scheduleArchivePersist()`（串行落盘队列）+ `getArchiveState()` / `archiveFlushed()`；`add/update/remove/clear` 接线落盘 |
| `ui/src/ai/model/ports.ts` | `coreArchivePort()`（走既有 `get_config`/`put_config`，带 inTauri 守卫）；`createCoreModelRegistry` 注入 archive；`memoryPorts` 支持测试注入口 |
| `core/src/db/config.rs` | `ai.models.registry` 三处登记：`KEYS` / `expected_type="string"` / `default_for=""` |
| `core/src/db/migrations.rs` | `CONTRACT_SCHEMA_VERSION` 12 → **13**（无表结构变更 ⇒ 不写迁移 SQL） |
| `docs/agent-dev/03-数据契约与接口规范.md` | 键行 + v13 变更记录 + 当前版本号 |
| `tools/verify_tech04.py` | T2f 契约版本判据 `== 12` → `>= 12`（动态读取，消除逐轮手改） |
| `docs/reviews/LEDGER.md` | TECH-06-B 记账（见 §5） |

### 明确不做的（防第二事实源）

- ❌ localStorage 存模型（T2a 全仓 0 处红线检查）
- ❌ 页面自己存模型（T1e：模型页零归档访问）
- ❌ 新增 core 命令 / 数据库迁移 / 新页面（T4a/T4b/T5b：16 路由 16 视图与 A 段基线一致）

---

## 2. 数据流变化

### 之前（问题态）

```
ModelsView → ModelRegistry（纯内存 store）→ 刷新/重启 → ❌ 清单清空
hydrate() 只灌 Provider/凭据/canonical，从不灌模型
```

### 之后

```
写入：add/update/remove/clear ──→ scheduleArchivePersist()
        （同步签名不变，落盘是异步旁路）
          └→ serializeArchive(按 id 排序，确定性) ──串行队列 persistChain──→
             ArchivePort.write ──→ core put_config("ai.models.registry") ──→ SQLite config 表

读取：hydrate() ──→ ArchivePort.read ──→ parseArchive（永不抛错，坏一条丢一条+记 issue）
        └→ materializeArchiveRecord（恢复语义：不查 Provider 表、不补缺省端点）
             └→ status 恒为「未测试」= available:false + 无 lastError（反假绿）

fail-closed：read() 抛错（core 不可达）⇒ archiveState=unreadable ⇒
             scheduleArchivePersist 直接 return —— 读不到就拒绝写，绝不把空清单写回去清库
```

关键设计点：

1. **单一事实源不变**：谁读谁写只有 `ModelRegistry` 一处；归档模块只定义序列化形态。
2. **探测状态结构上不可持久化**：`ArchiveRecord` 接口没有 `available/lastCheck/lastError` 字段（T3e 静态锁定）。重启后模型一律显示「未测试」，等真实探测给结论——延续 TECH-06-A 的 288 组合穷举纪律。
3. **`enabled`（用户意图）是唯一被持久化的 status 语义**：停用的模型重启后仍「离线」。
4. **canonical（`ai.model.current`）照旧**，恢复后校验不 dangling（④ 项：default 指向的模型实体必须还在）。

---

## 3. 架构影响

- **契约面**：+1 个 config 键（`ai.models.registry`，string 型），契约 v13。没有新命令、没有新表、没有新迁移文件（仍止于 0008）。
- **模块面**：`ai/model/` 域内新增一个纯模块；域外零引用（T3a 检索锁定——归档的运行期消费方只有 ai/model/ 域内）。
- **core 面**：只扩了 config 白名单三处登记（KEYS / expected_type / default_for），现有类型守卫与键白名单对它照常生效（C4 实证：数组被拒、未登记键被拒）。
- **UI 面**：零改动。模型页/AI 侧栏照旧只碰 Registry，调用方零迁移（add/update/remove 同步签名未变）。

## 4. 风险登记

| # | 风险 | 等级 | 对策/现状 |
|---|---|---|---|
| R-1 | config 表 string 键的存储形态是 serde_json::Value 编码（单元=带引号转义的 JSON 字符串字面量），直读 SQLite 与 API 读回不等价 | 低 | 已在验收 C3 显式建模（解码后逐字节比对）；契约文档键行已注明 string 语义 |
| R-2 | 归档写失败（磁盘满/权限）只记入 `archiveState.writeError`，UI 当前无强提示 | 低 | 本会话内内存态仍是权威，下次变更会重试落盘；UI 提示留待 UI 轮次（不阻塞） |
| R-3 | 归档格式 v1 若未来演进，旧版本串会被「按空清单处理」（不猜） | 低 | `ARCHIVE_VERSION` 显式拒绝 + 记 issue；升级时需写显式迁移路径 |
| R-4 | `profile_ext`/`profile_fields` 在指令中被点名但**仓库中不存在**——扩展档案需另行设计 | 记录 | 详见 `TECH-06-B-profile-audit.md`：真实结构是 4 张类型化表 + 建议队列，JSON 扩展列暂无必要 |
| R-5 | 验收基建坑：重启场景下 config 表里的 `runtime.http_port` 是上一实例残留值 | 已修 | `verify_tech06b.py::boot()` 改为「读到端口 + HTTP 探活 200」双条件（stage3 同坑的既有先例） |

## 5. 自动化验证（机器证据）

**`tools/verify_tech06b.py` — 48/48 PASS**，四层证据：

| 层 | 证明内容（摘要） |
|---|---|
| ① Node 直驱（真编译 registry/archive） | 落盘→同实例字节级往返；重启 3/3 恢复、身份逐字段保真；探测过→connected 但重启后回「未测试」（反假绿）；enabled 持久；current model 不丢不 dangling；删除无残留；core 不可达→unreadable+拒写；坏归档六类容错不崩 |
| ② 静态 T1~T5 | 唯一定义/唯一键名/组合根接线；全仓 0 localStorage 写模型；core 三处登记+契约 v13+文档同步；add/update/remove/clear 四路落盘接线+fail-closed 守卫；零新命令/零新迁移；UI 冻结（16 路由 16 视图、零裸色值） |
| ③ dist 动态（Edge headless + CDP） | 最终产物里加模型**零** localStorage 写入；无 core 时如实报 unreadable（不假装已保存）；产品内真值 `archiveKey()=ai.models.registry` |
| ④ 真 core 双启动 | 隔离 `PW_DATA_DIR` → PUT/GET 逐字节往返 → SQLite 直读（JSON 编码形态）→ 类型守卫/白名单生效 → **terminate 进程→重新 boot→值仍在**、schema_version 仍 13 |

**回归（同轮全绿 11/11）**：gate、tech01（9/9）、tech02_workspace、tech03b（81/81，含 vue-tsc）、tech04（44/44）、tech05c、tech05d、model_registry（含 vue-tsc + vite build 整仓构建）、contracts（6/6）、skin_engine（12/12）、tech06a。core `cargo test --release` 另行通过（config 契约自检两条在内）。

## 6. 给下一阶段（C）的建议

1. **档案扩展**（若进入 C 的档案部分）：按 profile-audit 的结论走「加列/加表」而不是 JSON 大列；头像只存引用（路径/资源 ID）。
2. **UI 轮次**：归档写失败（`getArchiveState().writeError`）可在模型页给一条弱提示；属于 UI 变更，需走 UI 冻结豁免。
3. **验收基建**：凡做「重启」类验收，端口等待一律用「读端口 + HTTP 探活」双条件，不要信 config 表里的旧端口值。

---

*停止条件遵从：B 段完成即停，未进入 C。*
