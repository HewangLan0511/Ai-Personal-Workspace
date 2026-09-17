#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-08 个人档案页编辑体验增强（Edge 无头 + CDP）。

用例判据：
  T1 编辑入口：编辑资料 → 原位展开编辑卡（昵称聚焦全选 / 签名 textarea / 标签编辑 / 头像行），
     页面主体节点身份不变。
  T2 签名：多行输入 + 长度计数联动 + 保存后头部签名行即时更新（局部 diff）。
  T3 标签：删除 / 手输 Enter 添加 / 推荐一键添加 → 保存后兴趣方向 chips 同步。
  T4 标签取消：增删后取消 → 兴趣方向还原，无新 toast。
  T5 头像：点头像开 picker（首字母 + 8 预设 + 上传入口）→ 选 🚀 即时预览 → 保存生效；
     重开选 💻 后取消 → 还原 🚀。
  T6 上传入口：点上传 → 演示 toast（仅 UI）。
  T7 空值与异常：昵称空 → 阻止保存；签名清空保存 → 头部恢复默认态；
     标签空/重复 → toast 反馈。
  T8 主体节点身份：编辑全程 AI 建议卡、扩展块容器、经历卡节点身份不变。
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
    profile = tempfile.mkdtemp(prefix="edge_s8_")
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

        # ---------- 进入档案页，登记主体节点 ----------
        ev("location.hash = '#/profile'")
        time.sleep(0.8)
        ev("""(() => {
          window.__head = document.getElementById('profileHead');
          window.__btn  = document.querySelector('.page-head [data-act="profile-edit"]');
          window.__av   = document.getElementById('profileAvatar');
          /* 主体节点：AI 建议卡（brand-50 虚线卡）与扩展块容器 */
          window.__ai   = document.querySelector('.card.card--dashed');
          window.__ext  = document.getElementById('profileExts');
          const g2 = document.querySelectorAll('.grid.g2 .card.card--lg');
          window.__g2a  = g2[0]; window.__g2b = g2[1];
        })()""")

        # ---------- T1 编辑入口 ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.4)
        s1 = ev("""(() => { const ed = document.getElementById('profileEditor');
          const inp = document.getElementById('nicknameInput');
          return {card: !!(ed && ed.querySelector('.card')),
            inp: !!inp, val: inp ? inp.value : '', focused: document.activeElement === inp,
            sel: inp ? (inp.selectionEnd - inp.selectionStart) === inp.value.length : false,
            sig: !!document.getElementById('signatureInput'), cnt: (document.getElementById('sigCount')||{textContent:''}).textContent,
            tagChips: ed.querySelectorAll('#tagEditor .chip--brand').length,
            sug: ed.querySelectorAll('#tagEditor [data-act=\"profile-tag-sug\"]').length,
            avp: !!ed.querySelector('[data-act=\"avatar-picker\"]'),
            save: !!ed.querySelector('[data-act=\"profile-save\"]'),
            headSame: document.getElementById('profileHead') === window.__head,
            aiSame: document.querySelector('.card.card--dashed') === window.__ai};
        })()""")
        ok = (s1["card"] and s1["inp"] and s1["val"] == "白宇" and s1["focused"] and s1["sel"]
              and s1["sig"] and s1["cnt"] == "0/60" and s1["tagChips"] == 5 and s1["sug"] > 0
              and s1["avp"] and s1["save"] and s1["headSame"] and s1["aiSame"])
        check("T1 编辑入口：原位展开编辑卡（昵称聚焦/签名/标签5+推荐/头像行），主体节点身份不变", ok,
              json.dumps(s1, ensure_ascii=False)[:220])

        # ---------- T2 签名（多行 + 计数 + 局部保存） ----------
        ev("""(() => { const si = document.getElementById('signatureInput');
          si.value = '专注 RGB-T 感知';
          si.dispatchEvent(new Event('input', {bubbles:true})); })()""")
        time.sleep(0.1)
        cnt = ev("(document.getElementById('sigCount')||{textContent:''}).textContent")
        ev("document.querySelector('#profileEditor [data-act=\"profile-save\"]').click()")
        time.sleep(0.5)
        s2 = ev("""(() => ({
          sig: (document.querySelector('#profileHead [data-field=\"signature\"]')||{textContent:''}).textContent,
          editorGone: !(document.getElementById('profileEditor')||{firstChild:null}).firstChild,
          headSame: document.getElementById('profileHead') === window.__head,
          extSame: document.getElementById('profileExts') === window.__ext,
          toast: (document.getElementById('toastHost')||{textContent:''}).textContent
        }))()""")
        ok = (cnt == "11/60" and s2["sig"] == "专注 RGB-T 感知" and s2["editorGone"]
              and s2["headSame"] and s2["extSame"] and "个人资料已更新" in s2["toast"])
        check("T2 签名：多行输入 + 计数联动(11/60) + 保存后头部签名行即时更新（局部 diff）", ok,
              f"cnt={cnt} sig={s2['sig'][:20]} editorGone={s2['editorGone']}")

        # ---------- T3 标签（删除 / Enter 添加 / 推荐添加） ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.4)
        ev("document.querySelector('#tagEditor [data-act=\"profile-tag-del\"]').click()")
        time.sleep(0.2)
        n_del = ev("document.querySelectorAll('#tagEditor .chip--brand').length")
        ev("document.getElementById('tagInput').value = '开源'")
        ev("document.getElementById('tagInput').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}))")
        time.sleep(0.2)
        n_add = ev("document.querySelectorAll('#tagEditor .chip--brand').length")
        ev("document.querySelector('#tagEditor [data-act=\"profile-tag-sug\"]').click()")
        time.sleep(0.2)
        n_sug = ev("document.querySelectorAll('#tagEditor .chip--brand').length")
        ev("document.querySelector('#profileEditor [data-act=\"profile-save\"]').click()")
        time.sleep(0.5)
        s3 = ev("""(() => ({
          tags: document.getElementById('profileTags').textContent,
          editorGone: !(document.getElementById('profileEditor')||{firstChild:null}).firstChild
        }))()""")
        ok = (n_del == 4 and n_add == 5 and n_sug == 6
              and "开源" in s3["tags"] and "深度学习" in s3["tags"] and "计算机视觉" not in s3["tags"]
              and s3["editorGone"])
        check("T3 标签：删除(5→4) → Enter 添加开源(5) → 推荐一键添加(6) → 保存后 chips 同步", ok,
              f"del={n_del} add={n_add} sug={n_sug} tags={s3['tags'][:60]}")

        # ---------- T4 标签取消 ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.4)
        ev("window.__tc = document.getElementById('toastHost').children.length")
        ev("document.querySelector('#tagEditor [data-act=\"profile-tag-del\"]').click()")
        time.sleep(0.2)
        ev("document.querySelector('#profileEditor [data-act=\"profile-cancel\"]').click()")
        time.sleep(0.4)
        s4 = ev("""(() => ({
          n: document.querySelectorAll('#profileTags .chip').length,
          editorGone: !(document.getElementById('profileEditor')||{firstChild:null}).firstChild,
          noNewToast: document.getElementById('toastHost').children.length <= window.__tc
        }))()""")
        ok = (s4["n"] == 6 and s4["editorGone"] and s4["noNewToast"])
        check("T4 标签取消：删除后取消 → 兴趣方向还原（6 个），无新 toast", ok,
              f"n={s4['n']} noNewToast={s4['noNewToast']}")

        # ---------- T5 头像（picker 预览 / 保存 / 取消还原） ----------
        ev("document.getElementById('profileAvatar').click()")
        time.sleep(0.4)
        s5a = ev("""(() => ({picks: document.querySelectorAll('.drawer .avatar-pick').length,
                             hasUp: !!document.querySelector('.drawer [data-act=\"avatar-upload\"]')}))()""")
        ev("document.querySelector('.drawer [data-act=\"avatar-set\"][data-v=\"🚀\"]').click()")
        time.sleep(0.2)
        s5b = ev("""(() => ({av: (document.getElementById('profileAvatar')||{textContent:''}).textContent,
                             on: !!document.querySelector('.drawer .avatar-pick.on[data-v=\"🚀\"]')}))()""")
        ev("document.querySelector('.drawer [data-act=\"avatar-save\"]').click()")
        time.sleep(0.4)
        s5c = ev("""(() => ({av: (document.getElementById('profileAvatar')||{textContent:''}).textContent,
                             toast: (document.getElementById('toastHost')||{textContent:''}).textContent,
                             drawerGone: !document.querySelector('.drawer')}))()""")
        # 取消还原：重开选 💻 再取消
        ev("document.getElementById('profileAvatar').click()")
        time.sleep(0.4)
        ev("document.querySelector('.drawer [data-act=\"avatar-set\"][data-v=\"💻\"]').click()")
        time.sleep(0.2)
        ev("document.querySelector('.drawer [data-act=\"avatar-cancel\"]').click()")
        time.sleep(0.4)
        s5d = ev("(document.getElementById('profileAvatar')||{textContent:''}).textContent")
        ok = (s5a["picks"] == 10 and s5a["hasUp"] and s5b["av"] == "🚀" and s5b["on"]
              and s5c["av"] == "🚀" and s5c["drawerGone"] and "头像已更新" in s5c["toast"]
              and s5d == "🚀")
        check("T5 头像：picker 10 格（首字母+8预设+上传）→ 选 🚀 即时预览 → 保存生效；取消还原", ok,
              f"picks={s5a['picks']} save={s5c['av']} afterCancel={s5d}")

        # ---------- T6 上传入口（仅 UI） ----------
        ev("document.getElementById('profileAvatar').click()")
        time.sleep(0.4)
        ev("document.querySelector('.drawer [data-act=\"avatar-upload\"]').click()")
        time.sleep(0.3)
        s6 = ev("(document.getElementById('toastHost')||{textContent:''}).textContent")
        ev("document.querySelector('.drawer [data-act=\"avatar-cancel\"]').click()")
        time.sleep(0.3)
        ok = "上传" in s6 and "开放" in s6
        check("T6 上传入口：点击 → 演示反馈（不实现真实上传）", ok, s6[:60])

        # ---------- T7 空值与异常输入 ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.4)
        ev("document.getElementById('nicknameInput').value = ''")
        ev("document.querySelector('#profileEditor [data-act=\"profile-save\"]').click()")
        time.sleep(0.3)
        s7a = ev("""(() => ({toast: (document.getElementById('toastHost')||{textContent:''}).textContent,
                             stillEditing: !!document.getElementById('nicknameInput')}))()""")
        ev("document.getElementById('nicknameInput').value = '白宇'")
        ev("document.querySelector('#profileEditor [data-act=\"profile-tag-add\"]').click()")
        time.sleep(0.3)
        s7b = ev("(document.getElementById('toastHost')||{textContent:''}).textContent")
        # 重复标签：开源在 T3 已加入 → toast「已存在」，chips 数不变
        ev("document.getElementById('tagInput').value = '开源'")
        ev("document.getElementById('tagInput').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}))")
        time.sleep(0.3)
        s7c = ev("""(() => ({toast: (document.getElementById('toastHost')||{textContent:''}).textContent,
                             chips: document.querySelectorAll('#tagEditor .chip--brand').length}))()""")
        # 正常添加（静默成功，chips 即时更新）
        ev("document.getElementById('tagInput').value = 'Rust'")
        ev("document.getElementById('tagInput').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}))")
        time.sleep(0.3)
        s7d = ev("document.querySelectorAll('#tagEditor .chip--brand').length")
        ev("document.querySelector('#profileEditor [data-act=\"profile-cancel\"]').click()")
        time.sleep(0.3)
        ok = ("昵称不能为空" in s7a["toast"] and s7a["stillEditing"]
              and "标签不能为空" in s7b and "已存在" in s7c["toast"] and s7c["chips"] == 6
              and s7d == 7)
        check("T7 空值与异常：昵称空阻止保存 / 空标签与重复标签 toast 反馈 / 正常添加静默生效", ok,
              f"a={s7a['toast'][-8:]} b={s7b[-8:]} c={s7c['toast'][-12:]} chips={s7c['chips']}→{s7d}")

        # ---------- T7b 签名清空 = 默认态 ----------
        ev("document.querySelector('.page-head [data-act=\"profile-edit\"]').click()")
        time.sleep(0.4)
        ev("document.getElementById('signatureInput').value = ''")
        ev("document.querySelector('#profileEditor [data-act=\"profile-save\"]').click()")
        time.sleep(0.4)
        s7d = ev("(document.querySelector('#profileHead [data-field=\"signature\"]')||{textContent:''}).textContent")
        ok = s7d == "还没有个性签名"
        check("T7b 签名清空保存 → 头部恢复默认状态文案", ok, f"sig={s7d}")

        # ---------- T8 主体节点身份 ----------
        s8 = ev("""(() => { const g2 = document.querySelectorAll('.grid.g2 .card.card--lg');
          return {head: document.getElementById('profileHead') === window.__head,
                  btn:  document.querySelector('.page-head [data-act=\"profile-edit\"]') === window.__btn,
                  ai:   document.querySelector('.card.card--dashed') === window.__ai,
                  ext:  document.getElementById('profileExts') === window.__ext,
                  g2a:  g2[0] === window.__g2a, g2b: g2[1] === window.__g2b}; })()""")
        ok = all(s8.values())
        check("T8 主体节点身份：头部/编辑按钮/AI 建议卡/扩展块/两张经历卡全程身份不变", ok, json.dumps(s8))
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
