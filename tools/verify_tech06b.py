#!/usr/bin/env python3
"""TECH-06-B 验收 · Part 1 模型清单持久化（`ai.models.registry` 唯一来源）。

## 被测物

- `ui/src/ai/model/archive.ts` —— 归档形态的**唯一定义**（serialize / parse / materialize）。
- `ui/src/ai/model/registry.ts` —— 唯一读写口：`hydrate()` 恢复、`add/update/remove/clear` 落盘。
- `ui/src/model/ports.ts`（coreArchivePort）—— 复用既有 `get_config` / `put_config`。
- `core/src/db/config.rs` —— 键登记（KEYS / expected_type / default_for 三处）+ 契约 v13。

## 证据分四层（各有各的治法）

| 层 | 治什么 |
|----|--------|
| ① Node 直驱 | **真编译**后的 `ModelRegistry` 在两个实例之间传同一份归档 = "重启"的领域级证明：恢复后模型还在、canonical 还在、探测状态**不**跟随（反假绿）、删除无残留、读不到就拒绝写（fail-closed） |
| ② 静态 T1~T5 | 抓"第二事实源 / 页面自己存 / localStorage 存 / 漏接线 / 破 UI 冻结 / 加后端命令" |
| ③ 动态（dist） | 跑**最终产物**：反 localStorage（加模型前后键集合不变）+ 无 core 时归档如实报 unreadable |
| ④ 真 core 双启动 | `PW_DATA_DIR` 隔离库 → PUT/GET/SQLite → **杀进程再启动** → 值仍在（存储层的真重启证明） |

## 反"假通过"

- ④ 是**真重启**：`stop_app()`（terminate+wait）之后重新 `start_app()`，不是"再读一次"。
- ③ 在浏览器里没有 core ⇒ 归档必然不可用 ⇒ 断言的是"**如实报 unreadable 且不写 localStorage**"，
  而不是"持久化成功"（后者在本环境不可证，不冒充）。
- ① 的对照组：写路径被断言两次（可读时真的写了 / 不可读时真的没写），避免"反正都成功"。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
UI = ROOT / "ui"
SRC = UI / "src"
DIST = UI / "dist"
TSC = UI / "node_modules" / "typescript" / "lib" / "tsc.js"

# ---- 复用 TECH-02 基建（CDP / Edge / 静态服务）----
_spec = importlib.util.spec_from_file_location("pw_tech02_infra", TOOLS / "verify_tech02_workspace.py")
assert _spec and _spec.loader
_t02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_t02)
CDPWebSocket = _t02.CDPWebSocket
find_edge = _t02.find_edge
free_port = _t02.free_port
start_server = _t02.start_server
ev = _t02.ev
wait_for = _t02.wait_for

# ---- 复用 stage9 的 core 启动/停止/HTTP/SQLite 设施（真重启证明）----
_spec9 = importlib.util.spec_from_file_location("pw_stage9_infra", TOOLS / "verify_stage9.py")
assert _spec9 and _spec9.loader
_s9 = importlib.util.module_from_spec(_spec9)
_spec9.loader.exec_module(_s9)
start_app = _s9.start_app
stop_app = _s9.stop_app
wait_port = _s9.wait_port
http_json = _s9.http_json
read_config_map = _s9.read_config_map

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def read_src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\{\s*/\*.*?\*/\s*\}", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//[^\n]*", "", text)
    text = re.sub(r"(?m)//[^\n]*", "", text)
    text = re.sub(r"(?m)^\s*\*[^\n]*", "", text)
    return text


def node() -> str:
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


# ---------------------------------------------------------------- 路径常量

ARCHIVE = "ai/model/archive.ts"
REGISTRY = "ai/model/registry.ts"
PORTS = "ai/model/ports.ts"
STATUS = "ai/model/status.ts"
PAGE = "views/ModelsView.vue"
CONFIG_RS = "core/src/db/config.rs"
MIGRATIONS_RS = "core/src/db/migrations.rs"
COMMANDS_RS = "core/src/api/commands.rs"
CONTRACT_MD = "docs/agent-dev/03-数据契约与接口规范.md"
KEY = "ai.models.registry"


# ================================================================ ① Node 直驱

NODE_JS = r"""
const assert = (c, m) => { if (!c) throw new Error('内部断言失败：' + m); };

const { ModelRegistry, entryStatusOf } = require('./ai/model/registry.js');
const A = require('./ai/model/archive.js');
const { displayStatusOf } = require('./ai/model/status.js');

const checks = [];
const rec = (name, ok, detail) => checks.push([name, !!ok, detail]);

