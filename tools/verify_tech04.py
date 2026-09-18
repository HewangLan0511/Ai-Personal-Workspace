#!/usr/bin/env python3
"""TECH-04 验收 · 核心能力接入规划与第一阶段落地（T1~T4）。

## 这一轮在验什么
TECH-04 的题目是"把已经设计好的 Runtime 接进真实产品"。分三块：

| 组 | 验的是 | 手段 |
|----|--------|------|
| T1 | **AI 模型系统真实闭环**：canonical 成为请求依据；「显示模型 == 实际调用模型」 | **Node 直驱 `selection.ts` + `session.ts`**（真 ModelRegistry + 假端口） |
| T2 | canonical 的**正式落点**与**迁移路径**：L1 已登记、镜像仍兼容、老值可前向搬运 | Node 直驱（含"未登记 L1"的旧行为对照组）+ 静态契约文档核对 |
| T3 | WorkspaceSnapshot 接入 `workspaceRuntime` 门面（只读三视图，零执行入口） | 静态（门面形状 + 禁止项 + 消费者白名单未被破坏） |
| T4 | 禁止项：无大规模重构 / 无新 UI 页面 / 无新动画体系 | 静态（路由基线 / 视图完整 / keyframes 基线 / 迁移数不变） |

## 反"假通过"的设计
1. **每个否定断言都配对照组**：说"不写 canonical"，就必须同时证明"该写的时候确实写了"；
2. **旧行为对照组**：T2 用 `l1Registered:false` 复现 TECH-03 时期（写不进去 → 落镜像），
   证明"迁移成功"不是因为"反正都会成功"；
3. **不宣称端到端**：真实 Tauri + 真 config 表的闭环由既有 `verify_stage5.py` 覆盖；
   本轮验的是"决策与编排"（那正是本次改动的全部内容）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
SRC = UI / "src"
TSC = UI / "node_modules" / "typescript" / "lib" / "tsc.js"

ENTRY_FILES = [
    "ai/model/model.ts",
    "ai/model/provider.ts",
    "ai/model/registry.ts",
    "ai/model/selection.ts",
    "ai/model/session.ts",
    "ai/model/consumer.ts",
    "workspace/snapshot.ts",
]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def node() -> str:
    """找 node.exe —— **不硬编码盘符/用户名**（门禁 A020/A021 会判违规）。"""
    cands: list[str] = []
    env_node = os.environ.get("NODE_EXE")
    if env_node:
        cands.append(env_node)
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    versions = Path(home) / ".workbuddy" / "binaries" / "node" / "versions"
    if versions.is_dir():
        cands += [str(v / "node.exe") for v in sorted(versions.iterdir(), reverse=True)]
    pf = os.environ.get("ProgramFiles")
    if pf:
        cands.append(str(Path(pf) / "nodejs" / "node.exe"))
    which = shutil.which("node")
    if which:
        cands.append(which)
    for cand in cands:
        if cand and Path(cand).exists():
            return str(cand)
    raise RuntimeError("找不到 node.exe")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def read_src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)//[^\n]*", "", text)
    return text


# ---------------------------------------------------------------- T0 编译


def compile_entries(tmp: Path) -> None:
    if not TSC.exists():
        raise RuntimeError(f"缺少 typescript 编译器：{TSC}（先 npm install）")
    args = [
        node(), str(TSC),
        "--target", "ES2022", "--module", "commonjs", "--moduleResolution", "node",
        "--strict", "--esModuleInterop", "--skipLibCheck",
        "--rootDir", str(SRC), "--outDir", str(tmp),
        *[str(SRC / f) for f in ENTRY_FILES],
    ]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(UI), timeout=240)
    if proc.returncode != 0:
        raise RuntimeError(f"tsc 编译失败（exit {proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    for f in ENTRY_FILES:
        out = tmp / f.replace(".ts", ".js")
        if not out.exists():
            raise RuntimeError(f"编译产物缺失：{out}")


def run_js(tmp: Path, name: str) -> list[tuple[str, bool, str]]:
    proc = subprocess.run([node(), str(tmp / name)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(tmp), timeout=240)
    out = proc.stdout or ""
    marker = [ln for ln in out.splitlines() if ln.startswith("__PW_RESULT__")]
    if not marker:
        raise RuntimeError(
            f"{name} 未产出结果（exit {proc.returncode}）\nSTDOUT:\n{out[-2500:]}\n"
            f"STDERR:\n{(proc.stderr or '')[-2500:]}"
        )
    payload = json.loads(marker[-1][len("__PW_RESULT__"):])
    return [(c[0], bool(c[1]), str(c[2])) for c in payload["checks"]]


# ---------------------------------------------------------------- Node 夹具

FAKE_PORTS_JS = r"""
const { ModelRegistry } = require('./ai/model/registry.js');

