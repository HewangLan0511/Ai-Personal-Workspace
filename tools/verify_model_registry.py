#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TECH-03-A 验收 · Model Registry（T1~T6）。

## 怎么跑
领域层（`ui/src/ai/model/{model,provider,registry}.ts`）**零外部依赖**（不 import Vue / `@/`），
所以本脚本用项目自带的 `typescript` 把它编译成 CommonJS 丢进临时目录，
再用 `node` 直接驱动 —— 断言的是**真实源码编译出来的产物**，不是复述设计。

```
T1~T5  node 驱动领域层（确定性、无浏览器、无 core）
T6     ① 静态：领域层零耦合 + 既有 AI 链路符号完好 + 零接线
       ② Python 侧：ai.providers.registry / ai.service / ai.credentials 行为不变
       ③ 整仓构建：npm run build（vue-tsc + vite build）通过
```

## 为什么不用 Edge headless（对比 verify_tech01 / verify_tech02 的选择）
本次交付物是**纯领域层**，且执行原则明确"不做 UI"。用浏览器跑只会验证"我新加了一个页面"，
而本轮恰恰**不该**有页面。所以驱动方式选 Node —— 与实际被测物同层。

## 可信度纪律（acceptance-script-integrity skill）
- **T5 每个反例都带对照组**：同样的结构把密钥换成引用就必须通过，
  否则"拒绝"可能只是"这个结构本来就不被支持"；
- **T5 断言 store 无残留**：拒绝必须是原子的，不能留下半个模型；
- **T4 断言 `probed=false`**：缺 key 时"本地短路不发请求"必须可观测，
  否则"返回 no_api_key"可能只是请求失败了恰好被归类成 no_api_key；
- **T6 不宣称端到端**：AI 对话主链路（core + sidecar + 真实 Provider）由
  `verify_stage5.py` 覆盖，本脚本**不重跑**，只证明"符号与构建未被破坏"；
- 单项失败不连坐，失败打印原始异常尾。
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

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
MODEL_DIR = UI / "src" / "ai" / "model"
DOMAIN_FILES = ["model.ts", "provider.ts", "registry.ts"]
TSC = UI / "node_modules" / "typescript" / "lib" / "tsc.js"

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
        # 版本目录名如 22.22.2-3，按名倒序即"新版本优先"
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


def npm() -> str:
    """找 npm.cmd —— 同上，全部从环境变量推导。"""
    cands: list[str] = []
    pf = os.environ.get("ProgramFiles")
    if pf:
        cands.append(str(Path(pf) / "nodejs" / "npm.cmd"))
    which = shutil.which("npm")
    if which:
        cands.append(which)
    for cand in cands:
        if cand and Path(cand).exists():
            return str(cand)
    raise RuntimeError("找不到 npm")


# ---------------------------------------------------------------- 领域层编译

def compile_domain(tmp: Path) -> None:
    """把领域层三个文件编译成 CommonJS。失败即 FATAL（后续用例全部依赖它）。"""
    if not TSC.exists():
        raise RuntimeError(f"缺少 typescript 编译器：{TSC}（先 npm install）")
    args = [
        node(),
        str(TSC),
        "--target", "ES2022",
        "--module", "commonjs",
        "--moduleResolution", "node",
        "--strict",
        "--esModuleInterop",
        "--skipLibCheck",
        "--outDir", str(tmp),
        *[str(MODEL_DIR / f) for f in DOMAIN_FILES],
    ]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(UI), timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"tsc 编译失败（exit {proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    for f in DOMAIN_FILES:
        out = tmp / f.replace(".ts", ".js")
        if not out.exists():
            raise RuntimeError(f"编译产物缺失：{out}")


# ---------------------------------------------------------------- Node 侧 harness

