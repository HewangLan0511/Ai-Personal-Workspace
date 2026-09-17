#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-04-B 档案扩展块系统 + 生活页插件化槽位（Edge 无头 + CDP）。

用例判据（★ 判据是 DOM 节点身份 + state 驱动的结构变化，不是"看起来有"）：
  T1 档案页扩展区：3 张扩展块卡齐全，来源 chip 正确，pending 卡有「待确认」+ 确认按钮。
  T2 确认写入：pending → applied（badge 消失），#profileExts 容器身份保留（局部更新）。
  T3 选择器添加/移除：抽屉添加「习惯打卡」→ 页面出现；移除 → 消失；容器身份始终保留。
  T4 生活页槽位：卡片头部带来源标签；管理抽屉关掉天气 → 网格无天气卡（身份保留）；
     再打开 → 回来；市场添加「日程」→ 今日日程卡出现。
  T5 故障对照组：render() 必须抹掉 #lifeGrid 身份标记（证明探针有区分度）。
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
    profile = tempfile.mkdtemp(prefix="edge_b_")
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
            last = ""
            for _ in range(100):
                try:
                    if ev("!!document.querySelector('.rsh--ai')"):
                        return True
                    last = ev("document.readyState + '|' + location.hash")
                except Exception as e:
                    last = repr(e)[:120]
                time.sleep(0.3)
            print("页面未就绪，最后状态:", last)
            return False
        assert wait_ready(), "页面未就绪"

        # ---------- T1 档案页扩展区 ----------
        ev("location.hash = '#/profile'")
        time.sleep(0.6)
        r = ev("""(() => {
          const box = document.getElementById('profileExts');
          if(!box) return {ok:false};
          box.dataset.probe = 'keep';
          const cards = [...box.querySelectorAll(':scope > .card')];
          const has = id => state.profileExts.some(e=>e.id===id);
          const pending = box.querySelector('[data-act="profile-ext-confirm"]');
          const chips = box.textContent;
          return {ok:true,
                  n: state.profileExts.length,
                  ids: state.profileExts.map(e=>e.id),
                  hasPending: !!pending,
                  srcAI: chips.includes('AI 建议'),
                  srcPlugin: chips.includes('插件同步'),
                  srcManual: chips.includes('手动添加'),
                  addCard: !!box.querySelector('[data-act="profile-ext-open"]')};
        })()""")
        ok = (r.get("ok") and r["n"] == 3 and set(r["ids"]) == {"cert","course","reading"}
              and r["hasPending"] and r["srcAI"] and r["srcPlugin"] and r["srcManual"] and r["addCard"])
        check("T1 档案扩展区：3 块齐全 + 来源 chip + pending 确认入口 + 添加虚卡", ok, json.dumps(r, ensure_ascii=False))

        # ---------- T2 确认写入 ----------
        ev("document.querySelector('[data-act=\"profile-ext-confirm\"]').click()")
        time.sleep(0.3)
        r = ev("""(() => { const box = document.getElementById('profileExts');
          return {kept: box.dataset.probe === 'keep',
                  pendingGone: !box.querySelector('[data-act="profile-ext-confirm"]'),
                  applied: state.profileExts.every(e=>e.status==='applied')}; })()""")
        check("T2 确认写入：pending→applied 且容器身份保留", r["kept"] and r["pendingGone"] and r["applied"],
              f"kept={r['kept']} pendingGone={r['pendingGone']} applied={r['applied']}")

        # ---------- T3 选择器添加 + 移除 ----------
        ev("document.querySelector('#profileExts [data-act=\"profile-ext-open\"]').click()")
        time.sleep(0.4)
        r = ev("""(() => {
          const drawer = document.querySelector('.drawer');
          if(!drawer) return {drawer:false};
          const btn = drawer.querySelector('[data-act="profile-ext-add"][data-v="habit"]');
          if(!btn) return {drawer:true, btn:false};
          btn.click();
          return {drawer:true, btn:true};
        })()""")
        time.sleep(0.4)
        r2 = ev("""(() => { const box = document.getElementById('profileExts');
          const drawer = document.querySelector('.drawer');
          return {kept: box.dataset.probe === 'keep',
                  habitIn: state.profileExts.some(e=>e.id==='habit'),
                  cardIn: !!box.querySelector('[data-act="profile-ext-remove"][data-v="habit"]'),
                  drawerMarked: drawer && drawer.textContent.includes('已添加')}; })()""")
        ev("document.querySelector('[data-act=\"profile-ext-remove\"][data-v=\"habit\"]').click()")
        time.sleep(0.3)
        r3 = ev("""(() => ({kept: document.getElementById('profileExts').dataset.probe === 'keep',
                  habitGone: !state.profileExts.some(e=>e.id==='habit')}))()""")
        ok = (r.get("drawer") and r.get("btn") and r2["kept"] and r2["habitIn"] and r2["cardIn"]
              and r2["drawerMarked"] and r3["kept"] and r3["habitGone"])
        check("T3 扩展块选择器：添加→页面+抽屉同步；移除→消失；身份保留", ok,
              f"open={json.dumps(r)} add={json.dumps(r2)} rm={json.dumps(r3)}")
        ev("document.querySelector('.drawer [data-act=\"close-layer\"], .scrim') && (()=>{const b=document.querySelector('.drawer-foot [data-act=\"close-layer\"]'); if(b) b.click();})()")
        time.sleep(0.3)

        # ---------- T4 生活页槽位 ----------
        ev("location.hash = '#/life'")
        time.sleep(0.6)
        r = ev("""(() => {
          const g = document.getElementById('lifeGrid');
          if(!g) return {ok:false};
          g.dataset.probe = 'keep';
          return {ok:true,
                  srcSys: g.textContent.includes('系统'),
                  srcWeather: g.textContent.includes('天气插件'),
                  srcMsg: g.textContent.includes('消息插件'),
                  srcMusic: g.textContent.includes('音乐插件'),
                  manageBtn: !!document.querySelector('[data-act="life-manage"]')};
        })()""")
        ok = (r.get("ok") and r["srcSys"] and r["srcWeather"] and r["srcMsg"] and r["srcMusic"] and r["manageBtn"])
        check("T4a 生活页槽位：来源标签齐全 + 管理入口", ok, json.dumps(r, ensure_ascii=False))

        ev("document.querySelector('[data-act=\"life-manage\"]').click()")
        time.sleep(0.4)
        ev("document.querySelector('.drawer [data-act=\"life-slot-sw\"][data-v=\"weather\"]').click()")
        time.sleep(0.4)
        r1 = ev("""(() => { const g = document.getElementById('lifeGrid');
          const sw = document.querySelector('.drawer [data-act="life-slot-sw"][data-v="weather"]');
          return {kept: g.dataset.probe === 'keep',
                  weatherOff: !g.textContent.includes('28°'),
                  swOff: sw && !sw.classList.contains('on'),
                  gridOn: state.lifeSlots.find(s=>s.id==='weather').on === false}; })()""")
        ev("document.querySelector('.drawer [data-act=\"life-slot-sw\"][data-v=\"weather\"]').click()")
        time.sleep(0.4)
        r2 = ev("""(() => ({kept: document.getElementById('lifeGrid').dataset.probe === 'keep',
                  weatherBack: document.getElementById('lifeGrid').textContent.includes('28°')}))()""")
        ev("document.querySelector('.drawer [data-act=\"life-slot-add\"], .drawer [data-act=\"close-layer\"]') && (()=>{const b=document.querySelector('.drawer-foot [data-act=\"close-layer\"]'); if(b) b.click();})()")
        time.sleep(0.3)
        ev("document.querySelector('#lifeGrid [data-act=\"life-slot-add\"][data-v=\"calendar\"]').click()")
        time.sleep(0.3)
        r3 = ev("""(() => { const g = document.getElementById('lifeGrid');
          return {kept: g.dataset.probe === 'keep',
                  calIn: g.textContent.includes('今日日程'),
                  slotIn: state.lifeSlots.some(s=>s.id==='calendar')}; })()""")
        ok = (r1["kept"] and r1["weatherOff"] and r1["swOff"] and r1["gridOn"]
              and r2["kept"] and r2["weatherBack"] and r3["kept"] and r3["calIn"] and r3["slotIn"])
        check("T4b 槽位开关/添加：天气关→网格消失（身份保留）→开→回来；市场添加日程", ok,
              f"off={json.dumps(r1)} on={json.dumps(r2)} add={json.dumps(r3)}")

        # ---------- T5 故障对照组 ----------
        ev("document.getElementById('lifeGrid').dataset.probe = 'keep'")
        ev("render()")
        r = ev("document.getElementById('lifeGrid').dataset.probe !== 'keep'")
        check("T5 故障对照组（render() 必须抹掉身份标记）", r is True, f"rebuilt={r}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
