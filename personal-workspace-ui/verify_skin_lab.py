#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Lab 端到端点击验收（default-skin.md §五 / §六 V8）。
验的是「--mt-skin-* 预览通道」在真实浏览器里的行为：
  1) 三档 computed --mt-intensity 分别为 1 / 0.55 / 1.35；
  2) Default 档 = 零覆盖（沙箱 style 为空）；
  3) 切档是局部更新 —— 沙箱外的节点不被重建（节点身份判据，对照组见 T1）。
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
        if not b:
            continue
        for rel in (("Microsoft", "Edge", "Application", "msedge.exe"),
                    ("Microsoft", "Edge Beta", "Application", "msedge.exe")):
            c = Path(b).joinpath(*rel)
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
            c = self.s.recv(65536)
            if not c:
                raise RuntimeError("socket closed")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self):
        b0, b1 = self._need(2)
        op = b0 & 0x0F
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._need(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._need(8))[0]
        if b1 & 0x80:
            mask = self._need(4)
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._need(ln)))
        else:
            data = self._need(ln)
        return op, data

    def send(self, text, op=0x1):
        data = text.encode()
        h = bytearray([0x80 | op]); n = len(data)
        if n < 126:
            h.append(0x80 | n)
        elif n < 65536:
            h.append(0x80 | 126); h += struct.pack(">H", n)
        else:
            h.append(0x80 | 127); h += struct.pack(">Q", n)
        mask = os.urandom(4); h += mask
        self.s.sendall(bytes(h) + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def call(self, method, params=None, timeout=90):
        self._id += 1
        mid = self._id
        self.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        self.s.settimeout(timeout)
        while True:
            op, data = self._frame()
            if op == 0x9:
                self.send(data.decode("utf-8", "replace"), op=0xA); continue
            if op == 0x8:
                raise RuntimeError("closed by peer")
            if op not in (0x1, 0x2):
                continue
            msg = json.loads(data.decode("utf-8", "replace"))
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise RuntimeError(json.dumps(msg["error"])[:400])
            return msg.get("result", {})


def connect(port, tries=60):
    for _ in range(tries):
        try:
            raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2).read()
            for tg in json.loads(raw):
                if tg.get("type") == "page" and tg.get("webSocketDebuggerUrl"):
                    u = urlparse(tg["webSocketDebuggerUrl"])
                    s = socket.create_connection((u.hostname, u.port), timeout=20)
                    key = base64.b64encode(os.urandom(16)).decode()
                    s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
                    buf = b""
                    while b"\r\n\r\n" not in buf:
                        buf += s.recv(4096)
                    head, rest = buf.split(b"\r\n\r\n", 1)
                    if b"101" not in head.split(b"\r\n")[0]:
                        raise RuntimeError("handshake failed")
                    return WS(s, rest)
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError("cannot attach CDP")


def ev(ws, expr, timeout=90):
    last = None
    for attempt in range(6):
        try:
            r = ws.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                                             "returnByValue": True}, timeout=timeout)
            if "exceptionDetails" in r:
                raise RuntimeError("JS 异常: " + json.dumps(r["exceptionDetails"], ensure_ascii=False)[:400])
            return r.get("result", {}).get("value")
        except RuntimeError as e:
            last = e
            if "Execution context was destroyed" in str(e) and attempt < 5:
                time.sleep(0.6 * (attempt + 1)); continue
            raise
    raise last