HARNESS = r"""
'use strict';
const path = require('path');
const { validateModelProfile, looksLikeSecret, isValidAuthRef, deriveModelId } = require('./model.js');
const { ProviderRegistry, inferConnectionType, CloudApiAdapter, LocalRuntimeAdapter, AgentAdapter,
        PROVIDER_ERROR_CODES } = require('./provider.js');
const { ModelRegistry, createModelsApi, entryStatusOf } = require('./registry.js');

const checks = [];
function check(name, passed, detail) {
  checks.push([name, !!passed, String(detail)]);
}
function codesOf(err) {
  return (err && err.issues ? err.issues.map((i) => i.code) : []).sort().join(',');
}
function pathsOf(err) {
  return (err && err.issues ? err.issues.map((i) => i.path).join(',') : '');
}
function throwsWith(fn, code) {
  try { fn(); return { threw: false, codes: '', msg: '' }; }
  catch (e) { const c = codesOf(e); return { threw: true, codes: c, msg: String(e.message || e), hit: c.split(',').includes(code) }; }
}
/** 异步版：`async` 方法抛的是 rejected Promise，同步 try/catch 抓不到（会变成 unhandled rejection）。 */
async function rejectsWith(promise, code) {
  try { await promise; return { threw: false, codes: '', msg: '' }; }
  catch (e) { const c = codesOf(e); return { threw: true, codes: c, msg: String(e.message || e), hit: c.split(',').includes(code) }; }
}

// ---------------------------------------------------------------- 假 L0 / 假 IO

const L0 = [
  { id: 'openai',     label: 'OpenAI',       defaultEndpoint: 'https://api.openai.com/v1',   defaultModel: 'gpt-4o-mini',     needsKey: true,  enabled: true,  note: '', capabilities: ['chat', 'stream', 'models'] },
  { id: 'deepseek',   label: 'DeepSeek',     defaultEndpoint: 'https://api.deepseek.com/v1', defaultModel: 'deepseek-chat',   needsKey: true,  enabled: true,  note: '', capabilities: ['chat', 'stream', 'models'] },
  { id: 'compatible', label: 'OpenAI 兼容',  defaultEndpoint: '',                           defaultModel: '',                needsKey: true,  enabled: true,  note: '', capabilities: ['chat', 'stream', 'models'] },
  { id: 'ollama',     label: 'Ollama',       defaultEndpoint: 'http://localhost:11434',      defaultModel: 'qwen2.5:7b',      needsKey: false, enabled: true,  note: '', capabilities: ['chat', 'stream', 'models'] },
  { id: 'lmstudio',   label: 'LM Studio',    defaultEndpoint: 'http://localhost:1234/v1',    defaultModel: '',                needsKey: false, enabled: true,  note: '', capabilities: ['chat', 'stream', 'models'] },
  { id: 'web-ai',     label: '网页 AI',      defaultEndpoint: '',                           defaultModel: '',                needsKey: false, enabled: false, note: '尚未开放', capabilities: [] },
  { id: 'user-agent', label: '自定义 Agent', defaultEndpoint: '',                           defaultModel: '',                needsKey: false, enabled: false, note: '协议待定稿', capabilities: [] },
];

const NOW = 1700000000000;

/** 内存端口：canonical 落 core，io 可编程（可抛错）。 */
function makePorts(opts) {
  opts = opts || {};
  const kv = new Map();
  const cache = new Map();
  const creds = new Set(opts.creds || []);
  const calls = [];
  let ioMode = opts.ioMode || 'ok';
  const remote = opts.remoteModels || {};
  let canonicalMode = opts.canonicalMode || 'core';

  const ports = {
    io: {
      async listRemoteModels(pid, o) {
        calls.push({ fn: 'listRemoteModels', pid, opts: o });
        if (ioMode === 'refused') { const e = new Error('connect ECONNREFUSED 127.0.0.1:11434'); throw e; }
        if (ioMode === 'unauthorized') { const e = new Error('auth_failed: 401 invalid api key'); throw e; }
        if (ioMode === 'down') { const e = new Error('request failed: host unreachable, DNS error'); throw e; }
        return remote[pid] || [];
      },
    },
    capability: {
      async loadProviders() { return opts.providers === undefined ? L0 : opts.providers; },
      async loadSecretPresence() { return [...creds]; },
    },
    canonical: {
      keys: { provider: 'ai.provider.current', model: 'ai.model.current' },
      mirrorKeys: { provider: 'ui.ai.provider', model: 'ui.ai.model' },
      async read() {
        if (canonicalMode === 'dead') { throw new Error('core unreachable'); }
        const provider = kv.get('ai.provider.current') || '';
        const model = kv.get('ai.model.current') || '';
        if (!provider && !model) return null;
        return { values: { provider, model, apiBase: '' }, from: 'core' };
      },
      async write(patch) {
        if (canonicalMode === 'mirror') return { landedOn: 'mirror' };
        if (canonicalMode === 'dead') return { landedOn: 'none' };
        if (patch.provider !== undefined) kv.set('ai.provider.current', patch.provider);
        if (patch.model !== undefined) kv.set('ai.model.current', patch.model);
        return { landedOn: 'core' };
      },
    },
    cache: {
      read() {
        const provider = cache.get('ui.ai.provider') || '';
        const model = cache.get('ui.ai.model') || '';
        const apiBase = cache.get('ui.ai.apiBase') || '';
        if (!provider && !model && !apiBase) return null;
        return { provider, model, apiBase };
      },
      write(v) {
        if (v.provider !== undefined) cache.set('ui.ai.provider', v.provider);
        if (v.model !== undefined) cache.set('ui.ai.model', v.model);
        if (v.apiBase !== undefined) cache.set('ui.ai.apiBase', v.apiBase);
      },
      clear() { cache.clear(); },
    },
    secret: {
      refFor: (id) => 'pw/' + id.toLowerCase() + '/default',
      async has(id) { return creds.has(id); },
      async set(id, secret) {
        creds.add(id);
        return { provider: id, ref: 'pw/' + id + '/default', mask: secret.slice(0, 3) + '****' + secret.slice(-4), backend: 'memory' };
      },
      async remove(id) { return creds.delete(id); },
    },
    now: () => NOW,
  };
  return { ports, kv, cache, creds, calls, setIoMode: (m) => { ioMode = m; }, setCanonicalMode: (m) => { canonicalMode = m; } };
}

function newRegistry(opts) {
  const env = makePorts(opts);
  const reg = new ModelRegistry(env.ports);
  return { reg, env };
}

// ================================================================ T1 创建模型
(async () => {
  try {
    const { reg, env } = newRegistry({ creds: ['deepseek'] });
    await reg.hydrate();

    const a = reg.add({ provider: 'deepseek', model: 'deepseek-chat' });
    const t1a = {
      id: a.id,
      endpoint: a.connection.endpoint,
      authRef: a.connection.authRef,
      type: a.connection.type,
      chat: a.capabilities.chat,
      vision: a.capabilities.vision,
      enabled: a.status.enabled,
      available: a.status.available,
      created: a.metadata.createdAt,
      updated: a.metadata.updatedAt,
      derivedIdOk: deriveModelId('deepseek', 'deepseek-chat') === 'deepseek:deepseek-chat',
      hasRawKey: JSON.stringify(a).toLowerCase().includes('apikey') || JSON.stringify(a).toLowerCase().includes('sk-'),
    };
    check('T1a 创建云 API 模型（缺省填充 endpoint/authRef/能力）',
      a.id === 'deepseek:deepseek-chat' && a.connection.endpoint === 'https://api.deepseek.com/v1'
      && a.connection.authRef === 'pw/deepseek/default' && a.connection.type === 'api'
      && a.capabilities.chat === true && a.capabilities.vision === false
      && a.status.enabled === true && a.status.available === false
      && a.metadata.createdAt === NOW && a.metadata.updatedAt === NOW
      && t1a.derivedIdOk === true && t1a.hasRawKey === false,
      JSON.stringify(t1a));

    const b = reg.add({ provider: 'ollama', model: 'qwen2.5:7b' });
    const c = reg.add({ provider: 'compatible', model: 'my-gw', connection: { endpoint: 'http://127.0.0.1:9999/v1' }, capabilities: { vision: true } });
    check('T1b 创建本地模型（无需 key → local + 无 authRef）与自定义 endpoint',
      b.connection.type === 'local' && b.connection.endpoint === 'http://localhost:11434'
      && b.connection.authRef === undefined && b.capabilities.chat === true
      && c.connection.endpoint === 'http://127.0.0.1:9999/v1' && c.capabilities.vision === true,
      JSON.stringify({ b: b.connection, bCap: b.capabilities, c: c.connection, cCap: c.capabilities }));

    const list = reg.list();
    const api = createModelsApi(reg);
    check('T1c 列表/门面（models.list + get + 状态归约 + hasSecret）',
      list.length === 3 && api.list().length === 3
      && list.every((e) => e.status === 'unchecked')
      && list.find((e) => e.provider === 'deepseek').hasSecret === true
      && list.find((e) => e.provider === 'ollama').hasSecret === true
      && api.get('ollama:qwen2.5:7b') !== null,
      JSON.stringify(list));

    const dup = throwsWith(() => reg.add({ provider: 'deepseek', model: 'deepseek-chat' }), 'duplicate_id');
    const unk = throwsWith(() => reg.add({ provider: 'nope', model: 'x' }), 'provider_unknown');
    const dis = throwsWith(() => reg.add({ provider: 'web-ai', model: 'x' }), 'provider_disabled');
    check('T1d 重复 id / 未注册 Provider / 未开放 Provider 一律拒绝',
      dup.hit && unk.hit && dis.hit && reg.list().length === 3,
      JSON.stringify({ dup: dup.codes, unk: unk.codes, dis: dis.codes }));

    const mut = reg.get('deepseek:deepseek-chat');
    mut.name = 'HACKED';
    mut.connection.authRef = 'HACKED';
    check('T1e 取回的实体是副本（改它不影响注册表）',
      reg.get('deepseek:deepseek-chat').name !== 'HACKED'
      && reg.get('deepseek:deepseek-chat').connection.authRef === 'pw/deepseek/default',
      JSON.stringify(reg.get('deepseek:deepseek-chat')));
  } catch (e) {
    check('T1 创建模型', false, 'EXCEPTION: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : String(e)));
  }

  // ================================================================ T2 切换默认模型
  try {
    const { reg, env } = newRegistry({ creds: ['deepseek'] });
    await reg.hydrate();
    reg.add({ provider: 'deepseek', model: 'deepseek-chat' });
    reg.add({ provider: 'ollama', model: 'qwen2.5:7b' });
    reg.add({ provider: 'openai', model: 'gpt-4o-mini' });

    const before = reg.getDefault();
    const d1 = await reg.setDefault('deepseek:deepseek-chat');
    const defAfter = reg.list().filter((e) => e.isDefault).map((e) => e.id);
    const d2 = await reg.setDefault('ollama:qwen2.5:7b');
    const defAfter2 = reg.list().filter((e) => e.isDefault).map((e) => e.id);

    check('T2a setDefault 写 canonical 且列表标记随之切换',
      before.unset === true && d1.canonical.provider === 'deepseek'
      && d1.canonical.model === 'deepseek-chat' && d1.canonical.source === 'core'
      && d1.canonical.pendingSync === false && d1.canonical.stale === false
      && defAfter.length === 1 && defAfter[0] === 'deepseek:deepseek-chat'
      && d2.canonical.provider === 'ollama' && defAfter2.length === 1 && defAfter2[0] === 'ollama:qwen2.5:7b',
      JSON.stringify({ before: before.unset, d1: d1.canonical, defAfter, d2: d2.canonical, defAfter2 }));

    const { reg: reg2 } = newRegistry({ creds: ['deepseek'], canonicalSeed: null });
    // 共用同一份 canonical？—— 用同一 kv 模拟"重启后仍在"
    const shared = makePorts({ creds: ['deepseek'] });
    const r3 = new ModelRegistry(shared.ports);
    await r3.hydrate();
    r3.add({ provider: 'deepseek', model: 'deepseek-chat' });
    r3.add({ provider: 'ollama', model: 'qwen2.5:7b' });
    await r3.setDefault('deepseek:deepseek-chat');
    const r4 = new ModelRegistry(shared.ports); // 新实例、同一持久化层
    await r4.hydrate();
    r4.add({ provider: 'deepseek', model: 'deepseek-chat' });
    r4.add({ provider: 'ollama', model: 'qwen2.5:7b' });
    const survived = r4.getDefault();
    const survivedFlags = r4.list().filter((e) => e.isDefault).map((e) => e.id);

    check('T2b canonical 跨实例存活（默认值是真的持久化，不是会话内存）',
      survived.canonical.provider === 'deepseek' && survived.canonical.model === 'deepseek-chat'
      && survived.profile !== null && survived.profile.id === 'deepseek:deepseek-chat'
      && survived.dangling === false && survivedFlags.length === 1
      && survivedFlags[0] === 'deepseek:deepseek-chat',
      JSON.stringify({ canon: survived.canonical, flags: survivedFlags }));

    const dis = await rejectsWith(reg.setCanonical({ provider: 'web-ai' }), 'provider_disabled');
    const unk = await rejectsWith(reg.setCanonical({ provider: 'ghost' }), 'provider_unknown');
    check('T2c canonical 契约：未注册 / 未开放 Provider 一律拒绝',
      dis.hit && unk.hit && reg.getCanonical().provider === 'ollama',
      JSON.stringify({ dis: dis.codes, unk: unk.codes, now: reg.getCanonical().provider }));

    // 降级：L1 落不住 → 落过渡镜像 → pendingSync=true
    const mir = makePorts({ creds: ['deepseek'] });
    mir.setCanonicalMode('mirror');
    const rm = new ModelRegistry(mir.ports);
    await rm.hydrate();
    rm.add({ provider: 'deepseek', model: 'deepseek-chat' });
    const dm = await rm.setDefault('deepseek:deepseek-chat');
    check('T2d 降级①：L1 落不住 → source=mirror / pendingSync=true / stale=false',
      dm.canonical.source === 'mirror' && dm.canonical.pendingSync === true && dm.canonical.stale === false,
      JSON.stringify(dm.canonical));

    // 降级：core 完全不可达 → 读 L2 缓存
    const dead = makePorts({ creds: [] });
    dead.setCanonicalMode('dead');
    dead.cache.set('ui.ai.provider', 'ollama');
    dead.cache.set('ui.ai.model', 'qwen2.5:7b');
    const rd = new ModelRegistry(dead.ports);
    const rep = await rd.hydrate();
    const dc = rd.getCanonical();
    check('T2e 降级②：core 不可达 → source=cache / stale=true',
      dc.source === 'cache' && dc.stale === true && dc.provider === 'ollama' && dc.model === 'qwen2.5:7b'
      && rep.canonical.source === 'cache',
      JSON.stringify({ canon: dc, report: rep.canonical }));
  } catch (e) {
    check('T2 切换默认模型', false, 'EXCEPTION: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : String(e)));
  }

  // ================================================================ T3 删除模型
  try {
    const { reg, env } = newRegistry({ creds: ['deepseek'] });
    await reg.hydrate();
    reg.add({ provider: 'deepseek', model: 'deepseek-chat' });
    reg.add({ provider: 'ollama', model: 'qwen2.5:7b' });
    await reg.setDefault('deepseek:deepseek-chat');
    const secretsBefore = env.creds.size;

    const okRemoved = reg.remove('ollama:qwen2.5:7b');
    const ghostRemoved = reg.remove('does-not-exist');
    const afterNonDefault = { n: reg.list().length, def: reg.list().filter((e) => e.isDefault).map((e) => e.id) };

    const okDefault = reg.remove('deepseek:deepseek-chat');
    const view = reg.getDefault();
    check('T3a 删除：命中返回 true、未命中返回 false、列表收缩',
      okRemoved === true && ghostRemoved === false && afterNonDefault.n === 1
      && afterNonDefault.def.length === 1 && okDefault === true && reg.list().length === 0,
      JSON.stringify({ okRemoved, ghostRemoved, afterNonDefault, okDefault, n: reg.list().length }));

    check('T3b 契约：删默认模型不动 canonical（进入 dangling），也不动凭据',
      view.canonical.provider === 'deepseek' && view.canonical.model === 'deepseek-chat'
      && view.profile === null && view.dangling === true && view.unset === false
      && env.creds.size === secretsBefore,
      JSON.stringify({ canon: view.canonical, dangling: view.dangling, profile: view.profile, creds: [...env.creds] }));

    const reAdded = reg.add({ provider: 'deepseek', model: 'deepseek-chat' });
    const reView = reg.getDefault();
    check('T3c 重新加回同名模型 → canonical 自动认出它（不再 dangling）',
      reAdded.id === 'deepseek:deepseek-chat' && reView.dangling === false
      && reView.profile !== null && reView.profile.id === 'deepseek:deepseek-chat',
      JSON.stringify({ id: reAdded.id, dangling: reView.dangling }));
  } catch (e) {
    check('T3 删除模型', false, 'EXCEPTION: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : String(e)));
  }

  // ================================================================ T4 Provider 多类型注册
  try {
    const pr = new ProviderRegistry();
    const inferred = {
      ollama: inferConnectionType({ id: 'ollama' }),
      lmstudio: inferConnectionType({ id: 'lmstudio' }),
      openai: inferConnectionType({ id: 'openai' }),
      agent: inferConnectionType({ id: 'user-agent' }),
      loopback: inferConnectionType({ id: 'self-host', needsKey: false, defaultEndpoint: 'http://localhost:8080/v1' }),
      explicitWins: inferConnectionType({ id: 'ollama', connectionType: 'api' }),
    };
    check('T4a 连接类型推断（本地表 / Agent 表 / 回环 / 显式覆盖优先）',
      inferred.ollama === 'local' && inferred.lmstudio === 'local' && inferred.openai === 'api'
      && inferred.agent === 'agent' && inferred.loopback === 'local' && inferred.explicitWins === 'api',
      JSON.stringify(inferred));

    const toInput = (p) => ({ id: p.id, label: p.label, defaultEndpoint: p.defaultEndpoint, defaultModel: p.defaultModel, needsKey: p.needsKey, enabled: p.enabled, note: p.note, capabilities: p.capabilities });
    pr.registerMany(L0.map(toInput));
    const sizeBefore = pr.size();
    const myLocal = pr.registerProvider({ id: 'my-local', label: '我的本地服务', defaultEndpoint: 'http://localhost:5555/v1', defaultModel: 'local-a', needsKey: false });
    const myAgent = pr.registerProvider({ id: 'my-agent', label: '我的 Agent', connectionType: 'agent' });
    const myCloud = pr.registerProvider({ id: 'my-cloud', label: '我的云' });
    const adapters = {
      myLocal: pr.adapterFor('my-local') instanceof LocalRuntimeAdapter,
      myAgent: pr.adapterFor('my-agent') instanceof AgentAdapter,
      myCloud: pr.adapterFor('my-cloud') instanceof CloudApiAdapter,
      openai: pr.adapterFor('openai') instanceof CloudApiAdapter,
    };
    check('T4b 三类 Provider 注册后各自拿到对应适配器',
      myLocal.connectionType === 'local' && myAgent.connectionType === 'agent' && myCloud.connectionType === 'api'
      && adapters.myLocal && adapters.myAgent && adapters.myCloud && adapters.openai,
      JSON.stringify({ types: [myLocal.connectionType, myAgent.connectionType, myCloud.connectionType], adapters }));

    // 幂等：**用完整描述符**重放同一批 id（不能只传 {id} —— 那会把描述符清空）
    pr.registerMany(L0.map(toInput));
    const dupRemoved = pr.removeProvider('my-cloud');
    const dupRemoved2 = pr.removeProvider('my-cloud');
    check('T4c 重复登记幂等 + removeProvider 语义（命中 true / 未命中 false）',
      pr.size() === sizeBefore + 2 && dupRemoved === true && dupRemoved2 === false
      && pr.getProvider('my-cloud') === null && pr.has('my-local') === true,
      JSON.stringify({ sizeBefore, sizeNow: pr.size(), dupRemoved, dupRemoved2 }));

    const env = makePorts({ creds: ['deepseek'], remoteModels: { ollama: ['llama3:8b', 'qwen2.5:7b'], deepseek: ['deepseek-chat', 'deepseek-reasoner'] } });
    const modelsOllama = await pr.getModels('ollama', env.ports.io);
    const modelsGhost = await pr.getModels('ghost', env.ports.io);
    check('T4d getModels：默认模型置顶 + 远端去重 + 未知 Provider 返回空数组',
      modelsOllama.length === 2 && modelsOllama[0].model === 'qwen2.5:7b'
      && modelsOllama[0].source === 'remote' && modelsOllama[1].model === 'llama3:8b'
      && modelsGhost.length === 0,
      JSON.stringify({ modelsOllama, modelsGhost }));

    const noKey = await pr.testConnection('openai', env.ports.io, { hasSecret: false });
    const withKey = await pr.testConnection('deepseek', env.ports.io, { hasSecret: true });
    const ghost = await pr.testConnection('nope', env.ports.io, {});
    check('T4e testConnection：缺 key 本地短路（probed=false）/ 有 key 走真实探测 / 未注册 Provider 明确报错',
      noKey.ok === false && noKey.code === 'no_api_key' && noKey.probed === false
      && withKey.ok === true && withKey.code === 'ok' && withKey.modelCount === 2 && withKey.probed === true
      && ghost.ok === false && ghost.code === 'not_implemented' && /未注册/.test(ghost.message),
      JSON.stringify({ noKey, withKey, ghost }));

    const localDown = makePorts({ ioMode: 'refused', remoteModels: {} });
    const down = await pr.testConnection('ollama', localDown.ports.io, { hasSecret: true });
    const agent = await pr.testConnection('my-agent', env.ports.io, {});
    check('T4f 失败语义分流：本地不可达 → local_model_down；Agent → not_implemented',
      down.ok === false && down.code === 'local_model_down'
      && agent.ok === false && agent.code === 'not_implemented'
      && PROVIDER_ERROR_CODES.includes('local_model_down'),
      JSON.stringify({ down, agent }));
  } catch (e) {
    check('T4 Provider 多类型注册', false, 'EXCEPTION: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : String(e)));
  }

  // ================================================================ T5 非法模型配置拒绝
  try {
    const { reg } = newRegistry({ creds: ['deepseek'] });
    await reg.hydrate();
    reg.add({ provider: 'deepseek', model: 'deepseek-chat' });
    const baseline = reg.list().length;

    const cases = [];
    function expectReject(label, input, code) {
      const r = throwsWith(() => reg.add(input), code);
      cases.push({ label, codes: r.codes, paths: pathsOf(r), hit: !!r.hit, msg: r.msg.slice(0, 120) });
      return r;
    }
    expectReject('明文 key 塞进 authRef', { provider: 'deepseek', model: 'm1', connection: { authRef: 'sk-abcdefghijklmnopqrstuvwx' } }, 'auth_ref_invalid'); // fake key：测试输入，非凭据
    expectReject('明文 key 用 apiKey 字段名', { provider: 'deepseek', model: 'm2', extras: { apiKey: 'whatever-value' } }, 'secret_detected'); // fake key：测试输入，非凭据
    expectReject('明文 key 藏在 extras 的值里', { provider: 'deepseek', model: 'm3', extras: { note: 'sk-proj-abcdefghijklmnop' } }, 'secret_detected'); // fake key：测试输入，非凭据
    expectReject('token 字段名', { provider: 'deepseek', model: 'm4', extras: { token: 'x' } }, 'secret_detected');
    expectReject('非法连接类型', { provider: 'deepseek', model: 'm5', connection: { type: 'websocket' } }, 'bad_connection_type');
    expectReject('api 缺 endpoint', { provider: 'compatible', model: 'm6', connection: { type: 'api' } }, 'endpoint_required');
    expectReject('endpoint 非 http(s)', { provider: 'compatible', model: 'm7', connection: { type: 'api', endpoint: 'ftp://x/y' } }, 'endpoint_invalid');
    // `local_path_required` 属"模型层纯校验"：`add()` 会用 Provider 的 defaultEndpoint 兜底，
    // 那是对的行为 —— 所以这里直接在校验层验规则本身，而不是拿 add() 的兜底当规则失效。
    const localBare = validateModelProfile({
      id: 'ollama:m8', provider: 'ollama', name: 'm8', model: 'm8',
      connection: { type: 'local' },
      capabilities: { chat: true, vision: false, coding: false, agent: false },
      status: { enabled: true, available: false },
      metadata: { createdAt: NOW, updatedAt: NOW },
    });
    cases.push({
      label: 'local 既无 endpoint 也无 localPath',
      codes: localBare.issues.map((i) => i.code).join(','),
      hit: localBare.ok === false && localBare.issues.some((i) => i.code === 'local_path_required'),
      msg: '',
    });
    expectReject('空 provider / 空 model', { provider: '   ', model: '  ' }, 'empty_provider');
    expectReject('capabilities 非布尔', { provider: 'deepseek', model: 'm9', capabilities: { chat: 'yes' } }, 'bad_type');
    const notObj = validateModelProfile('not-an-object');
    cases.push({ label: '整体不是对象', codes: notObj.issues.map((i) => i.code).join(','), hit: notObj.ok === false && notObj.issues[0].code === 'not_object', msg: '' });

    const allHit = cases.every((c) => c.hit);
    check('T5a 11 类非法配置逐一拒绝（含明文密钥 4 类 + 结构 5 类 + 类型 2 类）',
      allHit, JSON.stringify(cases));

    check('T5b 拒绝是原子的：store 无残留（不产生"半个模型"）',
      reg.list().length === baseline && reg.get('deepseek:m1') === null,
      JSON.stringify({ baseline, now: reg.list().length }));

    // ---- 对照组：同样的结构，把"密钥"换成"引用"必须通过 ----
    const good = reg.add({
      provider: 'deepseek', model: 'm-ok',
      extras: { note: '普通备注，不是密钥' },
      connection: { authRef: 'pw/deepseek/default' },
    });
    const goodWithCustomKeyName = reg.add({ provider: 'deepseek', model: 'm-ok2', extras: { apiBase: 'https://x/y' } });
    check('T5c 对照组：同结构换成 Secret Reference / 普通备注 / apiBase 字段名 → 通过',
      good.metadata.extras.note === '普通备注，不是密钥'
      && good.connection.authRef === 'pw/deepseek/default'
      && goodWithCustomKeyName.metadata.extras.apiBase === 'https://x/y'
      && reg.list().length === baseline + 2,
      JSON.stringify({ n: reg.list().length, ref: good.connection.authRef, extras: good.metadata.extras }));

    // ---- 检测器单测（避免"只有 add() 拒绝"这种表层覆盖）----
    // 下面 3 个"像密钥"的串是 fake 测试输入（非凭据），专供检测器命中判定。
    const det = {
      sk: looksLikeSecret('sk-proj-abcdefghijklmnop'), // fake key：测试输入，非凭据
      bearer: looksLikeSecret('Bearer abcdefghijklmnop'),
      hex: looksLikeSecret('0123456789abcdef0123456789abcdef'),
      ref: looksLikeSecret('pw/deepseek/default'),
      url: looksLikeSecret('https://api.deepseek.com/v1'),
      // 本地权重路径：Windows 绝对路径，且**不含用户名**（门禁 A020 只禁用户绝对路径）
      path: looksLikeSecret('C:\\models\\qwen2.5-7b-instruct-q4_k_m.gguf'),
      short: looksLikeSecret('deepseek-chat'),
      refOk: isValidAuthRef('pw/deepseek/default'),
      refBad: isValidAuthRef('sk-abc'),
    };
    check('T5d 密钥检测器：命中 3 类真实密钥形态，且不误报引用 / URL / 路径 / 模型名',
      det.sk && det.bearer && det.hex && !det.ref && !det.url && !det.path && !det.short && det.refOk && !det.refBad,
      JSON.stringify(det));

    // ---- setCredential 只回掩码 ----
    const cred = await reg.setCredential('deepseek', 'sk-abcdefghijklmnopqrstuvwx'); // fake key：测试输入，非凭据
    const credAfter = reg.hasCredential('deepseek');
    check('T5e 写入凭据只回掩码，明文不进任何返回值 / 不进模型配置',
      cred.mask === 'sk-****uvwx' && !JSON.stringify(cred).includes('abcdefghijklmnop')
      && credAfter === true && !JSON.stringify(reg.exportProfiles()).includes('abcdefghijklmnop'),
      JSON.stringify({ cred, credAfter }));
  } catch (e) {
    check('T5 非法模型配置拒绝', false, 'EXCEPTION: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : String(e)));
  }

  // ---------------- 输出 ----------------
  const failed = checks.filter((c) => !c[1]).length;
  process.stdout.write('__RESULT__' + JSON.stringify({ checks }) + '\n');
  process.exit(failed === 0 ? 0 : 1);
})();
"""