// ---- 测试端口束（真实 Registry + 测试自持的存储） ----
function makeBundle(opts = {}) {
  const kv = opts.kv || new Map();            // canonical（模拟 core config 的 L1 键；重启的实例必须共享同一存储）
  const creds = new Set(opts.creds ?? []);
  const box = opts.archiveBox || { raw: '' };  // 归档（模拟 config 表的那一格）
  const providers = [
    { id: 'comp', label: '兼容网关', connectionType: 'api', defaultEndpoint: 'https://gw.example/v1',
      defaultModel: 'm-large', needsKey: true, enabled: true, note: '', capabilities: ['chat', 'stream'] },
    { id: 'ollama', label: '本地推理', connectionType: 'local', defaultEndpoint: 'http://127.0.0.1:11434',
      defaultModel: 'q2.5:7b', needsKey: false, enabled: true, note: '', capabilities: ['chat'] },
  ];
  const ports = {
    io: { listRemoteModels: async () => opts.remote ?? [] },
    capability: { loadProviders: async () => providers, loadSecretPresence: async () => [...creds] },
    canonical: {
      keys: { provider: 'ai.provider.current', model: 'ai.model.current' },
      mirrorKeys: { provider: 'ui.ai.provider', model: 'ui.ai.model' },
      read: async () => {
        const p = kv.get('ai.provider.current') || '';
        const m = kv.get('ai.model.current') || '';
        if (!p && !m) return null;
        return { values: { provider: p, model: m, apiBase: '' }, from: 'core' };
      },
      write: async (patch) => {
        if (patch.provider !== undefined) kv.set('ai.provider.current', patch.provider);
        if (patch.model !== undefined) kv.set('ai.model.current', patch.model);
        return { landedOn: 'core' };
      },
    },
    cache: { read: () => null, write: () => undefined, clear: () => undefined },
    secret: {
      has: async (id) => creds.has(id),
      set: async (id, s) => { creds.add(id); return { provider: id, ref: 'pw/' + id + '/default', mask: '****', backend: 'memory' }; },
      remove: async (id) => creds.delete(id),
      refFor: (id) => 'pw/' + id + '/default',
    },
  };
  // 归档端口：默认绑定 box；archiveThrows=true 时 read 抛错（模拟 core 不可达）
  if (opts.archiveThrows) {
    ports.archive = { key: A.ARCHIVE_KEY,
      read: async () => { throw new Error('unreachable：核心服务未连接'); },
      write: async () => { throw new Error('禁止写入（fail-closed 应当根本不调用本方法）'); } };
  } else {
    ports.archive = { key: A.ARCHIVE_KEY, read: async () => box.raw, write: async (raw) => { box.raw = raw; } };
  }
  const reg = new ModelRegistry(ports);
  return { reg, kv, creds, box, providers, ports };
}

const factsOf = (reg, id) => {
  const e = reg.list().find((x) => x.id === id);
  if (!e) return null;
  return {
    enabled: e.enabled, entryStatus: e.status,
    needsSecret: e.needsSecret, hasSecret: e.hasSecret, lastError: e.lastError,
  };
};