const PROVS = [
  { id: 'openai',   label: 'OpenAI',   defaultEndpoint: 'https://api.openai.com/v1',
    defaultModel: 'gpt-5', needsKey: true,  enabled: true, note: '', capabilities: ['chat','stream','models'] },
  { id: 'deepseek', label: 'DeepSeek', defaultEndpoint: 'https://api.deepseek.com/v1',
    defaultModel: 'deepseek-chat', needsKey: true, enabled: true, note: '', capabilities: ['chat','stream','models'] },
  { id: 'ollama',   label: 'Ollama',   defaultEndpoint: 'http://localhost:11434',
    defaultModel: 'qwen2.5:7b', needsKey: false, enabled: true, note: '', capabilities: ['chat','stream','models'] },
];

/**
 * 造一副假端口。
 * opt.l1Registered === false ⇒ 复刻 TECH-03 时期（L1 键未登记 ⇒ 写它 bail ⇒ 落镜像）。
 * opt.mirror = {p, m} ⇒ 预置老数据（只写过镜像键的用户）。
 */
function makeRegistry(opt) {
  const o = opt || {};
  const l1 = new Map();
  const mirror = new Map();
  const creds = new Set();
  const st = { l1Registered: o.l1Registered !== false, cache: null };
  if (o.mirror) { mirror.set('p', o.mirror.p); mirror.set('m', o.mirror.m); }
  if (o.l1) { l1.set('p', o.l1.p); l1.set('m', o.l1.m); }
  if (o.cache !== undefined) st.cache = o.cache;

  const ports = {
    io: { async listRemoteModels() { return []; } },
    capability: {
      async loadProviders() { return PROVS; },
      async loadSecretPresence() { return [...creds]; },
    },
    canonical: {
      keys: { provider: 'ai.provider.current', model: 'ai.model.current' },
      mirrorKeys: { provider: 'ui.ai.provider', model: 'ui.ai.model' },
      async read() {
        const p = l1.get('p') || '', m = l1.get('m') || '';
        if (p || m) return { values: { provider: p, model: m, apiBase: '' }, from: 'core' };
        const mp = mirror.get('p') || '', mm = mirror.get('m') || '';
        if (mp || mm) return { values: { provider: mp, model: mm, apiBase: '' }, from: 'mirror' };
        return null;
      },
      async write(patch) {
        if (!st.l1Registered) {
          // 旧行为：L1 键未登记 ⇒ put_config 会 bail ⇒ 端口落回过渡镜像键
          if (patch.provider !== undefined) mirror.set('p', patch.provider);
          if (patch.model !== undefined) mirror.set('m', patch.model);
          return { landedOn: 'mirror' };
        }
        if (patch.provider !== undefined) l1.set('p', patch.provider);
        if (patch.model !== undefined) l1.set('m', patch.model);
        return { landedOn: 'core' };
      },
    },
    cache: {
      read() { return st.cache; },
      write(v) { st.cache = v; },
      clear() { st.cache = null; },
    },
    secret: {
      refFor: (id) => 'pw/' + id + '/default',
      async has(id) { return creds.has(id); },
      async set(id) {
        creds.add(id);
        return { provider: id, ref: 'pw/' + id + '/default', mask: '****', backend: 'memory' };
      },
      async remove(id) { return creds.delete(id); },
    },
    now: () => 1700000000000,
  };
  return { ports, st, l1, mirror, registry: () => new ModelRegistry(ports) };
}
module.exports = { makeRegistry, PROVS };
"""

# ---------------------------------------------------------------- T1/T2 harness

CHAIN_JS = r"""
'use strict';
const { makeRegistry } = require('./fixture.js');
const { resolveSelection, needsMigration, sameSelection } =
  require('./ai/model/selection.js');
const { createModelSession } = require('./ai/model/session.js');
const { resolveCurrentModel, createModelReadOnly } = require('./ai/model/consumer.js');

const checks = [];
function check(name, passed, detail) { checks.push([name, !!passed, String(detail)]); }
const J = (x) => JSON.stringify(x);