def run_node_harness(tmp: Path) -> list[tuple[str, bool, str]]:
    harness = tmp / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    proc = subprocess.run(
        [node(), str(harness)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(tmp), timeout=300,
    )
    out = proc.stdout or ""
    payload = None
    for line in out.splitlines():
        if line.startswith("__RESULT__"):
            payload = json.loads(line[len("__RESULT__"):])
    if payload is None:
        raise RuntimeError(
            f"node 未产出结果（exit {proc.returncode}）\nSTDOUT:\n{out[-2000:]}\nSTDERR:\n{(proc.stderr or '')[-2000:]}"
        )
    return [(c[0], c[1], c[2]) for c in payload["checks"]]


# ---------------------------------------------------------------- T6 旧 AI 功能无影响

def t6_static() -> None:
    # ① 领域层零耦合：不 import Vue / @/ / 其它 app 层
    offenders: list[str] = []
    for f in DOMAIN_FILES:
        text = (MODEL_DIR / f).read_text(encoding="utf-8")
        for m in re.finditer(r"""from\s+['"]([^'"]+)['"]""", text):
            spec = m.group(1)
            if spec.startswith(".") or spec in ("vue",) or spec.startswith("@/"):
                if spec.startswith("@/") or spec == "vue":
                    offenders.append(f"{f} ← {spec}")
    check("T6a 领域层零耦合（model/provider/registry 不 import Vue、不 import @/）",
          not offenders, "无外部依赖（可被 Node 直接编译执行）" if not offenders else "; ".join(offenders))

    # ② 接线点收敛（TECH-03-A 是"零接线"；TECH-03-B §四 首次接线，语义有意升级）
    #    TECH-03-A 的边界是"没有任何既有文件 import 新层"。
    #    TECH-03-B TASK-04 明确要求把 AI 顶栏"当前模型"接到 ModelRegistry，
    #    于是本条的判据从"零接线"升级为 **"接线点白名单 + 白名单内不得写"**：
    #    既守住"不允许任意文件乱接"，又给唯一那一处只读展示开合法的门。
    WIRING_ALLOWED = {
        "components/AiSidebar.vue",        # 顶栏"当前模型"：纯展示
        "composables/useCurrentModel.ts",  # 只读桥：共享 Registry + 投影 canonical
        "stores/ai.ts",                    # TECH-04 §一：请求依据（启动采纳 + 改选择回写）
        # TECH-05-C §P0-1：模型管理中心（`/models`）。原型 UI-06 的落点，也是
        # TECH-03-A 注释里明写过的"将来的模型管理页"—— 它**就是**该写 canonical 的那一处。
        "views/ModelsView.vue",
        # TECH-05-D §P1-A：AI 助手应用层。冻结契约把 `readers.aiAssistantPage`
        # 定为 `"canonical"`，所以这两个文件必须能读 Registry —— 但只是**读**：
        # `service.ts` 用 `resolveForUi()` 解出本次请求目标（canonical 优先），
        # `bridge.ts` 取共享单例并拼装各层读取器。两者都不在写方法清单里（T6b2 守）。
        "ai/assistant/service.ts",
        "ai/assistant/bridge.ts",
    }
    # 白名单文件里**绝不允许**出现的持久化写方法（读方法如 refreshCanonical 不在此列：
    # 它只把 L1 重读进内存，不写 config / 不写凭据）。
    # 注：TECH-04 起 `stores/ai.ts` 也进白名单，但它只调 bridge 的语义化入口
    # （`resolveAtBoot` / `syncSelection`），**不直接**调任何 ModelRegistry 写方法 ——
    # "谁改 canonical"因此仍然只有一处。
    WRITE_IDENTS = ("setCanonical", "setDefault", "setCredential", "removeCredential", "importProfiles")

    # 只读铁律的豁免面（TECH-05-C §P0-1）：
    # 模型管理中心是**产品里唯一合法改模型的地方**（新增/删除/设默认都发生在这里），
    # 因此对它不适用"不得出现写方法"。其余接线点（AiSidebar / useCurrentModel /
    # stores/ai）仍然逐字扫描 —— 规则不是被放宽，而是被**划清了适用面**：
    #   只读消费方（显示/发请求）→ 不得写；
    #   管理页面（用户显式操作）→ 必须写（否则功能就是假的）。
    WRITE_ALLOWED = {"views/ModelsView.vue"}


    wired: list[str] = []
    for path in list((UI / "src").rglob("*.ts")) + list((UI / "src").rglob("*.vue")):
        if MODEL_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"""from\s+['"][^'"]*ai/model""", text) or "ai/model/" in text:
            wired.append(str(path.relative_to(UI / "src")).replace("\\", "/"))
    unexpected = sorted(set(wired) - WIRING_ALLOWED)
    check("T6b 接线点收敛（只有只读消费者 import 新层）", not unexpected,
          ("允许：" + ", ".join(sorted(WIRING_ALLOWED))) if not unexpected
          else ("越界接线：" + "; ".join(unexpected)))

    # ②b 只读铁律：接线点不得调用任何写方法
    leaks: list[str] = []
    for rel in sorted(WIRING_ALLOWED):
        if rel in WRITE_ALLOWED:
            continue
        f = UI / "src" / rel
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for ident in WRITE_IDENTS:
            if ident in text:
                leaks.append(f"{rel}:{ident}")
    check("T6b2 只读铁律（只读接线点不出现 setCanonical/setDefault/setCredential 等写方法）",
          not leaks,
          ("只读接线点只读：" + ", ".join(sorted(set(WIRING_ALLOWED) - WRITE_ALLOWED)))
          if not leaks else "; ".join(leaks))

    # ③ 既有 AI 链路符号完好（invoke 命令名 + 参数键 + 页面绑定）
    #
    # TECH-05-D §P1-A：请求链路收敛到应用层唯一入口后，`'ai_chat'` 的**家**从
    # `stores/ai.ts` 搬到 `ai/assistant/transport.ts`。锚点随之迁移并升级为
    # 双向断言（旧家必须已清空 + 新家必须就位）—— 判据跑在**去注释文本**上，
    # 避免"往注释里搬一行"就通过。
    store = (UI / "src" / "stores" / "ai.ts").read_text(encoding="utf-8")
    transport_file = UI / "src" / "ai" / "assistant" / "transport.ts"
    transport = transport_file.read_text(encoding="utf-8") if transport_file.exists() else ""
    sidebar = (UI / "src" / "components" / "AiSidebar.vue").read_text(encoding="utf-8")
    settings = (UI / "src" / "views" / "SettingsView.vue").read_text(encoding="utf-8")
    learning = (UI / "src" / "views" / "LearningView.vue").read_text(encoding="utf-8")
    symbols = {
        "ai_info": "invokeCore<" in store and "'ai_info'" in store,
        "ai_chat（迁移到 ai/assistant/transport.ts）": "'ai_chat'" in transport,
        "ai_chat（store 内已清空）": "'ai_chat'" not in store,
        "args.provider": "provider: this.providerId" in store,
        "args.model": "model: this.model" in store,
        "args.mode": "mode: this.mode" in store,
        "persist.provider": "'ui.ai.provider'" in store,
        "persist.model": "'ui.ai.model'" in store,
        "sidebar.bind": "ai.providerId" in sidebar and "ai.model" in sidebar,
        "settings.bind": "ai.providers" in settings,
        "learning.bind": "ai.providerId" in learning,
    }
    check("T6c 既有 AI 链路符号完好（invoke 命令 / 参数键 / 三处页面绑定）",
          all(symbols.values()), json.dumps(symbols, ensure_ascii=False))

    # ④ core 改动面（TECH-04 §一 有意变更：L1 键**已登记**）
    #    TECH-03-A/B 时期这里是"L1 键仍未登记（走镜像兜底）"。
    #    TECH-04 §一 明确要求"确定 ai.provider.current 的正式落点"，于是判据翻转为
    #    **"L1 键已在三处登记齐全"** —— 这比原来的否定式断言更强（能查出漏登一半）。
    config_rs = (ROOT / "core" / "src" / "db" / "config.rs").read_text(encoding="utf-8")
    commands_rs = (ROOT / "core" / "src" / "api" / "commands.rs").read_text(encoding="utf-8")
    l1_keys_registered = 0
    l1_detail: dict[str, bool] = {}
    for k in ("ai.provider.current", "ai.model.current"):
        in_keys = k in config_rs
        in_type = bool(re.search(r"\"%s\"" % re.escape(k), config_rs.split("fn expected_type")[-1].split("fn type_ok")[0])) if "fn expected_type" in config_rs else False
        in_default = bool(re.search(r"\"%s\"\s*=>" % re.escape(k), config_rs.split("fn default_for")[-1])) if "fn default_for" in config_rs else False
        l1_detail[k] = in_keys and in_type and in_default
        l1_keys_registered += 1 if l1_detail[k] else 0
    mirror_kept = ("\"ui.ai.provider\"" in config_rs) and ("\"ui.ai.model\"" in config_rs)
    ports_ts = (MODEL_DIR / "ports.ts").read_text(encoding="utf-8")
    cmds_used = set(re.findall(r"invokeCore<[^>]*>\('([a-z_]+)'", ports_ts)) | set(
        re.findall(r"invokeCore\('([a-z_]+)'", ports_ts))
    existing = set(re.findall(r"pub (?:async )?fn (\w+)", commands_rs))
    unknown_cmds = sorted(c for c in cmds_used if c not in existing)
    check("T6d core 面：L1 键已在 KEYS/type/default 三处登记 + 镜像键保留 + 端口只调既有命令",
          l1_keys_registered == 2 and mirror_kept and not unknown_cmds,
          json.dumps({"L1三处齐全": l1_detail, "镜像键保留": mirror_kept,
                      "端口使用的命令": sorted(cmds_used),
                      "不存在的命令": unknown_cmds}, ensure_ascii=False))


