#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-07 个人档案编辑体验补全（Edge 无头 + CDP）。

用例判据：
  T1 编辑入口：点击「编辑」→ 输入框出现、自动聚焦、保留原昵称、保存/取消在位。
  T2 保存：改名 → 展示立即变化（局部 diff：#profileHead 壳节点身份不变）、头像首字联动、toast。
  T3 取消：修改后取消 → 恢复原昵称，无保存结果（无 toast）。
  T4 扩展结构：profileField 接口在 UI 上可验证（data-field/data-editable/data-type 投影 + 编辑态闭环）。
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
    profile = tempfile.mkdtemp(prefix="edge_s7_")
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

        # ---------- 进入档案页 ----------
        ev("location.hash = '#/profile'")
        time.sleep(0.8)
        ev("""window.__head0 = document.getElementById('profileHead');
              window.__btn0 = document.querySelector('.page-head [data-act="profile-edit"]');""")

        # ---------- T1 编辑入口（UI-08：编辑卡原位展开） ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.4)
        s1 = ev("""(() => { const inp = document.getElementById('nicknameInput');
          const ed = document.getElementById('profileEditor');
          return {card: !!(ed && ed.querySelector('.card')), inp: !!inp, val: inp ? inp.value : '',
                  focused: document.activeElement === inp,
                  sel: inp ? (inp.selectionEnd - inp.selectionStart) === inp.value.length : false,
                  save: !!ed.querySelector('[data-act=\"profile-save\"]'),
                  cancel: !!ed.querySelector('[data-act=\"profile-cancel\"]'),
                  label: ed.textContent.includes('昵称')};
        })()""")
        ok = (s1["card"] and s1["inp"] and s1["val"] == "白宇" and s1["focused"] and s1["sel"]
              and s1["save"] and s1["cancel"] and s1["label"])
        check("T1 编辑入口：编辑卡原位展开 + 输入框自动聚焦全选 + 保留原昵称 + 保存/取消在位", ok, json.dumps(s1, ensure_ascii=False)[:160])

        # ---------- T2 保存（S2：壳节点身份不变） ----------
        ev("document.getElementById('nicknameInput').value = '白宇 2.0'")
        ev("document.querySelector('[data-act=\"profile-save\"]').click()")
        time.sleep(0.5)
        s2 = ev("""(() => ({
          headSame: document.getElementById('profileHead') === window.__head0,
          btnSame: document.querySelector('.page-head [data-act=\"profile-edit\"]') === window.__btn0,
          name: (document.querySelector('#profileHead [data-field=\"nickname\"]')||{textContent:''}).textContent,
          inpGone: !document.getElementById('nicknameInput'),
          avatar: (document.getElementById('profileAvatar')||{textContent:''}).textContent,
          toast: (document.getElementById('toastHost')||{textContent:''}).textContent
        }))()""")
        ok = (s2["headSame"] and s2["btnSame"] and s2["name"] == "白宇 2.0" and s2["inpGone"]
              and s2["avatar"] == "白" and "个人资料已更新" in s2["toast"])
        check("T2 保存：展示立即变化 + 页面壳节点身份不变 + 头像首字联动 + toast「个人资料已更新」", ok,
              f"name={s2['name']} headSame={s2['headSame']} toast={'个人资料已更新' in s2['toast']}")

        # ---------- T3 取消 ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.3)
        ev("document.getElementById('nicknameInput').value = '临时改名'")
        # 取消不应产生新 toast：对比 toastHost 数量（T2 的 toast 可能还在 2.2s 存活期内，不能查文本）
        ev("window.__tc = document.getElementById('toastHost').children.length")
        ev("document.querySelector('[data-act=\"profile-cancel\"]').click()")
        time.sleep(0.4)
        s3 = ev("""(() => ({
          name: (document.querySelector('#profileHead [data-field=\"nickname\"]')||{textContent:''}).textContent,
          inpGone: !document.getElementById('nicknameInput'),
          noNewToast: document.getElementById('toastHost').children.length <= window.__tc
        }))()""")
        ok = (s3["name"] == "白宇 2.0" and s3["inpGone"] and s3["noNewToast"])
        check("T3 取消：恢复保存过的原昵称，不产生保存结果（无新 toast）", ok,
              f"name={s3['name']} noNewToast={s3['noNewToast']}")

        # ---------- T3b Esc 取消（补充交互） ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.3)
        ev("document.getElementById('nicknameInput').value = 'Esc 改名'")
        ev("""document.getElementById('nicknameInput').dispatchEvent(
               new KeyboardEvent('keydown', {key:'Escape', bubbles:true}))""")
        time.sleep(0.4)
        s3b = ev("(document.querySelector('#profileHead [data-field=\"nickname\"]')||{textContent:''}).textContent")
        ok = s3b == "白宇 2.0"
        check("T3b Esc 取消：编辑态键盘退出恢复原昵称", ok, f"name={s3b}")

        # ---------- T4 扩展结构（profileField 接口投影） ----------
        s4 = ev("""(() => {
          const nick = document.querySelector('#profileHead [data-field=\"nickname\"]');
          const tag = document.querySelector('#profileHead [data-field=\"tagline\"]');
          return {nickOk: !!nick && nick.dataset.editable === 'true' && nick.dataset.type === 'text',
                  tagReadonly: !!tag && tag.dataset.editable === 'false' && tag.dataset.type === 'text',
                  nickVal: nick ? nick.textContent : ''};
        })()""")
        # 再走一遍完整编辑闭环证明字段由数据结构驱动
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.3)
        ev("document.getElementById('nicknameInput').value = '接口验证'")
        ev("document.querySelector('[data-act=\"profile-save\"]').click()")
        time.sleep(0.4)
        s4b = ev("(document.querySelector('#profileHead [data-field=\"nickname\"]')||{textContent:''}).textContent")
        ev("""(() => { document.querySelector('.page-head [data-act=\"profile-edit\"]').click();
             document.getElementById('nicknameInput').value = '白宇';
             document.querySelector('[data-act=\"profile-save\"]').click(); })()""")
        time.sleep(0.4)
        ok = (s4["nickOk"] and s4["tagReadonly"] and s4b == "接口验证")
        check("T4 扩展结构：profileField(id/label/value/editable/type) 接口在 UI 可验证且驱动编辑闭环", ok,
              f"nickOk={s4['nickOk']} tagReadonly={s4['tagReadonly']} driven={s4b}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
