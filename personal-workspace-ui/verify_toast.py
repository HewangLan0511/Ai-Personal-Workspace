#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：Toast 队列规则（Edge 无头 + CDP）。

规则（2026-09-14 用户规定）：
  同一时刻最多 2 条；第 3 条进来自动**淡出**最旧的一条；
  每条既可点击关闭，也会在 2.2s 后自动淡出。

被修的 bug：旧实现共享一个 toastTimer，新弹窗 clearTimeout 会取消旧弹窗的
自动消失 → 弹窗滞留不退；超额时 firstElementChild.remove() 硬删无淡出。

用例判据：
  T1 超额挤旧：toast×3 → 存活 2 条、最旧者带 .out 淡出类（不是硬删）、稍后被移除。
  T2 点击关闭：点击后 .out 淡出类挂上、随后移除。
  T3 自动消失：2.2s 后节点从 DOM 移除。
  T4 计时器独立（回归核心 bug）：A 先弹、1.5s 后弹 B；A 的年龄到点必须自己退场
     （旧实现里 B 的 clearTimeout 会让 A 永远滞留 —— 此用例必红）。
"""
import base64, json, os, shutil, socket, struct, subprocess, sys, tempfile, time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "index.html").as_uri()


def find_edge():
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        b = os.environ.get(var)
        if not b: continue
        c = Path(b).joinpath("Microsoft", "Edge", "Application", "msedge.exe")
        if c.exists(): return str(c)
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


TOAST_STATE = """(() => {
  const host = document.getElementById('toastHost');
  const all = [...host.querySelectorAll('.toast')];
  return { all: all.length,
           alive: all.filter(t => !t.dataset.out).length,
           outCls: all.filter(t => t.classList.contains('out')).length,
           texts: all.map(t => t.textContent) };
})()"""


def main():
    EDGE = find_edge()
    if not EDGE:
        print("FAIL 找不到 Edge"); return 2
    port = free_port()
    profile = tempfile.mkdtemp(prefix="edge_toast_")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--allow-file-access-from-files",
         "--window-size=1600,1000", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", PAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results = []
    def check(name, ok, detail):
        results.append((name, ok))
        print(("PASS" if ok else "FAIL"), name, "｜", detail)

    try:
        ws = connect(port)
        def ev(js):
            r = ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True,
                                             "awaitPromise": True}, timeout=30)
            if r.get("exceptionDetails"):
                raise RuntimeError("页面求值异常: " + json.dumps(r["exceptionDetails"])[:300])
            return r.get("result", {}).get("value")

        for _ in range(100):
            try:
                if ev("!!document.querySelector('.rsh--ai')"): break
            except Exception: pass
            time.sleep(0.3)

        # ---------- T1 超额挤旧 = 淡出而非硬删 ----------
        ev("toast('第一条'); toast('第二条'); toast('第三条')")
        s1 = ev(TOAST_STATE)          # 同帧：被挤者应已带 .out 且仍在 DOM（淡出中）
        time.sleep(0.4)
        s2 = ev(TOAST_STATE)          # 淡出完成后：被挤者移除，剩 2 条存活
        ok = (s1["alive"] == 2 and s1["outCls"] == 1 and s1["all"] == 3
              and s2["all"] == 2 and s2["alive"] == 2 and s2["outCls"] == 0
              and "第一条" in "".join(s1["texts"]))
        check("T1 超额挤旧走淡出、存活恒为 2", ok,
              f"同帧 all={s1['all']} alive={s1['alive']} out={s1['outCls']}；0.4s后 all={s2['all']} out={s2['outCls']}")

        # ---------- T2 点击关闭 ----------
        ev("toast('点我关闭')")
        s3 = ev(TOAST_STATE)
        ev("[...document.querySelectorAll('#toastHost .toast')].pop().click()")
        s4 = ev(TOAST_STATE)
        time.sleep(0.35)
        s5 = ev(TOAST_STATE)
        ok = (s3["alive"] >= 1 and s4["outCls"] >= 1 and s5["texts"].count("点我关闭") == 0)
        check("T2 点击弹窗可关闭（带淡出）", ok,
              f"点击前 alive={s3['alive']}；点击后 out={s4['outCls']}；0.35s后节点移除={s5['texts'].count('点我关闭') == 0}")

        # ---------- T3 自动消失 ----------
        ev("toast('两秒后自灭')")
        time.sleep(2.8)
        s6 = ev(TOAST_STATE)
        check("T3 2.2s 后自动淡出并移除", s6["texts"].count("两秒后自灭") == 0,
              f"2.8s 后残留={s6['texts'].count('两秒后自灭')}")

        # ---------- T4 计时器独立（回归"弹窗滞留"核心 bug） ----------
        ev("toast('甲-先弹')")
        time.sleep(1.5)
        ev("toast('乙-后弹')")           # 旧实现：这句的 clearTimeout 让甲永不退场
        time.sleep(1.3)                  # 甲年龄 2.8s > 2.2s，必须已退场；乙年龄 1.3s 应存活
        s7 = ev(TOAST_STATE)
        aGone = "甲-先弹" not in "".join(s7["texts"])
        bAlive = any("乙-后弹" in t and True for t in s7["texts"]) or s7["alive"] >= 1
        check("T4 每条计时器独立（先弹者到点自灭，不被后弹者顺延）",
              aGone and bAlive, f"甲已退场={aGone}；此刻文本={s7['texts']}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for ok in results.values() if ok) if isinstance(results, dict) else sum(1 for _, ok in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
