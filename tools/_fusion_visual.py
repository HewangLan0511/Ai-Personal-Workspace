"""UI-FUSION-REAL 视觉验收：Edge 无头截图（正式 dist 各页 vs 原型 index.html）。"""
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace")
DIST = ROOT / "ui" / "dist"
OUT = ROOT / "tools" / "_fusion_shots"
OUT.mkdir(exist_ok=True)

EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

# dist 里没有 HTTP 服务时 SPA 深链会 404，用 file:// + hash 路由不可行（history 模式）。
# 因此走 vite preview（dist 静态服务，--strictPort）。
PREVIEW_PORT = 4781


def find_edge() -> str:
    for p in EDGE_CANDIDATES:
        if p.exists():
            return str(p)
    raise SystemExit("未找到 Edge")


def shot(edge: str, url: str, name: str, profile: Path, wait_ms: int = 3200) -> None:
    subprocess.run(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--user-data-dir={profile}",
         f"--screenshot={OUT / name}.png", f"--virtual-time-budget={wait_ms}",
         "--window-size=1440,900", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    print(f"shot {name}")


if __name__ == "__main__":
    import http.server
    import functools

    class SPAHandler(http.server.SimpleHTTPRequestHandler):
        """dist 静态服务 + SPA 深链回退（history 路由必须，否则 /dashboard 404）。"""

        def send_head(self):
            path = self.translate_path(self.path)
            p = Path(path)
            if not p.exists() or p.is_dir():
                # 深链回退到 index.html（静态资源命中时走原逻辑）
                if "." not in p.name:
                    self.path = "/index.html"
            return super().send_head()

        def log_message(self, *a):  # 静音访问日志
            pass

    edge = find_edge()
    handler = functools.partial(SPAHandler, directory=str(DIST))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PREVIEW_PORT), handler)
    import threading
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    profile = Path(tempfile.mkdtemp(prefix="pw-fusion-shot-"))
    base = f"http://127.0.0.1:{PREVIEW_PORT}"
    pages = ["dashboard", "mode", "software", "learning", "project",
             "life", "ai", "profile", "device", "plugins", "settings", "models", "run"]
    try:
        for p in pages:
            shot(edge, f"{base}/{p}", p, profile)
        # 原型对照（file:// 直开）
        proto = (ROOT / "personal-workspace-ui" / "index.html").as_uri()
        for route in ["home", "workspaces", "apps", "settings"]:
            shot(edge, f"{proto}#/{route}", f"proto-{route}", profile)
    finally:
        srv.shutdown()
    print("done ->", OUT)