(async () => {
  // ================================================================ T1 数据链闭环

  // ① 纯决策：四种组合（表格全覆盖）
  {
    const empty = { provider: '', model: '', apiBase: '' };
    const selA = { provider: 'deepseek', model: 'deepseek-chat', apiBase: '' };
    const canA = { provider: 'openai', model: 'gpt-5', apiBase: '', source: 'core', stale: false, pendingSync: false };

    const r0 = resolveSelection(empty, empty);
    check('t1-a 两者皆空 → none（不做任何写）',
          r0.source === 'none' && !r0.writeCanonical && !r0.adoptIntoSelection, J({ src: r0.source }));

    const r1 = resolveSelection(empty, selA);
    check('t1-b canonical 空 + 界面有 → 采用界面选择并**前向写 canonical**',
          r1.source === 'selection' && r1.writeCanonical === true && r1.adoptIntoSelection === false
          && sameSelection(r1.target, selA), J({ src: r1.source, write: r1.writeCanonical }));

    const r2 = resolveSelection(canA, empty);
    check('t1-c canonical 有 + 界面空 → 以 canonical 为准并让界面跟随',
          r2.source === 'canonical' && r2.writeCanonical === false && r2.adoptIntoSelection === true
          && sameSelection(r2.target, canA), J({ src: r2.source, adopt: r2.adoptIntoSelection }));

    const r3 = resolveSelection(canA, selA);
    check('t1-d 两者都有且不一致 → **收敛到 canonical**（落点是唯一事实来源）',
          r3.source === 'canonical' && r3.adoptIntoSelection === true
          && sameSelection(r3.target, canA), J({ target: r3.target, src: r3.source }));

    const r4 = resolveSelection(canA, { provider: 'openai', model: 'gpt-5', apiBase: '' });
    check('t1-e 两者一致 → 无操作（不产生多余写入）',
          r4.source === 'canonical' && !r4.writeCanonical && !r4.adoptIntoSelection, J({ src: r4.source }));
  }

  // ② 首次落点：canonical 为空时，界面选择被写进落点（L1）
  {
    const f = makeRegistry();
    const sess = createModelSession(f.registry());
    await sess.ready();
    check('t1-f 起始态：canonical 未设置（current() === null）', sess.current() === null,
          J(sess.current()));

    const r = await sess.resolveAtBoot({ provider: 'deepseek', model: 'deepseek-chat', apiBase: '' });
    const after = sess.current();
    check('t1-g 启动解析：采用界面选择并写入落点（source 变 core）',
          r.source === 'selection' && r.wroteCanonical === true
          && after && after.source === 'core' && after.provider === 'deepseek',
          J({ src: r.source, wrote: r.wroteCanonical, after: after && after.source }));

    check('t1-h 落点里确实是规范化的 provider id',
          f.l1.get('p') === 'deepseek' && f.l1.get('m') === 'deepseek-chat',
          J({ p: f.l1.get('p'), m: f.l1.get('m') }));
  }

  // ③ 显示 == 调用：canonical 与界面选择冲突时，**显示的与发出的一致**
  {
    const f = makeRegistry({ l1: { p: 'openai', m: 'gpt-5' } });
    const reg = f.registry();
    const sess = createModelSession(reg);
    await sess.ready();
    // 界面侧是旧 localStorage 值（deepseek）
    const r = await sess.resolveAtBoot({ provider: 'deepseek', model: 'deepseek-chat', apiBase: '' });
    const canonical = sess.current();

    check('t1-i 冲突时以 canonical 为准（界面旧值不覆盖落点）',
          r.source === 'canonical' && r.selection.provider === 'openai'
          && r.selection.model === 'gpt-5' && r.adopted === true,
          J({ src: r.source, sel: r.selection }));

    // 顶栏显示（consumer 投影）必须与"本次请求依据"逐字段相同
    const view = resolveCurrentModel(reg);
    check('t1-j **显示模型 == 实际调用模型**（顶栏投影 vs 请求依据，逐字段一致）',
          view.canonical.provider === r.selection.provider
          && view.canonical.model === r.selection.model
          && view.canonical.provider === canonical.provider
          && view.canonical.model === canonical.model,
          J({ 顶栏: view.canonical, 请求: r.selection }));

    check("t1-k 顶栏能显示出来（模型已随 canonical 登记，不误报「已失效」）",
          view.dangling === false && view.set === true && view.label === 'gpt-5' && view.badge === '',
          J({ label: view.label, badge: view.badge, dangling: view.dangling }));

    // 对照组：若**不**登记模型，顶栏会误报「已失效」—— 证明上一条不是白给的
    const reg2 = f.registry();
    await reg2.hydrate();
    await reg2.setCanonical({ provider: 'openai', model: 'gpt-5', apiBase: '' });
    const view2 = resolveCurrentModel(reg2);
    check('t1-l 对照组：不登记模型时顶栏确实会报「已失效」（证明 t1-k 有区分度）',
          view2.dangling === true && view2.badge === '已失效',
          J({ badge: view2.badge, dangling: view2.dangling }));
  }

  // ④ 运行期跟随：canonical 被别处改掉后，会话能感知（订阅）
  {
    const f = makeRegistry();
    const reg = f.registry();
    const sess = createModelSession(reg);
    await sess.ready();
    await sess.resolveAtBoot({ provider: 'deepseek', model: 'deepseek-chat', apiBase: '' });

    const seen = [];
    const off = sess.subscribe((c) => seen.push(c ? c.provider + '/' + c.model : 'null'));
    await reg.setCanonical({ provider: 'openai', model: 'gpt-5', apiBase: '' });
    await new Promise((r) => setTimeout(r, 0));
    check('t1-m 运行期 canonical 被改 → 订阅者拿到新值（会话可跟随）',
          seen.indexOf('openai/gpt-5') >= 0, J(seen));

    // 只读面拿到的也是新值（顶栏与订阅同源）
    const ro = createModelReadOnly(reg);
    check('t1-n 只读面与订阅读到同一个落点（同源，不可能分叉）',
          ro.current().canonical.provider === 'openai', J(ro.current().canonical));
    off();
  }

  // ================================================================ T2 落点与迁移

  // ① 老数据（只写过镜像键）→ 能读出来
  {
    const f = makeRegistry({ mirror: { p: 'deepseek', m: 'deepseek-chat' } });
    const sess = createModelSession(f.registry());
    await sess.ready();
    const c = sess.current();
    check('t2-c 老数据可读（只写过镜像键时 source=mirror / pendingSync=true）',
          c && c.source === 'mirror' && c.pendingSync === true && c.provider === 'deepseek',
          J(c));
  }

  // ② 迁移路径：前向搬运到 L1，且**不删旧值**
  {
    const f = makeRegistry({ mirror: { p: 'deepseek', m: 'deepseek-chat' } });
    const sess = createModelSession(f.registry());
    await sess.ready();
    const before = sess.current();
    const mg = await sess.migrateIfNeeded();
    const after = sess.current();
    check('t2-d 迁移路径可用：镜像 → L1（source mirror→core，pendingSync 转 false）',
          before.source === 'mirror' && mg.migrated === true && mg.from === 'mirror'
          && after.source === 'core' && after.pendingSync === false,
          J(mg));
    check('t2-e **旧镜像键的值仍保留**（不删旧值 → 老版本回滚可跑）',
          f.mirror.get('p') === 'deepseek' && f.mirror.get('m') === 'deepseek-chat',
          J({ p: f.mirror.get('p'), m: f.mirror.get('m') }));
    check('t2-f 迁移幂等：第二次调用不再搬（no-op）',
          (await sess.migrateIfNeeded()).migrated === false, 'noop');
  }

  // ③ 对照组：L1 未登记（TECH-03 时期的行为）→ 搬不过去，如实报"没成"
  {
    const f = makeRegistry({ l1Registered: false, mirror: { p: 'deepseek', m: 'deepseek-chat' } });
    const sess = createModelSession(f.registry());
    await sess.ready();
    const mg = await sess.migrateIfNeeded();
    const after = sess.current();
    check('t2-g 对照组：L1 未登记时迁移不成功（source 仍 mirror）——证明 t2-d 非"反正都成功"',
          mg.migrated === false && after.source === 'mirror',
          J({ mg, after: after.source }));
  }

  // ④ 未设置时不迁移（不无中生有）
  {
    const f = makeRegistry();
    const sess = createModelSession(f.registry());
    await sess.ready();
    const mg = await sess.migrateIfNeeded();
    check('t2-h canonical 从未设置 → 不迁移（no-op，不写空值）',
          mg.migrated === false && sess.current() === null, J(mg));
  }

  // ⑤ 契约：canonical 不得指向未注册 / 未开放的 Provider
  {
    const f = makeRegistry();
    const reg = f.registry();
    const sess = createModelSession(reg);
    await sess.ready();
    const r1 = await sess.syncSelection({ provider: 'ghost', model: 'x', apiBase: '' });
    check('t2-i 写 canonical 拒绝未注册 Provider（syncSelection 返回 null，落点不变）',
          r1 === null && sess.current() === null, J({ ret: r1, cur: sess.current() }));
    const r2 = await sess.syncSelection({ provider: '', model: 'x', apiBase: '' });
    check('t2-j 空 provider 不写（不产生"半个 canonical"）', r2 === null, J(r2));
  }

  // ⑥ 界面改选择 → 落点同步变（这就是"写进 canonical 才算数"）
  {
    const f = makeRegistry();
    const reg = f.registry();
    const sess = createModelSession(reg);
    await sess.ready();
    await sess.resolveAtBoot({ provider: 'deepseek', model: 'deepseek-chat', apiBase: '' });
    const snap = await sess.syncSelection({ provider: 'openai', model: 'gpt-5', apiBase: '' });
    const c = sess.current();
    check('t2-k 用户改选择 → canonical 随即更新（显示与调用同时变）',
          snap !== null && snap.source === 'core' && c.provider === 'openai' && c.model === 'gpt-5',
          J({ src: snap && snap.source, cur: c }));
  }

  // ⑦ needsMigration 纯判据
  {
    check('t2-l needsMigration 只在"有值且真身不在 L1"时为真',
          needsMigration({ provider: 'a', model: 'b', source: 'mirror' }) === true
          && needsMigration({ provider: 'a', model: 'b', source: 'cache' }) === true
          && needsMigration({ provider: 'a', model: 'b', source: 'core' }) === false
          && needsMigration({ provider: '', model: '', source: 'core' }) === false,
          '四条判据');
  }

  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
})().catch((e) => {
  checks.push(['chain EXCEPTION', false, String((e && e.stack) || e)]);
  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
});
"""


# ---------------------------------------------------------------- T2/T3/T4 静态


def t2_static() -> None:
    config_rs = read("core/src/db/config.rs")
    l1_ok = {}
    tail_type = config_rs.split("fn expected_type")[-1].split("fn type_ok")[0]
    tail_default = config_rs.split("fn default_for")[-1]
    for k in ("ai.provider.current", "ai.model.current"):
        in_keys = ('"%s"' % k) in config_rs
        in_type = bool(re.search(r'"%s"' % re.escape(k), tail_type))
        in_default = bool(re.search(r'"%s"\s*=>' % re.escape(k), tail_default))
        l1_ok[k] = bool(in_keys and in_type and in_default)
    check("T2a canonical L1 键已在 core 三处登记（KEYS / expected_type / default_for）",
          all(l1_ok.values()), json.dumps(l1_ok, ensure_ascii=False))

    mirror_kept = ('"ui.ai.provider"' in config_rs) and ('"ui.ai.model"' in config_rs)
    check("T2b 过渡镜像键保留在 core 登记表（镜像兼容不破坏）", mirror_kept,
          "ui.ai.provider / ui.ai.model 仍在 KEYS")

    store = strip_comments(read_src("stores/ai.ts"))
    still_persist = ("persist(PROVIDER_KEY" in store) and ("persist(MODEL_KEY" in store)
    check("T2c AI store 仍写镜像键（老版本回滚可读）+ 同时写落点", still_persist,
          "既有 persist 调用保留")

    ports = read_src("ai/model/ports.ts")
    l1_first = ports.index("writePair(L1_KEYS") < ports.index("writePair(MIRROR_KEYS")
    check("T2d 写序：先 L1，失败才落镜像（落点优先，兼容兜底）", l1_first,
          "writePair(L1_KEYS) 在 writePair(MIRROR_KEYS) 之前")

    doc = read("docs/agent-dev/03-数据契约与接口规范.md")
    doc_rows = ("`ai.provider.current`" in doc) and ("`ai.model.current`" in doc)
    doc_ver = "**v12**" in doc
    check("T2e 契约文档已更新（§3.1.1 两行 + 变更记录 v12）", doc_rows and doc_ver,
          json.dumps({"键行": doc_rows, "v12行": doc_ver}, ensure_ascii=False))

    mig_rs = read("core/src/db/migrations.rs")
    m_ver = re.search(r"CONTRACT_SCHEMA_VERSION:\s*i64\s*=\s*(\d+)", mig_rs)
    ver = int(m_ver.group(1)) if m_ver else -1
    # TECH-06-B 显式记账：`== 12` 放宽为 `>= 12`（沿 verify_stage9 `== 11 → >= 11` 先例）。
    # 意图不变 —— "登记 canonical 键 ⇒ 契约确实升过版"；v13 是模型清单键 ai.models.registry。
    check("T2f 契约版本常量 ≥ 12（v12=canonical 键；TECH-06-B 已升 v13=模型清单键）",
          ver >= 12,
          f"CONTRACT_SCHEMA_VERSION = {ver}")

    mig = sorted(p.name for p in (ROOT / "core" / "migrations").glob("*.sql"))
    check("T2g 未新增数据库迁移（仍止于 0008）",
          bool(mig) and mig[-1] == "0008_plugin_audit.sql",
          json.dumps({"count": len(mig), "last": mig[-1] if mig else None}, ensure_ascii=False))


def t3_snapshot_facade() -> None:
    rt = read_src("workspace/runtime.ts")
    code = strip_comments(rt)

    has_ns = bool(re.search(r"^\s*snapshot:\s*\{", code, flags=re.M))
    has_methods = all(m in code for m in ("capture:", "restore:", "validate:", "status:"))
    check("T3a workspaceRuntime 暴露 snapshot 门面（capture / restore / validate / status）",
          has_ns and has_methods,
          json.dumps({"命名空间": has_ns, "四方法": has_methods}, ensure_ascii=False))

    three_views = all(k in rt for k in ("workspaceId", "entryCount", "persistedValid", "runIdMatch"))
    check("T3b 只读三视图齐备（当前工作空间状态 / 最近布局状态 / 恢复可用性）", three_views,
          "workspaceId + entryCount + persistedValid + runIdMatch")

    # 禁止项：门面里不得出现任何"执行"入口
    exec_idents = ["killsProcesses: true", "launchesApps: true", "writesDatabase: true",
                   "touchesUnmanagedWindows: true", "executable: true",
                   "killProcess", "terminateProcess", "moveWindow", "setWindowPos",
                   "launchApp", "startApp", "ShellExecute"]
    hits = [i for i in exec_idents if i in rt]
    check("T3c 门面**零执行入口**（无杀进程 / 无移动窗口 / 无启动软件 / 无写库）",
          not hits, "只读 + 只算计划" if not hits else "; ".join(hits))

    guards_false = all(f"{k}: false" in rt for k in (
        "killsProcesses", "launchesApps", "writesDatabase", "touchesUnmanagedWindows"))
    exec_false = "executable: false" in rt
    check("T3d 四条红线与 executable 在门面视图里写死为 false（可断言）",
          guards_false and exec_false, "guardrails 四项 + executable 均为 false")

    snap = read_src("workspace/snapshot.ts")
    no_imports = not re.findall(r"^\s*import\s", snap, flags=re.M)
    check("T3e snapshot.ts 接入门面后仍**零 import**（纯模块没被污染）", no_imports, "0 import")

    injects = all(k in rt for k in ("setProbe", "setPersistedReader", "setCurrentRunId", "isProbeWired"))
    check("T3f 注入点齐备（真实采集接入时无需改门面形状）", injects,
          "setProbe / setPersistedReader / setCurrentRunId / isProbeWired")

    # T1c 白名单未被破坏：不得有新文件 import workspace/runtime
    # （TECH-05-C §P0-3 登记了产品内的工作空间状态组件为第二处消费者）
    # （UI-FUSION-FULL 登记第三处：首页 Hero 读取工作空间运行时作**只读**投影，
    #   与 WorkspaceStatus.vue 同一类消费者 —— 只读 `workspaceRuntime` 门面，
    #   不新增写路径、不碰 frozen 命令面）
    allowed = {
        str(SRC / "workspace" / "runtime.ts"),
        str(SRC / "views" / "DevWorkspaceHarness.vue"),
        str(SRC / "components" / "WorkspaceStatus.vue"),
        str(SRC / "components" / "HomeHero.vue"),
    }
    importers: list[str] = []
    for path in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"""from\s+['"][^'"]*workspace/runtime['"]""", text) and str(path) not in allowed:
            importers.append(str(path.relative_to(SRC)))
    check("T3g runtime 消费者白名单未被破坏（固件页 + 已登记的状态组件）", not importers,
          "无额外消费者" if not importers else "; ".join(importers))


def t4_forbidden() -> None:
    router = read_src("router/index.ts")
    routes = re.findall(r"path:\s*'([^']*)'", router)
    # TECH-05-C §P0-1 有意新增一条：`/models`（模型管理中心，不进主导航）。
    # TECH-07 §P0-4 有意新增一条：`/run`（运行页 · 影院版，不进主导航）。
    # 2026-09-18 动效对接批次有意新增一条：`/motion`（动效规范页 · 不进主导航）。
    #   依据 = 设计稿 `ROUTES.showcase` 页头原文「只做展示与切换，不进主导航 ——
    #   主 IA 不动，入口放在设置 · 外观」；同批把设计稿的 `ROUTES.guard`
    #   （三档降级对比）并入同一页，故只新增**一条**路由而不是两条。
    #   与既有的 `/dev/motion`（DevMotionHarness.vue）**不是同一件东西**：
    #   前者是产品页（设计稿的动效规范台），后者是 TECH-01 的 dev-only 固件。
    # 基线因此演进 —— 但"演进了哪一条"必须逐项可核对（差异会打进 detail）。
    baseline = ['/', '/dashboard', '/software', '/ai', '/learning', '/project', '/mode', '/layout',
                '/profile', '/life', '/device', '/plugins', '/settings', '/models', '/run',
                '/motion', '/dev/motion', '/dev/workspace']
    same = routes == baseline
    check("T4a UI 页面清单与基线逐项一致（TECH-05-C 后基线含 /models，TECH-07 后含 /run，本批含 /motion）",
          same,
          json.dumps({"count": len(routes), "一致": same, "差异": sorted(set(routes) ^ set(baseline))},
                     ensure_ascii=False))

    # 基线：TECH-05-C 后的正式视图清单（逐一钉住，防止"顺手删/搬"变成静默通过）
    views_baseline = [
        "AiView.vue", "DashboardView.vue", "DesktopWidgetView.vue", "DevMotionHarness.vue",
        "DevWorkspaceHarness.vue", "DeviceView.vue", "LayoutView.vue", "LearningView.vue",
        "LifeView.vue", "ModeView.vue", "ModelsView.vue", "MotionSpecView.vue", "PluginsView.vue",
        "ProfileView.vue", "ProjectView.vue", "RunView.vue", "SettingsView.vue", "SoftwareView.vue",
    ]
    views = sorted(p.name for p in (SRC / "views").glob("*.vue"))
    check("T4b 视图文件与基线逐项一致（无删除 / 无搬家；TECH-05-C 后含 ModelsView.vue，本批含 MotionSpecView.vue）",
          views == sorted(views_baseline),
          json.dumps({"count": len(views), "差异": sorted(set(views) ^ set(views_baseline))},
                     ensure_ascii=False))

    # 只匹配**真实的 at-rule 声明** `@keyframes <name>`（不是注释里提到这个词）。
    # TECH-05-C 期间新增的原语层在注释里写明了"本文件零 @keyframes"，
    # 裸文本扫描会把这句自述当成违规 —— 判据改为正则匹配声明本身，
    # 精度提高（仍能抓到任何真实新增的关键帧），不放松。
    kf_re = re.compile(r"@keyframes\s+[A-Za-z_-]")
    kf = []
    for p in SRC.rglob("*"):
        if p.suffix in (".css", ".vue") and p.is_file():
            if kf_re.search(p.read_text(encoding="utf-8")):
                kf.append(str(p.relative_to(SRC)).replace("\\", "/"))
    check("T4c 未新增动画体系（@keyframes 声明全局仅既有 1 处：base.css 的 ai-blink）",
          sorted(kf) == ["styles/base.css"], json.dumps(sorted(kf), ensure_ascii=False))

    # 无大规模重构：既有 AI 链路的调用形状保留（TECH-03 的 T6c 同款锚点）
    #
    # TECH-05-D §P1-A：请求链路**有意**收敛到应用层唯一入口
    # （`ai/assistant/transport.ts`）。于是本条的锚点**随重构迁移**，不是被删掉：
    #   · `'ai_chat'` 必须出现在唯一入口里（命令名一项不少）；
    #   · 并且**不得**再出现在 store 或任何 Vue 页面里 —— 这是新增的**反向断言**，
    #     比原来的正向断言更强（原来只要求"出现在 store"，现在禁止它出现在 store）。
    # 判据一律跑在**去注释后的代码**上：注释里提一句 `ai_chat` 不算数
    # （否则迁移会变成"往注释里搬一行"就通过，那就成了假绿）。
    #
    # "页面零 transport" 的口径**只圈 AI 请求链路**（`ai_chat` / `ai_cancel` /
    # `ai_preview_context`）—— SettingsView 的凭据读写是另一条链路（且早于本轮存在），
    # 不在本条范围内，不能顺手算成违规。AI 助手页（AiView.vue）另有一条更严的断言：
    # **它连 `invokeCore` 都不许出现**（页面不得承担任何 Provider/API 传输逻辑）。
    store = strip_comments(read_src("stores/ai.ts"))
    transport = strip_comments(read_src("ai/assistant/transport.ts"))
    request_code = strip_comments(read_src("ai/assistant/request.ts"))
    ai_view_code = strip_comments(read_src("views/AiView.vue"))
    REQUEST_CMDS = ("'ai_chat'", "'ai_cancel'", "'ai_preview_context'")
    page_hits = sorted(
        str(p.relative_to(SRC)).replace("\\", "/")
        for p in SRC.rglob("*.vue")
        if any(c in strip_comments(p.read_text(encoding="utf-8")) for c in REQUEST_CMDS)
    )
    anchors = {
        "ai_chat 迁移到唯一入口（ai/assistant/transport.ts）": "'ai_chat'" in transport,
        "store 内不再直接调请求 transport": "'ai_chat'" not in store,
        "Vue 页面零 AI 请求链路（无 ai_chat/ai_cancel/ai_preview_context）": not page_hits,
        "AI 助手页零 invokeCore（页面不承担任何传输逻辑）": "invokeCore" not in ai_view_code,
        "参数键在应用层装配（buildChatArgs）": all(
            k in request_code for k in ("provider:", "model:", "apiBase:", "mode:", "enabledScopes:")),
        "镜像键仍写": "'ui.ai.provider'" in store and "'ui.ai.model'" in store,
        "对外面 12 项仍在": all(s in store for s in (
            "providerId", "model", "mode", "messages", "currentProvider", "permissionText",
            "enabledScopes", "setProvider", "setModel", "setMode", "init", "send")),
        "选择面仍写 canonical（provider/model 参数键保留）": "provider: this.providerId" in store
            and "model: this.model" in store and "mode: this.mode" in store,
    }
    check("T4d 既有 AI 链路锚点齐全（ai_chat→应用层唯一入口 / 参数键 / 镜像键 / 对外面 12 项）",
          all(anchors.values()),
          json.dumps({**anchors, "页面 transport 命中": page_hits}, ensure_ascii=False))

    # 新增代码集中在 model 层与 workspace 门面，未散落到各视图
    new_or_changed = ["ai/model/selection.ts", "ai/model/session.ts", "ai/model/bridge.ts"]
    absent = [f for f in new_or_changed if not (SRC / f).exists()]
    check("T4e 新增面收敛在 ai/model（决策/会话/桥三层）+ workspace 门面",
          not absent, f"{len(new_or_changed)} 个新文件均存在" if not absent else "缺失：" + ", ".join(absent))


# ---------------------------------------------------------------- 主流程


def main() -> int:
    print("=== TECH-04 验收 · 核心能力接入第一阶段 ===")
    tmp = Path(tempfile.mkdtemp(prefix="pw-tech04-"))
    try:
        try:
            compile_entries(tmp)
            sizes = ", ".join(
                f"{f.split('/')[-1]}→{(tmp / f.replace('.ts', '.js')).stat().st_size}B"
                for f in ENTRY_FILES)
            check("T0 被测模块编译（tsc → CommonJS）", True, sizes)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check("T0 被测模块编译（tsc → CommonJS）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
            raise SystemExit(1)

        (tmp / "fixture.js").write_text(FAKE_PORTS_JS, encoding="utf-8")
        (tmp / "chain.js").write_text(CHAIN_JS, encoding="utf-8")

        for fn in (t2_static, t3_snapshot_facade, t4_forbidden):
            try:
                fn()
            except Exception:
                tb = traceback.format_exc().strip().splitlines()
                check(getattr(fn, "__name__", "static"), False, "EXCEPTION: " + " | ".join(tb[-3:]))

        try:
            for cname, passed, detail in run_js(tmp, "chain.js"):
                check(cname, passed, detail)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check("T1/T2（Node 驱动 selection + session）", False,
                  "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== 汇总 {passed}/{total} ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