(async () => {
  // ---------- ① 落盘：add 三个模型（api / local / agent） ----------
  const b1 = makeBundle({ archiveBox: { raw: '' }, creds: ['comp'] });
  const r1 = b1.reg;
  await r1.hydrate();
  const apiId = r1.add({ provider: 'comp', model: 'm-large' }).id;
  const localId = r1.add({ provider: 'ollama', model: 'q2.5:7b' }).id;
  r1.providers.registerProvider({ id: 'ag1', label: '个人Agent', connectionType: 'agent',
    defaultEndpoint: 'http://127.0.0.1:8787', defaultModel: 'ag', needsKey: false,
    enabled: true, note: '', capabilities: ['chat'] });
  const agentId = r1.add({ provider: 'ag1', model: 'ag' }).id;
  r1.update(localId, { status: { enabled: false } });
  await r1.archiveFlushed();

  const written = b1.box.raw;
  let parsed = A.parseArchive(written);
  rec('① 归档串可解析且包含全部 3 条（写入真的发生了）',
      parsed.models.length === 3 && !parsed.issues.length,
      JSON.stringify({ 条数: parsed.models.length, issue: parsed.issues }));

  // ①b 确定性 + 往返：归档 → 解析 → 物化 → 再序列化 必须字节级还原同一串
  // （list() 返回的是 ModelListEntry 展平视图、没有 metadata，不能直接喂 serializeArchive）
  const roundTrip = A.serializeArchive(
      A.parseArchive(written).models
        .map((m) => A.materializeArchiveRecord(m, Date.now()).profile)
        .filter(Boolean));
  rec('①b 序列化确定性（归档 → 物化 → 再序列化 字节级还原：同状态永远得到同串）',
      roundTrip === written,
      roundTrip === written ? '往返字节一致' : '往返发生漂移：' + roundTrip.slice(0, 120));

  // ---------- ② 重启：新 Registry 实例读同一份归档 ----------
  const b2 = makeBundle({ archiveBox: b1.box, creds: ['comp'], kv: b1.kv });
  const r2 = b2.reg;
  const report = await r2.hydrate();
  const ids2 = r2.list().map((e) => e.id).sort();
  rec('② 重启后模型全部恢复（3/3，id 一致）',
      report.archive.state === 'ok' && report.archive.restored === 3 &&
      JSON.stringify(ids2) === JSON.stringify([agentId, apiId, localId].sort()),
      JSON.stringify({ state: report.archive.state, restored: report.archive.restored, ids: ids2 }));

  const apiRec = parsed.models.find((m) => m.id === apiId);
  const localRec = parsed.models.find((m) => m.id === localId);
  rec('②b 身份配置逐字段保真（provider/model/connection.type/endpoint）',
      apiRec.provider === 'comp' && apiRec.model === 'm-large' &&
      localRec.connection.type === 'local' && !!localRec.connection.endpoint,
      JSON.stringify({ api: apiRec.connection, local: localRec.connection }));

  // ---------- ③ 反假绿：探测状态不跟随重启 ----------
  // 重启前：真探测（本地桩 io 返回 ok）→ connected
  const before = await r1.check(apiId);
  const beforeFacts = factsOf(r1, apiId);
  // 重启后：同一模型必须回到「未测试」
  const afterFacts = factsOf(r2, apiId);
  const afterEnv = r2.list().find((e) => e.id === apiId);
  const raw2 = A.parseArchive(b2.box.raw).models.find((m) => m.id === apiId);
  rec('③ 重启前探测通过 → connected（对照组，证明这条链路真的会变绿）',
      before.ok === true && beforeFacts.entryStatus === 'ready' &&
      displayStatusOf(beforeFacts) === 'connected',
      JSON.stringify({ code: before.code, entry: beforeFacts.entryStatus, display: displayStatusOf(beforeFacts) }));
  rec('③b 重启后**不含**探测状态：available=false / 无 lastError / 显示「未测试」（不得假绿）',
      afterFacts.entryStatus === 'unchecked' && displayStatusOf(afterFacts) === 'unchecked' &&
      !('available' in raw2) && !('lastError' in raw2) && !('lastCheck' in raw2),
      JSON.stringify({ entry: afterFacts.entryStatus, display: displayStatusOf(afterFacts), 归档键: Object.keys(raw2) }));

  // ③c enabled（用户意图）跟随重启：local 被停用 → 恢复后仍 disabled → 显示「离线」
  const lf = factsOf(r2, localId);
  rec('③c enabled 持久化（停用的模型重启后仍停用 → 「离线」，不是「未测试」）',
      lf.enabled === false && lf.entryStatus === 'disabled' && displayStatusOf(lf) === 'offline',
      JSON.stringify({ enabled: lf.enabled, entry: lf.entryStatus, display: displayStatusOf(lf) }));

  // ---------- ④ current model 不丢（canonical + 归档 双重持久化） ----------
  await r1.setDefault(localId);
  await r1.archiveFlushed();
  const b3 = makeBundle({ archiveBox: b1.box, creds: ['comp'], kv: b1.kv });
  await b3.reg.hydrate();
  const def = b3.reg.getDefault();
  rec('④ 重启后 current model 不丢（canonical 恢复 + 指向的模型实体还在，不 dangling）',
      def.unset === false && def.dangling === false && def.profile && def.profile.id === localId,
      JSON.stringify({ unset: def.unset, dangling: def.dangling, profile: def.profile && def.profile.id,
                       canonical: def.canonical }));

  // ---------- ⑤ 删除不残留 ----------
  r2.remove(apiId);
  await r2.archiveFlushed();
  const afterRemove = A.parseArchive(b2.box.raw).models.map((m) => m.id);
  const b4 = makeBundle({ archiveBox: b2.box, creds: ['comp'], kv: b1.kv });
  await b4.reg.hydrate();
  rec('⑤ 删除后归档不含该 id，重启也不再出现（无残留）',
      !afterRemove.includes(apiId) &&
      !b4.reg.list().some((e) => e.id === apiId) &&
      b4.reg.list().length === 2,
      JSON.stringify({ 归档: afterRemove, 重启后: b4.reg.list().map((e) => e.id) }));

  // ---------- ⑥ fail-closed：读不到就拒绝写 ----------
  const b5 = makeBundle({ archiveThrows: true });
  const r5 = b5.reg;
  await r5.hydrate();
  r5.providers.registerProvider({ id: 'comp', label: '兼容网关', connectionType: 'api',
    defaultEndpoint: 'https://gw.example/v1', defaultModel: 'm-large', needsKey: true,
    enabled: true, note: '', capabilities: ['chat'] });
  r5.add({ provider: 'comp', model: 'm-large' });
  await r5.archiveFlushed();
  const st5 = r5.getArchiveState();
  rec('⑥ core 不可达 → 归档如实报 unreadable 且**拒绝覆盖写**（不会把空清单写回去清库）',
      st5.state === 'unreadable' && st5.issues.length > 0,
      JSON.stringify({ state: st5.state, issue: st5.issues[0] && st5.issues[0].message }));

  // ---------- ⑦ 容错：坏归档不崩、好记录不丢 ----------
  const env = JSON.parse(written);
  const cases = {
    坏JSON: '{not-json',
    顶层非对象: '[1,2,3]',
    版本不识别: JSON.stringify({ v: 99, models: env.models }),
    缺models: JSON.stringify({ v: 1 }),
    记录缺id: JSON.stringify({ v: 1, models: [{ provider: 'comp', model: 'x' }, env.models[0]] }),
    重复id: JSON.stringify({ v: 1, models: [env.models[0], env.models[0]] }),
  };
  const tol = {};
  for (const [name, raw] of Object.entries(cases)) {
    let out = null, threw = false;
    try { out = A.parseArchive(raw); } catch (e) { threw = true; }
    tol[name] = threw ? 'THREW' : { 条数: out.models.length, issue: out.issues.length };
  }
  rec('⑦ 坏归档逐类容错（不抛错、好记录保留、问题逐条上报）',
      tol['坏JSON']['条数'] === 0 && tol['顶层非对象']['条数'] === 0 &&
      tol['版本不识别']['条数'] === 0 && tol['缺models']['条数'] === 0 &&
      tol['记录缺id']['条数'] === 1 && tol['重复id']['条数'] === 1 &&
      Object.values(tol).every((v) => v !== 'THREW'),
      JSON.stringify(tol));

  // ⑦b 对照：好归档解析零 issue（证明上面的 issue 是"真抓到问题"，不是恒非空）
  rec('⑦b 对照组：合法归档解析零 issue',
      A.parseArchive(written).issues.length === 0, '合法输入零告警');

  // ---------- ⑧ 归档记录形态：只有身份与意图，没有探测状态 ----------
  const keysOfRecord = Object.keys(A.parseArchive(written).models[0]);
  rec('⑧ 归档记录键集合 = 身份+配置+enabled（结构上不含 available/lastCheck/lastError）',
      ['id', 'provider', 'name', 'model', 'connection', 'capabilities', 'enabled',
       'createdAt', 'updatedAt'].every((k) => keysOfRecord.includes(k)) &&
      !['available', 'lastCheck', 'lastError', 'status'].some((k) => keysOfRecord.includes(k)),
      JSON.stringify(keysOfRecord));

  // ---------- ⑨ materialize 的"恢复"语义：不要求 Provider 在册 ----------
  const solo = A.parseArchive(written).models.find((m) => m.id === localId);
  const mat = A.materializeArchiveRecord(solo, Date.now());
  rec('⑨ 恢复不依赖 Provider 在册（core 掉线也能恢复，不会因此丢数据）',
      !!mat.profile && mat.profile.provider === 'ollama' && mat.profile.status.enabled === false,
      JSON.stringify({ ok: !!mat.profile, provider: mat.profile && mat.profile.provider }));
  const badMat = A.materializeArchiveRecord({ ...solo, id: 'x y!', connection: { type: 'api' } }, Date.now());
  rec('⑨b 非法记录被拒绝且给出原因（不静默吞）',
      !!badMat.error && !badMat.profile,
      JSON.stringify(badMat.error || ''));

  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
})().catch((e) => {
  console.log('__PW_RESULT__' + JSON.stringify({ checks, fatal: String(e && e.message || e) }));
});
"""


def compile_entries(tmp: Path) -> None:
    if not TSC.exists():
        raise RuntimeError(f"缺少 typescript 编译器：{TSC}")
    entries = [str(SRC / ARCHIVE), str(SRC / REGISTRY), str(SRC / STATUS)]
    args = [
        node(), str(TSC),
        "--target", "ES2022", "--module", "commonjs", "--moduleResolution", "node",
        "--strict", "--esModuleInterop", "--skipLibCheck",
        "--rootDir", str(SRC), "--outDir", str(tmp),
        *entries,
    ]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(UI), timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"tsc 编译失败（exit {proc.returncode}）:\n{proc.stdout}\n{proc.stderr}")
    for rel in (ARCHIVE, REGISTRY, STATUS):
        if not (tmp / rel.replace(".ts", ".js")).exists():
            raise RuntimeError(f"编译产物缺失：{rel}")


def run_node(tmp: Path) -> None:
    (tmp / "__probe.js").write_text(NODE_JS, encoding="utf-8")
    proc = subprocess.run([node(), str(tmp / "__probe.js")], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(tmp), timeout=300)
    out = proc.stdout or ""
    marker = [ln for ln in out.splitlines() if ln.startswith("__PW_RESULT__")]
    if not marker:
        raise RuntimeError(f"Node 探针未产出结果（exit {proc.returncode}）\n{out[-1500:]}\n{(proc.stderr or '')[-800:]}")
    payload = json.loads(marker[-1][len("__PW_RESULT__"):])
    for name, ok, detail in payload["checks"]:
        check(name, ok, detail)
    if payload.get("fatal"):
        raise RuntimeError("Node 探针致命错误：" + payload["fatal"])


def node_layer() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="pw-tech06b-node-"))
    try:
        compile_entries(tmp)
        run_node(tmp)
    except Exception:
        tb = traceback.format_exc().strip().splitlines()
        check("①~⑨ Node 直驱（真编译 Registry 的重启模拟）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ================================================================ ② 静态

def t1_single_source() -> None:
    arc = read_src(ARCHIVE)
    arc_c = strip_comments(arc)
    ports = strip_comments(read_src(PORTS))
    reg = strip_comments(read_src(REGISTRY))
    page = strip_comments(read_src(PAGE))

    # T1a 归档形态唯一定义
    definers = []
    for p in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        t = strip_comments(p.read_text(encoding="utf-8"))
        if re.search(r"(export\s+)?function\s+(serializeArchive|parseArchive|materializeArchiveRecord)\s*\(", t) or \
           re.search(r"(export\s+)?const\s+ARCHIVE_KEY\s*=", t):
            definers.append(p.relative_to(SRC).as_posix())
    check("T1a 归档键与序列化/解析**唯一定义**在 ai/model/archive.ts（不出现第二套）",
          sorted(set(definers)) == [ARCHIVE] and 'ARCHIVE_KEY = "ai.models.registry"' in arc_c.replace("'", '"'),
          json.dumps(sorted(set(definers)), ensure_ascii=False))

    # T1b 键值即契约键
    check("T1b 归档键 = ai.models.registry（与 core/契约文档一字不差）",
          f'export const ARCHIVE_KEY = "{KEY}"' in arc.replace("'", '"').replace('export const ARCHIVE_KEY = "ai.models.registry"', 'export const ARCHIVE_KEY = "' + KEY + '"')
          or f"ARCHIVE_KEY = '{KEY}'" in arc or f'ARCHIVE_KEY = "{KEY}"' in arc,
          f"ARCHIVE_KEY = {KEY}")

    # T1c 接线检索：生产组合根必须注入 archive（漏了 = 静默退化为内存态）
    m = re.search(r"export function createCoreModelRegistry\([^)]*\)[\s\S]*?\n\}", ports)
    body = m.group(0) if m else ""
    check("T1c 生产组合根已注入 archive 端口（`archive: coreArchivePort()`）—— 防「文件在、没接线」",
          "archive: coreArchivePort()" in body,
          "createCoreModelRegistry 含 archive" if "archive: coreArchivePort()" in body else "组合根缺 archive 注入")

    # T1d 归档端口复用既有命令 + 无 localStorage
    m2 = re.search(r"export function coreArchivePort\(\)[\s\S]*?\n\}", ports)
    abody = m2.group(0) if m2 else ""
    cmds = set(re.findall(r"invokeCore(?:<[^>]*>)?\('([a-z_]+)'", abody))
    check("T1d 归档端口只走既有 get_config/put_config（零新增命令）且带 inTauri 守卫、零 localStorage",
          cmds == {"get_config", "put_config"} and "inTauri()" in abody and "localStorage" not in abody,
          json.dumps({"命令": sorted(cmds), "inTauri守卫": "inTauri()" in abody,
                      "localStorage": "localStorage" in abody}, ensure_ascii=False))

    # T1e 页面不碰归档（禁止"页面自己存模型"）
    page_touch = ("ARCHIVE_KEY" in page or "archive" in page.lower() and "get_config" in page)
    check("T1e 模型页零归档访问（不自己存模型，一切经 Registry）",
          "ARCHIVE_KEY" not in page and "get_config" not in page,
          "页面零持久化直连" if not page_touch else "页面出现归档/配置直连")


def t2_no_localstorage_and_core_side() -> None:
    # T2a 全 ui/src 无任何 localStorage 写模型键（含 stores/ai.ts 键基线不变）
    bad: list[str] = []
    for p in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        t = strip_comments(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"setItem\(\s*'([^']+)'", t):
            k = m.group(1)
            if "model" in k.lower() or k.startswith("ai.") or k == KEY:
                bad.append(f"{p.relative_to(SRC).as_posix()}:{k}")
    check("T2a 零 localStorage 写模型（键含 model/ai.* 一律不允许 —— 指令红线）",
          not bad, json.dumps(sorted(set(bad)), ensure_ascii=False) if bad else "全仓 0 处")

    store = read_src("stores/ai.ts")
    found = set(re.findall(r"'(ui\.ai\.[A-Za-z]+)'", store))
    check("T2a-b AI store 的 localStorage 键基线不增不减（持久化没有偷偷借道 store）",
          found == {"ui.ai.width", "ui.ai.collapsed", "ui.ai.provider", "ui.ai.model", "ui.ai.mode"},
          json.dumps(sorted(found), ensure_ascii=False))

    cfg = read(CONFIG_RS)
    in_keys = f'"{KEY}"' in cfg
    has_type = re.search(rf'"{KEY}"\s*=>\s*"string"', cfg) is not None
    has_default = re.search(rf'"{KEY}"\s*=>\s*serde_json::json!\(""\)', cfg) is not None
    check("T2b core 三处齐登记（KEYS / expected_type=string / default_for=\"\"）",
          in_keys and has_type and has_default,
          json.dumps({"KEYS": in_keys, "expected_type": has_type, "default_for": has_default}, ensure_ascii=False))

    # T2b-b core 单测锁死"显式类型 + 显式默认"两条契约约束仍然成立（防漏登静默落到 any/null）
    check("T2b-b core 侧契约自检测试在位（explicit type / explicit default 两条）",
          "fn every_registered_key_has_an_explicit_type" in cfg and
          "fn every_registered_key_has_an_explicit_default" in cfg,
          "两条契约自检测试在位")

    mig = read(MIGRATIONS_RS)
    m = re.search(r"CONTRACT_SCHEMA_VERSION:\s*i64\s*=\s*(\d+)", mig)
    ver = int(m.group(1)) if m else -1
    check("T2c 契约版本升到 13（模型清单键入契约；无表结构变更 ⇒ 不写 migration）",
          ver == 13, f"CONTRACT_SCHEMA_VERSION = {ver}")

    doc = read(CONTRACT_MD)
    key_row = f"`{KEY}`" in doc
    v13_row = "| 2026-09-16 | **v13**" in doc
    v13_mentions = "ai.models.registry" in doc
    check("T2d 契约文档同步（键行 + v13 变更记录）",
          key_row and v13_row and v13_mentions,
          json.dumps({"键行": key_row, "v13行": v13_row}, ensure_ascii=False))


def t3_registry_wiring() -> None:
    reg = strip_comments(read_src(REGISTRY))
    others: list[str] = []
    for p in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith("ai/model/"):
            continue
        t = strip_comments(p.read_text(encoding="utf-8"))
        if re.search(r"from ['\"][^'\"]*ai/model/archive['\"]|from ['\"]\./archive['\"]", t) or "serializeArchive" in t:
            others.append(rel)
    check("T3a 归档的运行期消费方只有 ai/model/ 域内（页面/其它模块零 import —— 无第二事实源）",
          not others, json.dumps(others, ensure_ascii=False) if others else "域外零引用")

    # T3b check()（唯一发请求的方法）不得触发落盘 —— 探测状态不持久化
    m = re.search(r"async check\(id: string\): Promise<ConnectionTestResult> \{[\s\S]*?\n  \}", reg)
    body = m.group(0) if m else ""
    check("T3b 探测（check）不触发落盘（避免每次测试连接都写库，也让状态天然不持久化）",
          "scheduleArchivePersist" not in body and body != "",
          "check 内零落盘调用")

    # T3c 四个变更口都落盘；remove 仅在真删了之后
    for name, sig in (("add", r"add\(input: ModelProfileInput\): ModelProfile \{[\s\S]*?\n  \}"),
                      ("update", r"update\(id: string, patch: Partial<ModelProfileInput>\): ModelProfile \{[\s\S]*?\n  \}"),
                      ("remove", r"remove\(id: string\): boolean \{[\s\S]*?\n  \}"),
                      ("clear", r"clear\(\): void \{[\s\S]*?\n  \}")):
        mm = re.search(sig, reg)
        ok = mm is not None and ("scheduleArchivePersist()" in mm.group(0))
        check(f"T3c-{name[:3]} {name}() 落盘在位", ok,
              "scheduleArchivePersist 在位" if ok else "缺落盘调用")

    # T3d fail-closed 在代码里可见：非 ok 状态直接 return
    m = re.search(r"private scheduleArchivePersist\(\): void \{[\s\S]*?\n  \}", reg)
    body = m.group(0) if m else ""
    check("T3d 落盘前置校验（端口缺失 / 状态非 ok ⇒ 直接 return，绝不覆盖写）",
          "if (!port || this.archiveState.state !== 'ok') return" in body,
          "fail-closed 守卫在位")

    # T3e 归档形态文件不含探测状态字段（反假绿的结构性证据）
    arc = strip_comments(read_src(ARCHIVE))
    rec_iface = re.search(r"export interface ArchiveRecord \{[\s\S]*?\n\}", arc)
    iface = rec_iface.group(0) if rec_iface else ""
    check("T3e 归档记录接口零探测状态字段（available/lastCheck/lastError 结构上进不来）",
          bool(iface) and not any(k in iface for k in ("available", "lastCheck", "lastError", "status")),
          "ArchiveRecord 无探测状态字段")


def t4_no_new_backend_and_ui_frozen() -> None:
    ports = strip_comments(read_src(PORTS))
    existing = set(re.findall(r"pub (?:async )?fn (\w+)", read(COMMANDS_RS)))
    used = {a or b for a, b in re.findall(r"invokeCore<[^>]*>\('([a-z_]+)'|invokeCore\('([a-z_]+)'", ports)}
    unknown = sorted(c for c in used if c not in existing)
    check("T4a 端口层调用的 core 命令全部既有（本轮零新增命令）",
          not unknown, json.dumps({"使用": sorted(used), "不存在": unknown}, ensure_ascii=False))

    migs = sorted(p.name for p in (ROOT / "core" / "migrations").glob("*.sql"))
    check("T4b 未新增数据库迁移（仍止于 0008 —— config 键不需要 DDL）",
          bool(migs) and migs[-1] == "0008_plugin_audit.sql",
          json.dumps({"count": len(migs), "last": migs[-1] if migs else None}, ensure_ascii=False))

    page = read_src(PAGE)
    css_page = strip_comments(page)
    decl = re.findall(r"(?m)^\s*(--[A-Za-z0-9_-]+)\s*:", page)
    naked = re.findall(r"(?<![-\w])(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\))", css_page)
    check("T5a UI 冻结：模型页零自定义属性 / 零裸色值（本轮不改版）",
          not decl and not naked, json.dumps({"自定义属性": decl, "裸色值": sorted(set(naked))[:4]}, ensure_ascii=False))

    router = read_src("router/index.ts")
    routes = re.findall(r"path:\s*'([^']*)'", router)
    views = sorted(p.name for p in (SRC / "views").glob("*.vue"))
    # 基线演进（逐项可核对，判据不放松）：
    #   TECH-07 后 +1 → /run + RunView.vue；
    #   2026-09-18 动效对接批次 +1 → /motion + MotionSpecView.vue（设计稿 ROUTES.showcase，
    #   页头原文「不进主导航，入口放在设置 · 外观」）。
    check("T5b 零新增页面/路由（18 路由 / 18 视图与 TECH-06-A 基线一致；"
          "TECH-07 后含 /run + RunView.vue，动效批次后含 /motion + MotionSpecView.vue）",
          len(routes) == 18 and len(views) == 18,
          json.dumps({"路由数": len(routes), "视图数": len(views)}, ensure_ascii=False))


# ================================================================ ③ 动态（最终产物）

DYN_PROBE = r"""
(async () => {
  const M = window.__pwModels;
  if (!M) return { fatal: 'no __pwModels' };
  const r = M.registry;
  const before = {};
  for (let i = 0; i < localStorage.length; i++) before[localStorage.key(i)] = localStorage.getItem(localStorage.key(i));

  r.providers.registerProvider({ id: 't6b-local', label: 'T6B 本地桩', connectionType: 'local',
    defaultEndpoint: 'http://127.0.0.1:59998', defaultModel: 't6b-model', needsKey: false,
    enabled: true, note: '验收注入', capabilities: ['chat'] });
  let addedId = null, addErr = '';
  try { addedId = r.add({ provider: 't6b-local', model: 't6b-model' }).id; }
  catch (e) { addErr = String(e && e.message || e); }

  const st = (typeof r.getArchiveState === 'function') ? r.getArchiveState() : null;
  const akey = (typeof r.archiveKey === 'function') ? r.archiveKey() : null;

  const after = {};
  for (let i = 0; i < localStorage.length; i++) after[localStorage.key(i)] = localStorage.getItem(localStorage.key(i));
  const lsDiff = Object.keys({...before, ...after}).filter(k => before[k] !== after[k]);

  if (addedId) r.remove(addedId);
  r.providers.removeProvider('t6b-local');
  return { addedId, addErr, st, akey, lsBefore: Object.keys(before), lsDiff,
           hasFlush: typeof r.archiveFlushed === 'function' };
})()
"""


def run_dynamic() -> None:
    """跑最终 dist：证明「加模型不写 localStorage」+「无 core 时归档如实报 unreadable」。"""
    if not DIST.exists():
        check("R 动态（最终产物）", False, f"ui/dist 不存在：{DIST}")
        return
    port, srv = start_server()
    base = f"http://127.0.0.1:{port}"
    ws = None
    proc = None
    profile = None
    try:
        edge = find_edge()
        dbg_port = free_port()
        profile = tempfile.mkdtemp(prefix="pw-tech06b-")
        cmd = [
            edge, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={profile}",
            f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
            "--window-size=1600,1000", "about:blank",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as resp:
                    targets = json.loads(resp.read().decode())
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.2)
        if not ws_url:
            check("R 动态（最终产物）", False, "连不上 CDP")
            return
        ws = CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"{base}/models"}, timeout=15)
        wait_for(ws, "!!(window.__pwModels && window.__pwModels.statuses)", timeout=30)
        ev(ws, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))", timeout=10)
        res = ev(ws, DYN_PROBE, timeout=30)
        if not isinstance(res, dict) or res.get("fatal"):
            check("R 动态（最终产物）", False, json.dumps(res, ensure_ascii=False)[:300])
            return
        # R1 反 localStorage：加模型前后键集合不变
        check("R1 动态：添加模型**零** localStorage 写入（键集合逐项比对不变）",
              res["addedId"] and not res["lsDiff"],
              json.dumps({"added": bool(res["addedId"]), "ls差异": res["lsDiff"],
                          "ls键数": len(res["lsBefore"])}, ensure_ascii=False))
        # R2 无 core ⇒ 归档如实报 unreadable（不谎报已持久化）
        st = res.get("st") or {}
        check("R2 动态：无 core 时归档如实报 unreadable（fail-closed，不假装已保存）",
              bool(res["addedId"]) and st.get("state") == "unreadable" and bool(st.get("issues")),
              json.dumps({"state": st.get("state"), "issue": (st.get("issues") or [{}])[0].get("message", "")},
                         ensure_ascii=False))
        # R3 产品内接线真值
        check("R3 动态：Registry 归档键 = ai.models.registry（产品内真值，非脚本推断）",
              res.get("akey") == KEY and res.get("hasFlush") is True,
              json.dumps({"key": res.get("akey"), "archiveFlushed": res.get("hasFlush")}, ensure_ascii=False))
    except Exception:
        tb = traceback.format_exc().strip().splitlines()
        check("R 动态（最终产物）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            srv.shutdown()
        except Exception:
            pass
        if profile:
            shutil.rmtree(profile, ignore_errors=True)


# ================================================================ ④ 真 core 双启动

ENVELOPE = {
    "v": 1,
    "models": [
        {"id": "deepseek:deepseek-chat", "provider": "deepseek", "name": "deepseek-chat",
         "model": "deepseek-chat", "connection": {"type": "api", "endpoint": "https://api.example.com/v1"},
         "capabilities": {"chat": True, "vision": False, "coding": False, "agent": False},
         "enabled": True, "createdAt": 1726400000000, "updatedAt": 1726400000000},
        {"id": "ollama:q2.5:7b", "provider": "ollama", "name": "q2.5:7b",
         "model": "q2.5:7b", "connection": {"type": "local", "endpoint": "http://127.0.0.1:11434"},
         "capabilities": {"chat": True, "vision": False, "coding": False, "agent": False},
         "enabled": False, "createdAt": 1726400000000, "updatedAt": 1726400000000},
    ],
}
RAW = json.dumps(ENVELOPE, ensure_ascii=False, separators=(",", ":"))


def core_layer() -> None:
    """真 core 双启动：隔离数据目录 → 写键 → 杀进程 → 再启动 → 值仍在。"""
    exe = ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    if not exe.exists():
        check("④ 真 core 双启动（存储层真重启）", False, f"release 可执行文件不存在：{exe}（先 cargo build --release）")
        return

    data_dir = Path(tempfile.mkdtemp(prefix="pw-tech06b-core-"))
    db_path = data_dir / "workspace.db"
    proc = None
    try:
        def boot() -> str:
            nonlocal proc
            proc = start_app(exe, data_dir)
            # ★ 不能只等 config 表里的 runtime.http_port「非空」：重启场景下那是
            # **上一实例的残留值**，秒返回、GET 打在还没监听的端口上 —— C6/C7 假阴的根因。
            # 必须「读到端口 + HTTP 真探活 200」双条件（verify_stage3 的 wait_for_new_port 同坑）。
            deadline = time.time() + 60
            last_err = ""
            while time.time() < deadline:
                try:
                    port = str(read_config_map(db_path).get("runtime.http_port", "") or "")
                except Exception as exc:  # db 可能尚未建表/被锁
                    port, last_err = "", str(exc)
                if port:
                    try:
                        st_probe, _b = http_json(
                            f"http://127.0.0.1:{port}/api/v1/config/schema_version", method="GET"
                        )
                        if st_probe == 200:
                            return port
                        last_err = f"http {st_probe}"
                    except Exception as exc:  # noqa: BLE001
                        last_err = str(exc)
                time.sleep(0.3)
            raise RuntimeError(f"core 未在 60s 内 HTTP 探活成功（{last_err or '超时'}）")

        base = f"http://127.0.0.1:{boot()}"

        # C1 默认值 = 空串（"从未写过"语义）
        st, body = http_json(f"{base}/api/v1/config/{KEY}", method="GET")
        val0 = (body or {}).get("data")
        check("C1 默认值 = 空串（空串 = 从未写过，不是假的空清单）",
              st == 200 and val0 == "", json.dumps({"status": st, "data": val0}, ensure_ascii=False))

        # C2 写入 + 读回
        st, body = http_json(f"{base}/api/v1/config/{KEY}", body=RAW, method="PUT",
                             headers={"Content-Type": "application/json"})
        ok_put = bool(body) and body.get("ok") is True
        st2, body2 = http_json(f"{base}/api/v1/config/{KEY}", method="GET")
        val1 = (body2 or {}).get("data")
        check("C2 写入成功且读回与所写一致（逐字节）",
              ok_put and st2 == 200 and val1 == RAW,
              json.dumps({"put_ok": ok_put, "roundtrip": val1 == RAW, "len": len(str(val1))}, ensure_ascii=False))

        # C3 SQLite 直读（绕过 API，证明真的落在 config 表）
        # 语义：config 表存 serde_json::Value 的序列化形态 —— string 键的单元是
        # 「JSON 字符串字面量」（带引号转义，如 "{\"v\":1,...}"）。API 读回时解码，
        # 所以 C2 的逐字节往返成立；直读须与「RAW 的 JSON 编码」比对，且解码后 == RAW。
        raw_db = read_config_map(db_path).get(KEY)
        decoded_ok = False
        if isinstance(raw_db, str):
            try:
                decoded_ok = json.loads(raw_db) == RAW
            except Exception:  # noqa: BLE001
                decoded_ok = False
        check("C3 SQLite config 表直读 = 所写串的 JSON 编码（解码后逐字节一致）",
              decoded_ok,
              "直读一致（JSON 字符串字面量形态，解码 == RAW）" if decoded_ok
              else f"db={str(raw_db)[:80]}…")

        # C4 类型守卫：数组 body 必须被拒（expected_type=string）
        st4, body4 = http_json(f"{base}/api/v1/config/{KEY}", body=[1, 2, 3], method="PUT",
                               headers={"Content-Type": "application/json"})
        rejected_type = bool(body4) and body4.get("ok") is False
        # C4b 未登记键必须被拒（白名单仍然生效，本轮没有把门拆了）
        st5, body5 = http_json(f"{base}/api/v1/config/ai.models.evil", body="x", method="PUT",
                               headers={"Content-Type": "application/json"})
        rejected_unknown = bool(body5) and body5.get("ok") is False
        check("C4 类型守卫与键白名单仍然生效（数组被拒 / 未登记键被拒）",
              rejected_type and rejected_unknown,
              json.dumps({"数组被拒": rejected_type, "未登记被拒": rejected_unknown,
                          "错误": (body4 or {}).get("error", {}).get("message", "")[:60]}, ensure_ascii=False))

        # C5 schema_version = 13
        st6, body6 = http_json(f"{base}/api/v1/config/schema_version", method="GET")
        ver = (body6 or {}).get("data")
        check("C5 契约版本 = 13（schema_version 与 config.rs/migrations.rs 同源）",
              st6 == 200 and ver == 13, f"schema_version={ver}")

        # ---- 真重启：杀进程 → 重新启动 ----
        stop_app(proc)
        proc = None
        time.sleep(1.0)
        base2 = f"http://127.0.0.1:{boot()}"
        st7, body7 = http_json(f"{base2}/api/v1/config/{KEY}", method="GET")
        val2 = (body7 or {}).get("data")
        check("C6 **真重启**后归档仍在（进程被 terminate → 重新 boot → 读回一致）",
              st7 == 200 and val2 == RAW,
              json.dumps({"重启后一致": val2 == RAW, "端口变了": base2 != base}, ensure_ascii=False))

        # C7 重启后 schema_version 仍是 13（契约常量不是一次性写入）
        st8, body8 = http_json(f"{base2}/api/v1/config/schema_version", method="GET")
        check("C7 重启后 schema_version 仍为 13", st8 == 200 and (body8 or {}).get("data") == 13,
              f"schema_version={(body8 or {}).get('data')}")
    except Exception:
        tb = traceback.format_exc().strip().splitlines()
        check("④ 真 core 双启动（存储层真重启）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        stop_app(proc)
        shutil.rmtree(data_dir, ignore_errors=True)


# ================================================================ 主流程

def main() -> int:
    print("=== TECH-06-B 验收 · Part 1 模型清单持久化（ai.models.registry） ===")

    node_layer()
    t1_single_source()
    t2_no_localstorage_and_core_side()
    t3_registry_wiring()
    t4_no_new_backend_and_ui_frozen()
    run_dynamic()
    core_layer()

    total = len(RESULTS)
    fails = [r for r in RESULTS if not r[1]]
    print(f"=== 汇总 {total - len(fails)}/{total} ===")
    if fails:
        print("--- FAIL 明细 ---")
        for name, _, detail in fails:
            print(f"FAIL {name} — {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