def main():
    EDGE = find_edge()
    if not EDGE:
        print("FAIL 找不到 Edge"); return 2
    port = free_port()
    profile = tempfile.mkdtemp(prefix="edge_skinlab_")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--window-size=1600,1000", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", PAGE + "#/skinlab"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results = []
    try:
        ws = connect(port)
        ws.call("Runtime.enable")
        for _ in range(40):
            if ev(ws, "!!document.getElementById('skinSandbox')"):
                break
            time.sleep(0.25)

        # 通道桥接是 CSS 静态规则，这里直接断言它真的写进了样式表（防止"脚本绿但桥接没写"）
        step_name = "T0 通道桥接真实存在于样式表"
        facts = ev(ws, """
        (async () => {
          let found = false;
          for (const sh of document.styleSheets) {
            let rules; try { rules = sh.cssRules; } catch (e) { continue; }
            for (const r of rules) {
              if (r.selectorText && r.selectorText.includes('.skin-sandbox') && r.style) {
                const t = r.style.getPropertyValue('--mt-intensity');
                if (t && t.includes('--mt-skin-intensity')) found = true;
              }
            }
          }
          return { found };
        })()
        """)
        results.append((bool(facts and facts.get("found")), step_name,
                        json.dumps(facts, ensure_ascii=False)))

        def click_tier(v):
            return f"""
            (async () => {{
              const waitUntil = async (fn, ms=2500) => {{
                const t0 = Date.now();
                while(Date.now()-t0 < ms){{ try{{ if(fn()) return true; }}catch(e){{}} await new Promise(r=>setTimeout(r,30)); }}
                return false;
              }};
              const box = document.getElementById('skinSandbox');
              const swatchCard = document.querySelector('.skinlab-swatches').closest('.card');
              const kid = swatchCard.firstElementChild;
              kid.setAttribute('data-probe','keep');
              const btn = document.querySelector('[data-act="skin-lab"] button[data-v="{v}"]');
              if(!btn) return {{ err:'找不到 ' + '{v}' + ' 按钮' }};
              btn.click();
              await waitUntil(() => {{
                const c = getComputedStyle(box).getPropertyValue('--mt-intensity').trim();
                const want = {{default:'1', calm:'0.55', lively:'1.35'}}['{v}'];
                return parseFloat(c) === parseFloat(want);
              }});
              const kid2 = swatchCard.firstElementChild;
              return {{
                intensity: getComputedStyle(box).getPropertyValue('--mt-intensity').trim(),
                stagger: getComputedStyle(box).getPropertyValue('--mt-stagger').trim(),
                boxStyleAttr: box.getAttribute('style') || '',
                sameBox: box === document.getElementById('skinSandbox'),
                outsideSurvived: kid2 === kid,
                onStates: [...document.querySelectorAll('[data-act="skin-lab"] button')]
                  .map(b => b.getAttribute('data-v') + ':' + b.classList.contains('on')),
                hint: (document.getElementById('skinLabHint')||{{}}).textContent || ''
              }};
            }})()
            """

        def check(v, want_i, want_s):
            def _c(f):
                # 精确判定：computed 幅度、沙箱节点身份、沙箱外节点存活、on 态分布
                ok = (not f.get("err")
                      and abs(float(f["intensity"]) - want_i) < 1e-9
                      and f["sameBox"] is True
                      and f["outsideSurvived"] is True
                      and f["onStates"] == [f"default:{'true' if v == 'default' else 'false'}",
                                            f"calm:{'true' if v == 'calm' else 'false'}",
                                            f"lively:{'true' if v == 'lively' else 'false'}"])
                if v == "default":
                    ok = ok and f["boxStyleAttr"] == ""          # 零覆盖 = 无 inline style
                else:
                    ok = ok and ("--mt-skin-intensity" in f["boxStyleAttr"])
                return ok, ("intensity=%s stagger=%s boxStyle=%r sameBox=%s outsideSurvived=%s"
                            % (f.get("intensity"), f.get("stagger"),
                               (f.get("boxStyleAttr") or "")[:60],
                               f.get("sameBox"), f.get("outsideSurvived")))
            return _c

        for v, wi, ws_, label in (("default", 1, "24ms", "T1 Default｜零覆盖"),
                                  ("calm", 0.55, "12ms", "T2 Calm｜幅度减半"),
                                  ("lively", 1.35, "32ms", "T3 Lively｜幅度拉满"),
                                  ("default", 1, "24ms", "T4 回到 Default｜通道清空")):
            facts = ev(ws, click_tier(v))
            if isinstance(facts, dict) and facts.get("err"):
                results.append((False, label, "探针报错: " + str(facts["err"])))
                continue
            ok, note = check(v, wi, ws_)(facts)
            results.append((ok, label, note + " | " + json.dumps(facts, ensure_ascii=False)[:300]))
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    npass = sum(1 for r in results if r[0])
    print("=" * 78)
    for ok, name, note in results:
        print(("PASS " if ok else "FAIL ") + name)
        print("      " + note)
    print("=" * 78)
    print("TOTAL %d passed, %d failed" % (npass, len(results) - npass))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