def t6_python_side() -> None:
    """Python 侧 AI 面必须原样（本轮一行没改；这条防的是"顺手改了没注意"）。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from ai.credentials import CredentialStore, ref_for
        from ai.providers import registry as ai_registry

        ids = sorted(ai_registry.PROVIDERS.keys())
        expected_ids = sorted(
            ["openai", "deepseek", "compatible", "ollama", "lmstudio", "web-ai", "user-agent"]
        )
        disabled = sorted(k for k, v in ai_registry.PROVIDERS.items() if not v.enabled)
        avail = ai_registry.available()
        shape_ok = all(
            set(["id", "label", "defaultBase", "defaultModel", "needsKey", "enabled", "note",
                 "capabilities"]).issubset(p.keys()) for p in avail
        )
        mask_ok = (
            CredentialStore.mask("sk-abcdefghijklmnop") == "sk-****mnop"  # fake key：测试输入，非凭据
            and CredentialStore.mask("") == ""
            and CredentialStore.mask("short") == "*****"
            and ref_for("deepseek") == "pw/deepseek/default"
            and ref_for("x", "alt") == "pw/x/alt"
        )
        check(
            "T6e Python 侧 AI 面原样（7 个 Provider / 2 个未开放 / available() 字段 / 掩码规则）",
            ids == expected_ids and disabled == ["user-agent", "web-ai"] and shape_ok and mask_ok,
            json.dumps({"ids": ids, "disabled": disabled, "shape": shape_ok, "mask": mask_ok},
                       ensure_ascii=False),
        )
    except Exception:
        tb = traceback.format_exc().strip().splitlines()
        check("T6e Python 侧 AI 面原样", False, "EXCEPTION: " + " | ".join(tb[-3:]))


def t6_build() -> None:
    """整仓构建：vue-tsc 类型检查 + vite build 全过 → 没有任何既有模块被破坏。"""
    proc = subprocess.run(
        [npm(), "run", "build"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(UI), timeout=600,
    )
    tail = (proc.stdout or "").strip().splitlines()
    err_tail = (proc.stderr or "").strip().splitlines()
    ok = proc.returncode == 0 and any("built in" in ln for ln in tail)
    check("T6f 整仓构建通过（vue-tsc --noEmit && vite build）", ok,
          f"exit={proc.returncode} " + " | ".join((tail[-2:] + err_tail[-2:]))[:300])


# ---------------------------------------------------------------- 主流程

def main() -> int:
    if not MODEL_DIR.exists():
        print(f"FATAL 缺少交付目录：{MODEL_DIR}")
        return 2
    print("=== TECH-03-A 验收 · Model Registry ===")
    tmp = Path(tempfile.mkdtemp(prefix="pw-model-registry-"))
    try:
        try:
            compile_domain(tmp)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check("T0 领域层编译（tsc → CommonJS）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
            raise SystemExit(1)

        check("T0 领域层编译（tsc → CommonJS）", True,
              f"{', '.join(f.replace('.ts', '.js') for f in DOMAIN_FILES)} → {tmp}")

        try:
            for name, passed, detail in run_node_harness(tmp):
                check(name, passed, detail)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check("T1~T5（node 驱动领域层）", False, "EXCEPTION: " + " | ".join(tb[-3:]))

        for fn in (t6_static, t6_python_side, t6_build):
            try:
                fn()
            except Exception:
                tb = traceback.format_exc().strip().splitlines()
                check(getattr(fn, "__name__", "T6"), False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # 收尾零残留

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== 汇总 {passed}/{total} ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
