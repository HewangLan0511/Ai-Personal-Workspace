#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Personal Workspace · 生活中心能力（阶段8，11 §A）
=================================================

- A1 天气：Open-Meteo（免费、无需 Key；用户可换 API base）。**定位由用户手动
  传城市名，绝不读系统定位**（11 §禁止事项）。内存缓存 30 分钟。
- A2 音乐：Windows SMTC（`winsdk`）读系统当前媒体会话 —— **可选依赖**：
  未安装 winsdk 时 `available=false` 优雅降级（同 `win.apps_probe` 的模式）。
  不保存播放历史（数据轻量化）。
- A3 社交概览：只返回**未读数**与来源摘要。内置两类 provider：
  - `imap`：IMAP `STATUS (UNSEEN)`，只取计数、不下载正文（不存聊天内容红线）；
  - `demo`：固定未读数（验收与演示用，明确标注）。
  密码经 core 的 keyring 凭据库存取，**不进配置 JSON / 不进数据库**（红线 V1）。

全部仅标准库（winsdk 除外，且为可选）。
"""

from __future__ import annotations

import imaplib
import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from typing import Any

# ---- A2：winsdk（SMTC）可选导入 -------------------------------------------

try:
    from winsdk.windows.media.control import (  # type: ignore[import-not-found]
        GlobalSystemMediaTransportControlsSessionManager as _SmtcMgr,
    )

    _WINSDK_ERROR = ""
except Exception as _exc:  # pragma: no cover - 未安装 winsdk / 非 Windows
    _SmtcMgr = None  # type: ignore[assignment]
    _WINSDK_ERROR = str(_exc)


# ---------------------------------------------------------------------------
# A1 天气

_WEATHER_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_WEATHER_TTL = 30 * 60  # 11 §A1：缓存 30 分钟

# 天气代码 → 中文短语（Open-Meteo WMO codes 的常用子集）
_WMO = {
    0: "晴", 1: "基本晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛雨", 53: "毛雨", 55: "大毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
}


def _http_get_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "PersonalWorkspace/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fake_weather(city: str) -> dict[str, Any]:
    """验收/离线演示用固定数据（PW_WEATHER_FAKE=1 启用；来源必须显式标注）。"""
    return {
        "city": city,
        "source": "fake（PW_WEATHER_FAKE=1，非真实 API）",
        "current": {"temperature": 23.5, "weather": "多云"},
        "daily": [
            {"date": "2026-09-13", "weather": "多云", "max": 28.0, "min": 19.0},
            {"date": "2026-09-14", "weather": "晴", "max": 29.0, "min": 20.0},
            {"date": "2026-09-15", "weather": "小雨", "max": 25.0, "min": 18.0},
        ],
    }


def weather(city: str, api_base: str = "") -> dict[str, Any]:
    city = (city or "").strip()
    if not city:
        raise ValueError("需要 city（用户手动设置，不自动定位）")

    if os.environ.get("PW_WEATHER_FAKE") == "1":
        return _fake_weather(city)

    cache_key = city.lower()
    now = time.time()
    hit = _WEATHER_CACHE.get(cache_key)
    if hit and now - hit[0] < _WEATHER_TTL:
        return hit[1]

    base = (api_base or "https://api.open-meteo.com/v1").rstrip("/")
    # 地理编码（Open-Meteo 免费地理编码，固定域名，见下）
    geo_url = (
        "https://geocoding-api.open-meteo.com/v1/search?name="
        + urllib.parse.quote(city)
        + "&count=1&language=zh"
    )
    geo = _http_get_json(geo_url)
    results = geo.get("results") or []
    if not results:
        raise ValueError(f"找不到城市：{city}")
    lat, lon = results[0]["latitude"], results[0]["longitude"]
    resolved = results[0].get("name", city)

    url = (
        f"{base}/forecast?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min"
        "&timezone=auto&forecast_days=4"
    )
    raw = _http_get_json(url)

    def wmo(code: Any) -> str:
        return _WMO.get(int(code), f"代码{code}")

    daily = raw.get("daily") or {}
    dates = daily.get("time") or []
    out = {
        "city": resolved,
        "source": "open-meteo",
        "current": {
            "temperature": (raw.get("current") or {}).get("temperature_2m"),
            "weather": wmo((raw.get("current") or {}).get("weather_code", -1)),
        },
        "daily": [
            {
                "date": d,
                "weather": wmo((daily.get("weather_code") or [-1])[i]),
                "max": (daily.get("temperature_2m_max") or [None])[i],
                "min": (daily.get("temperature_2m_min") or [None])[i],
            }
            for i, d in enumerate(dates[:4])
        ],
    }
    # 未来 3 天（第一项是今天）
    out["daily"] = out["daily"][:4]
    _WEATHER_CACHE[cache_key] = (now, out)
    return out


# ---------------------------------------------------------------------------
# A2 音乐（SMTC）


def media_available() -> dict[str, Any]:
    return {"available": _SmtcMgr is not None, "error": _WINSDK_ERROR or None}


def media_now() -> dict[str, Any]:
    if _SmtcMgr is None:
        return {
            "available": False,
            "reason": "winsdk 未安装（SMTC 媒体会话不可用）",
            "session": None,
        }
    manager = _SmtcMgr.request_async().get()
    sessions = manager.get_sessions()
    if sessions.size == 0:
        return {"available": True, "session": None}
    session = sessions.get(0)
    info = session.get_saved_media_info()
    props = session.get_playback_info()
    tl = session.get_timeline_properties()
    return {
        "available": True,
        "session": {
            "title": info.title or "",
            "artist": info.artist or "",
            "album": getattr(info, "album_title", "") or "",
            "status": str(props.playback_status).split(".")[-1],  # PLAYING / PAUSED ...
            "position_seconds": int(tl.position.total_seconds()) if tl.position else 0,
            "duration_seconds": int(tl.end_time.total_seconds()) if tl.end_time else 0,
        },
    }


def media_control(action: str) -> dict[str, Any]:
    # 先校验 action（无论 winsdk 是否可用，非法输入都必须被拒——不能因降级而放过）
    actions = {
        "play": lambda s: s.try_play_async(),
        "pause": lambda s: s.try_pause_async(),
        "next": lambda s: s.try_skip_next_async(),
        "previous": lambda s: s.try_skip_previous_async(),
    }
    fn = actions.get((action or "").lower())
    if fn is None:
        raise ValueError(f"未知 action：{action}（play/pause/next/previous）")
    if _SmtcMgr is None:
        return {"available": False, "acted": False}
    manager = _SmtcMgr.request_async().get()
    sessions = manager.get_sessions()
    if sessions.size == 0:
        return {"available": True, "acted": False, "reason": "无媒体会话"}
    fn(sessions.get(0)).get()
    return {"available": True, "acted": True}


# ---------------------------------------------------------------------------
# A3 社交概览（只取未读数，绝不读正文）


def social_overview(services: list[dict[str, Any]]) -> dict[str, Any]:
    """逐服务取未读数。单服务失败不影响其它服务（02 §2.7）。"""
    items: list[dict[str, Any]] = []
    for svc in services or []:
        name = str(svc.get("name") or "").strip()
        stype = str(svc.get("type") or "").strip().lower()
        if not name:
            continue
        entry: dict[str, Any] = {"name": name, "type": stype, "ok": False}
        try:
            if stype == "imap":
                entry["unread"] = _imap_unread(svc)
                entry["summary"] = f"{svc.get('user', '')}@{svc.get('host', '')} 未读邮件"
                entry["ok"] = True
            elif stype == "demo":
                entry["unread"] = int(svc.get("demoUnread", 3))
                entry["summary"] = "演示数据源（非真实服务）"
                entry["ok"] = True
            else:
                entry["summary"] = f"未知服务类型：{stype}"
        except Exception as exc:  # noqa: BLE001
            entry["summary"] = f"获取失败：{exc}"
        items.append(entry)
    return {"items": items, "note": "仅未读计数与来源摘要；不存任何消息内容"}


def _imap_unread(svc: dict[str, Any]) -> int:
    """IMAP STATUS (UNSEEN)：只取计数。不 LIST、不 FETCH、不下载任何正文。"""
    host = str(svc.get("host") or "")
    port = int(svc.get("port") or 993)
    user = str(svc.get("user") or "")
    password = str(svc.get("password") or "")
    if not (host and user and password):
        raise ValueError("imap 服务需要 host/user/password（password 走凭据库，不落库）")
    ctx = ssl.create_default_context()
    conn: imaplib.IMAP4
    if svc.get("tls", True):
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    else:
        conn = imaplib.IMAP4(host, port)
    try:
        conn.login(user, password)
        typ, data = conn.status("INBOX", "(UNSEEN)")
        if typ != "OK":
            raise RuntimeError(f"STATUS 失败：{typ}")
        # 形如 b'INBOX (UNSEEN 3)'
        parsed = str(data[0] if data else "")
        idx = parsed.upper().find("UNSEEN")
        if idx < 0:
            return 0
        tail = parsed[idx + len("UNSEEN"):].strip().lstrip(" ")
        digits = "".join(ch for ch in tail if ch.isdigit())
        return int(digits) if digits else 0
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


# 供 service.py 的社交凭据存取（复用 ai.credentials 的系统凭据库，不进数据库）


def social_credential_ref(name: str) -> str:
    return f"social.imap.{name}"


def set_social_password(name: str, password: str) -> None:
    from ai.credentials import store  # 延迟导入，避免无凭据库环境炸

    store().set(social_credential_ref(name), password)


def resolve_password(svc: dict[str, Any]) -> str:
    """按服务配置解析密码：只认 credRef（keyring），**绝不**读配置里的明文（红线 V1）。"""
    ref = str(svc.get("credRef") or "")
    if not ref:
        return ""
    from ai.credentials import store

    cred = store().get(ref)
    return cred.password if cred else ""


def inject_passwords(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 keyring 中的密码注入服务**内存副本**（永不落库/落日志）。"""
    out = []
    for svc in services or []:
        s = dict(svc)
        if s.get("type") == "imap" and not s.get("password"):
            s["password"] = resolve_password(s)
        out.append(s)
    return out
