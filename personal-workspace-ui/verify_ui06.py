#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-06 模型管理中心（Edge 无头 + CDP）。

用例判据：
  T1 页面可访问：#/models 结构完整（当前模型卡 + 3 模型卡 + 添加入口），无 registry/canonical/adapter 字样。
  T2 切换模型（S2）：drawer 切换 → 当前模型卡局部更新，页面壳节点身份不变（不整页重绘）。
  T3 测试连接：卡片出延迟 chip + 未配置→已连接（演示数据）。
  T4 设为默认：当前 chip 转移 + 顶部当前模型同步。
  T5 添加流程：类型三选 → 本地模型字段 → 保存 → 卡片即时出现（局部）。
  T6 删除：卡片移除，数量回落。
  T7 空状态：删空后出现「还没有添加模型」引导文案 + 顶部显示 未设置模型。
  T8 AI 页入口：当前模型 chip 展示并跳转模型管理。
  T9 设置入口：设置 → AI 与模型 分类含模型管理入口，可跳转。
  T10 响应式：1920 / 1366 / 900 无横向溢出。
"""
import base64, json, os, shutil, socket, struct, subprocess, sys, tempfile, time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "index.html").as_uri()


def find_edge():
    roots = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        b = os.environ.get(var)
        if b:
            roots.append(Path(b))
    for root in roots:
        c = root.joinpath("Microsoft", "Edge", "Application", "msedge.exe")
        if c.exists():
            return str(c)
    return shutil.which("msedge")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class WS:
    def __init__(self, sock, initial):
        self.s = sock; self.buf = initial; self._id = 0

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk: raise RuntimeError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]; return out

    def _frame(self):
        b0, b1 = self._need(2)
        op = b0 & 0x0F; ln = b1 & 0x7F
        if ln == 126: ln = struct.unpack(">H", self._need(2))[0]
        elif ln == 127: ln = struct.unpack(">Q", self._need(8))[0]
        if b1 & 0x80:
            mask = self._need(4)
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._need(ln)))
        else: data = self._need(ln)
        return op, data

    def send(self, text, op=0x1):
        data = text.encode()
        h = bytearray([0x80 | op]); n = len(data)
        if n < 126: h.append(0x80 | n)
        elif n < 65536: h.append(0x80 | 126); h += struct.pack(">H", n)
        else: h.append(0x80 | 127); h += struct.pack(">Q", n)
        mask = os.urandom(4); h += mask
        self.s.sendall(bytes(h) + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def call(self, method, params=None, timeout=90):
        self._id += 1; mid = self._id
        self.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        self.s.settimeout(timeout)
        while True:
            op, data = self._frame()
            if op == 0x9: self.send(data.decode("utf-8", "replace"), op=0xA); continue
            if op == 0x8: raise RuntimeError("closed by peer")
            if op not in (0x1, 0x2): continue
            msg = json.loads(data.decode("utf-8", "replace"))
            if msg.get("id") != mid: continue
            if "error" in msg: raise RuntimeError(json.dumps(msg["error"])[:400])
            return msg.get("result", {})


def connect(port, tries=60):
    last = ""
    for _ in range(tries):
        try:
            raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2).read()
            for t in json.loads(raw):
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    u = urlparse(t["webSocketDebuggerUrl"])
                    s = socket.create_connection((u.hostname, u.port), timeout=20)
                    key = base64.b64encode(os.urandom(16)).decode()
                    s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
                    buf = b""
                    while b"\r\n\r\n" not in buf: buf += s.recv(4096)
                    head, rest = buf.split(b"\r\n\r\n", 1)
                    if "101" not in head.split(b"\r\n")[0].decode("latin1"):
                        raise RuntimeError("handshake fail")
                    return WS(s, rest)
        except Exception as e:
            last = repr(e)[:160]
        time.sleep(0.4)
    raise RuntimeError("cannot attach; last=" + last)


def main():
    EDGE = find_edge()
    if not EDGE:
        print("FAIL 找不到 Edge"); return 2
    port = free_port()
    profile = tempfile.mkdtemp(prefix="edge_s6_")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--allow-file-access-from-files",
         "--window-size=1600,1000", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", PAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results = []
    def check(name, ok, detail):
        results.append((name, ok, detail))
        print(("PASS" if ok else "FAIL"), name, "｜", detail)

    try:
        ws = connect(port)
        def ev(js):
            r = ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True,
                                             "awaitPromise": True}, timeout=30)
            if r.get("exceptionDetails"):
                raise RuntimeError("页面求值异常: " + json.dumps(r["exceptionDetails"])[:300])
            return r.get("result", {}).get("value")

        def wait_ready():
            for _ in range(100):
                try:
                    if ev("!!document.querySelector('.rsh--ai')"):
                        return True
                except Exception: pass
                time.sleep(0.3)
            return False
        assert wait_ready(), "页面未就绪"

        # ---------- T1 页面可访问 ----------
        ev("location.hash = '#/models'")
        time.sleep(0.8)
        s1 = ev("""(() => {
          /* innerText 只取渲染文本，不会把 <script> 里的注释误当页面文案 */
          const t = document.getElementById('modelPage') ? document.body.innerText : '';
          return {page: !!document.getElementById('modelPage'),
            cur: (document.getElementById('curModelCard')||{textContent:''}).textContent,
            cards: document.querySelectorAll('#modelGrid .model-card').length,
            add: !!document.querySelector('[data-act="model-add"]'),
            leak: /registry|canonical|adapter/i.test(t)};
        })()""")
        ok = (s1["page"] and "GPT-5" in s1["cur"] and s1["cards"] == 3 and s1["add"] and not s1["leak"])
        check("T1 页面可访问：当前模型卡 + 3 卡 + 添加入口，无技术词泄漏", ok,
              f"cards={s1['cards']} leak={s1['leak']} cur={s1['cur'][:40]}")

        # ---------- T2 切换模型（S2 局部 diff，壳节点身份不变） ----------
        ev("""window.__mp = document.getElementById('modelPage');
              window.__tp = document.querySelector('.page-head .t-page');""")
        ev("document.querySelector('[data-act=\"model-switch-open\"]').click()")
        time.sleep(0.4)
        rows = ev("document.querySelectorAll('.drawer [data-act=\"model-switch\"]').length")
        ev("document.querySelector('.drawer [data-act=\"model-switch\"][data-v=\"m2\"]').click()")
        time.sleep(0.6)
        s2 = ev("""(() => ({
          same: document.getElementById('modelPage') === window.__mp
             && document.querySelector('.page-head .t-page') === window.__tp,
          cur: (document.getElementById('curModelCard')||{textContent:''}).textContent,
          m2cur: !!(document.querySelector('#modelGrid .model-card[data-mid=\"m2\"] .chip--brand')),
          drawerGone: !document.querySelector('.drawer'),
          toast: (document.getElementById('toastHost')||{textContent:''}).textContent
        }))()""")
        ok = (rows == 3 and s2["same"] and "Qwen2.5-7B" in s2["cur"] and s2["m2cur"]
              and s2["drawerGone"] and "已切换到" in s2["toast"])
        check("T2 切换模型：局部更新（页面壳节点身份不变）+ 当前 chip 转移 + toast", ok,
              f"rows={rows} same={s2['same']} cur={s2['cur'][:30]}")

        # ---------- T3 测试连接（未配置 → 已连接 + 延迟 chip） ----------
        ev("document.querySelector('#modelGrid .model-card[data-mid=\"m3\"] [data-act=\"model-test\"]').click()")
        time.sleep(0.4)
        s3 = ev("""(() => { const c = document.querySelector('#modelGrid .model-card[data-mid=\"m3\"]');
          return {t: c.textContent, same: document.getElementById('modelPage') === window.__mp}; })()""")
        ok = ("38ms" in s3["t"] and "已连接" in s3["t"] and s3["same"])
        check("T3 测试连接：延迟 chip（演示数据）+ 未配置转已连接", ok, s3["t"][:80])

        # ---------- T4 设为默认 ----------
        ev("document.querySelector('#modelGrid .model-card[data-mid=\"m3\"] [data-act=\"model-default\"]').click()")
        time.sleep(0.4)
        s4 = ev("""(() => ({
          cur: (document.getElementById('curModelCard')||{textContent:''}).textContent,
          m3cur: !!(document.querySelector('#modelGrid .model-card[data-mid=\"m3\"] .chip--brand')),
          defBtnGone: !document.querySelector('#modelGrid .model-card[data-mid=\"m3\"] [data-act=\"model-default\"]')
        }))()""")
        ok = ("Claude" in s4["cur"] and s4["m3cur"] and s4["defBtnGone"])
        check("T4 设为默认：当前 chip 转移 + 顶部当前模型同步", ok, f"cur={s4['cur'][:30]}")

        # ---------- T5 添加流程（本地模型） ----------
        ev("document.querySelector('.page-head [data-act=\"model-add\"]').click()")
        time.sleep(0.4)
        picks = ev("document.querySelectorAll('.drawer .pick').length")
        ev("document.querySelector('.drawer .pick[data-act=\"model-add-type\"][data-v=\"local\"]').click()")
        time.sleep(0.4)
        fields = ev("""(() => ({
          addr: !!document.getElementById('mAddr'), mname: !!document.getElementById('mMname'),
          apiField: !!document.getElementById('mEndpoint')
        }))()""")
        ev("document.getElementById('modelName').value='Llama-3-8B'")
        ev("document.getElementById('mAddr').value='http://127.0.0.1:11434'")
        ev("document.getElementById('mMname').value='llama3:8b'")
        ev("document.querySelector('.drawer [data-act=\"model-add-save\"]').click()")
        time.sleep(0.6)
        s5 = ev("""(() => ({
          n: document.querySelectorAll('#modelGrid .model-card').length,
          newCard: (document.querySelector('#modelGrid .model-card[data-mid]:last-child')||{textContent:''}).textContent,
          drawerGone: !document.querySelector('.drawer')
        }))()""")
        ok = (picks == 3 and fields["addr"] and fields["mname"] and not fields["apiField"]
              and s5["n"] == 4 and "Llama-3-8B" in s5["newCard"] and "本地模型" in s5["newCard"] and s5["drawerGone"])
        check("T5 添加流程：3 类型选择 → 本地模型字段 → 卡片即时出现（局部）", ok,
              f"picks={picks} n={s5['n']} new={s5['newCard'][:40]}")

        # ---------- T6 删除 ----------
        s6 = ev("""(() => {
          const c = document.querySelector('#modelGrid .model-card:last-child');
          const name = c.querySelector('.t-card').textContent;
          c.querySelector('[data-act=\"model-del\"]').click();
          return {name, after: document.querySelectorAll('#modelGrid .model-card').length};
        })()""")
        ok = (s6["name"] == "Llama-3-8B" and s6["after"] == 3)
        check("T6 删除：卡片移除 + 数量回落到 3", ok, f"del={s6['name']} after={s6['after']}")

        # ---------- T7 空状态 ----------
        # 每次删除都局部重建 grid —— 必须循环现查现点（forEach 拿旧引用会点到 detached 节点）
        ev("""(() => { let guard = 10;
          while(document.querySelector('#modelGrid [data-act="model-del"]') && guard-- > 0){
            document.querySelector('#modelGrid [data-act="model-del"]').click();
          } })()""")
        time.sleep(0.5)
        s7 = ev("""(() => ({
          t: (document.getElementById('modelGrid')||{textContent:''}).textContent,
          cur: (document.getElementById('curModelCard')||{textContent:''}).textContent,
          addRowHidden: document.getElementById('modelAddRow').style.display === 'none',
          emptyAdd: !!document.querySelector('#modelGrid [data-act=\"model-add\"]')
        }))()""")
        ok = ("还没有添加模型" in s7["t"] and "连接一个AI模型" in s7["t"]
              and "未设置模型" in s7["cur"] and s7["addRowHidden"] and s7["emptyAdd"])
        check("T7 空状态：引导文案 + 顶部未设置模型 + 底部入口隐藏/空态内保留添加", ok,
              f"addRowHidden={s7['addRowHidden']}")

        # ---------- T8 AI 页入口（含返回来源记忆） ----------
        ev("location.hash = '#/ai'")
        time.sleep(0.8)
        s8 = ev("""(() => { const b = document.querySelector('.page-head [data-act=\"models-entry\"][data-v=\"ai\"]');
          return {exists: !!b, t: b ? b.textContent : ''}; })()""")
        if s8["exists"]: ev("document.querySelector('.page-head [data-act=\"models-entry\"][data-v=\"ai\"]').click()")
        time.sleep(0.8)
        on_models = ev("!!document.getElementById('modelPage')")
        # 返回按钮应回到 AI 助手页（跳转来源），不是设置
        ev("document.getElementById('modelBackBtn').click()")
        time.sleep(0.8)
        back_ai = ev("""(() => ({
          hash: location.hash,
          isAi: !!document.querySelector('.page-head [data-act=\"models-entry\"][data-v=\"ai\"]'),
          noModels: !document.getElementById('modelPage')
        }))()""")
        ok = (s8["exists"] and "当前模型：" in s8["t"] and on_models
              and back_ai["hash"] == "#/ai" and back_ai["isAi"] and back_ai["noModels"])
        check("T8 AI 页入口：chip 跳转模型管理 → 返回按钮回到 AI 助手页（来源记忆）", ok,
              f"t={s8['t'][:26]} onModels={on_models} back={back_ai['hash']}")

        # ---------- T9 设置入口（含返回设置） ----------
        ev("location.hash = '#/settings'")
        time.sleep(0.8)
        ev("document.querySelector('[data-act=\"set-cat\"][data-v=\"ai\"]').click()")
        time.sleep(0.5)
        s9 = ev("""(() => {
          const body = document.querySelector('.set-body');
          const btn = document.querySelector('.set-body [data-act=\"models-entry\"][data-v=\"settings\"]');
          return {t: body ? body.textContent : '', hasBtn: !!btn};
        })()""")
        if s9["hasBtn"]: ev("document.querySelector('.set-body [data-act=\"models-entry\"][data-v=\"settings\"]').click()")
        time.sleep(0.8)
        on_models2 = ev("!!document.getElementById('modelPage')")
        ev("document.getElementById('modelBackBtn').click()")
        time.sleep(0.8)
        back_set = ev("""(() => ({
          hash: location.hash, hasSetBody: !!document.querySelector('.set-body'),
          noModels: !document.getElementById('modelPage')
        }))()""")
        ok = ("AI 与模型" in s9["t"] and "模型管理" in s9["t"] and s9["hasBtn"] and on_models2
              and back_set["hash"] == "#/settings" and back_set["hasSetBody"] and back_set["noModels"])
        check("T9 设置入口：AI 与模型 → 打开模型管理 → 返回回设置", ok,
              f"onModels={on_models2} back={back_set['hash']}")

        # ---------- T10 响应式 ----------
        ev("location.hash = '#/models'")   # T9 结尾已返回设置页，先回模型管理页
        time.sleep(0.8)
        resp = []
        for w in (1920, 1366, 900):
            ws.call("Emulation.setDeviceMetricsOverride",
                    {"width": w, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
            time.sleep(0.5)
            r = ev("""(() => ({
              sw: document.documentElement.scrollWidth, iw: window.innerWidth,
              page: !!document.getElementById('modelPage')
            }))()""")
            resp.append((w, r))
        ws.call("Emulation.clearDeviceMetricsOverride")
        ok = all(r["sw"] <= r["iw"] + 1 and r["page"] for _, r in resp)
        check("T10 响应式：1920/1366/900 模型管理页均无横向溢出", ok,
              " ".join(f"{w}:sw{r['sw']}/iw{r['iw']}" for w, r in resp))
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
