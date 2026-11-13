"""DouyinBarrage 桌面 UI：房间、录制、弹幕、礼物。"""
from __future__ import annotations

import os
import queue
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

# 保证能 import DouyinBarrage 根目录
ROOT = Path(__file__).resolve().parent.parent
if getattr(sys, "frozen", False):
    # 打包后：代码在 _MEIPASS，可写目录在 exe 旁
    MEIPASS = Path(getattr(sys, "_MEIPASS", ROOT))
    APP = Path(sys.executable).resolve().parent
    ROOT = MEIPASS
    WORK = APP
else:
    MEIPASS = ROOT
    APP = ROOT
    WORK = ROOT

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Barrage 需要可写 cwd（cookie.txt / config）
try:
    os.chdir(WORK)
except Exception:
    pass

import flet as ft  # noqa: E402

for rel in (
    "tools/node/node-v20.18.0-win-x64",
    "tools/ffmpeg/bin",
):
    for base in (MEIPASS, APP, ROOT):
        d = base / rel
        if d.is_dir():
            os.environ["PATH"] = f"{d};{os.environ.get('PATH', '')}"
            break



# ---------- UI 视觉规范（Apple 风格） ----------
C = {
    "bg": "#F5F5F7",
    "surface": "#FFFFFF",
    "surface_alt": "#F7F7F9",
    "soft": "#F2F2F7",
    "border": "#E5E5EA",
    "text": "#1D1D1F",
    "muted": "#6E6E73",
    "blue": "#007AFF",
    "blue_soft": "#EAF3FF",
    "green": "#34C759",
    "green_soft": "#EAF9EE",
    "orange": "#FF9F0A",
    "orange_soft": "#FFF4E5",
    "red": "#FF3B30",
    "red_soft": "#FFECEB",
    "purple": "#AF52DE",
    "purple_soft": "#F7EDFC",
}


def _txt(
    value: str,
    *,
    size: int = 14,
    color: str | None = None,
    weight: ft.FontWeight | None = None,
) -> ft.Text:
    return ft.Text(
        value,
        size=size,
        color=color or C["text"],
        weight=weight,
        font_family="Segoe UI",
    )


def _card(
    content: ft.Control,
    *,
    padding: int | ft.Padding = 16,
    radius: int = 18,
    bgcolor: str | None = None,
    border: bool = True,
    expand: bool = False,
    width: int | None = None,
    height: int | None = None,
) -> ft.Container:
    return ft.Container(
        content=content,
        expand=expand,
        width=width,
        height=height,
        padding=padding,
        border_radius=radius,
        bgcolor=bgcolor or C["surface"],
        border=ft.Border.all(1, C["border"]) if border else None,
    )


def _pill(value: str, *, fg: str, bg: str) -> ft.Container:
    return ft.Container(
        _txt(value, size=11, color=fg, weight=ft.FontWeight.W_600),
        bgcolor=bg,
        padding=ft.Padding.symmetric(vertical=4, horizontal=9),
        border_radius=999,
    )


def _icon_badge(
    icon: ft.IconData,
    *,
    fg: str,
    bg: str,
    size: int = 36,
    gradient: ft.Gradient | None = None,
) -> ft.Container:
    return ft.Container(
        ft.Icon(icon, color=fg, size=20),
        width=size,
        height=size,
        border_radius=11,
        bgcolor=None if gradient else bg,
        gradient=gradient,
        alignment=ft.Alignment.CENTER,
        animate=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
    )


def _button(
    label: str,
    *,
    icon: ft.IconData | None = None,
    fg: str = C["text"],
    bg: str = C["soft"],
    on_click=None,
) -> ft.Button:
    return ft.Button(
        label,
        icon=icon,
        color=fg,
        bgcolor=bg,
        elevation=0,
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        ),
    )


def _writable_root() -> Path:
    return WORK


def _ensure_cookie() -> None:
    """把 MEIPASS 里的 cookie.txt 拷到可写目录。"""
    src_cookie = MEIPASS / "cookie.txt"
    dst_cookie = WORK / "cookie.txt"
    try:
        if src_cookie.is_file() and (
            not dst_cookie.is_file() or dst_cookie.stat().st_size < 100
        ):
            dst_cookie.write_text(src_cookie.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except Exception:
        pass


def normalize_room(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    m = re.search(r"(?:live\.douyin\.com|www\.douyin\.com/root/live)/(\d+)", t)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{8,})", t)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{6,}", t):
        return t
    return t


class RoomRuntime:
    """一个房间的采集线程包装。"""

    def __init__(
        self,
        live_id: str,
        name: str,
        *,
        record: bool,
        quality: str,
        gift: bool = True,
        chat: bool = True,
    ) -> None:
        self.live_id = live_id
        self.name = name or live_id
        self.record = record
        self.quality = quality
        self.gift = gift
        self.chat = chat
        self.inst = None
        self.thread: Optional[threading.Thread] = None
        self.status = "准备中"
        self.running = False
        self.anchor = ""
        self.log_lines: list[str] = []

    def apply_runtime_flags(self) -> None:
        """把录制/礼物/弹幕开关同步到运行中的 Barrage 实例。"""
        inst = self.inst
        if not inst:
            return
        try:
            eo = getattr(inst, "_enable_outputs", None)
            if isinstance(eo, dict):
                eo["gift"] = self.gift
                eo["chat"] = self.chat
            cfg = getattr(inst, "config", None)
            if isinstance(cfg, dict) and isinstance(cfg.get("output"), dict):
                cfg["output"]["gift"] = self.gift
                cfg["output"]["chat"] = self.chat
            rec = getattr(inst, "_record_cfg", None)
            if isinstance(rec, dict):
                rec["enabled"] = self.record
            if not self.record and hasattr(inst, "_stop_recording"):
                try:
                    inst._stop_recording()
                except Exception:
                    pass
            if self.record and hasattr(inst, "_start_recording"):
                try:
                    # 仅在已开播且当前未在录时尝试开录
                    if getattr(inst, "anchor_name", None) and not getattr(
                        getattr(inst, "video_recorder", None), "is_recording", False
                    ):
                        inst._start_recording()
                except Exception:
                    pass
        except Exception:
            pass

    def log(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.log_lines.append(line)
        if len(self.log_lines) > 200:
            self.log_lines = self.log_lines[-200:]


class Studio:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.rooms: dict[str, RoomRuntime] = {}
        self.chat_q: deque = deque(maxlen=500)
        self.gift_q: deque = deque(maxlen=300)
        self.log_q: deque = deque(maxlen=400)
        self.events: queue.Queue = queue.Queue()
        self._patched = False

        page.title = "抖音直播助手 · 弹幕礼物"
        try:
            page.window.title = "抖音直播助手"
        except Exception:
            pass
        page.theme_mode = ft.ThemeMode.LIGHT
        try:
            page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)
        except Exception:
            pass
        page.bgcolor = C["bg"]
        try:
            page.window.width = 1320
            page.window.height = 900
            page.window.min_width = 1100
            page.window.min_height = 760
            page.window.center = True
            page.window.visible = True
        except Exception:
            page.width = 1320
            page.height = 900
        page.padding = 0
        page.spacing = 0

        self._build_top()
        self._build_settings()
        self._build_sidebar()
        self._build_panels()
        self.rooms_row = ft.Row(
            spacing=12,
            wrap=False,
            height=84,
            scroll=ft.ScrollMode.AUTO,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.rooms_row_wrap = ft.Container(
            self.rooms_row,
            height=84,
            bgcolor=C["bg"],
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._chat_n = 0
        self._gift_n = 0
        self._csv_offsets: dict[str, int] = {}

        self.main = ft.Column(
            [
                self.top,
                self.settings,
                ft.Row(
                    [
                        _txt("直播间", size=16, weight=ft.FontWeight.W_700),
                        _pill("实时状态", fg=C["blue"], bg=C["blue_soft"]),
                        _txt(
                            "添加直播间后，卡片会显示在这里",
                            size=11,
                            color=C["muted"],
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.rooms_row_wrap,
                self.panels,
            ],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=14,
        )
        self._root = ft.Container(
            content=ft.Row(
                [self.sidebar, self.main],
                spacing=16,
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            expand=True,
            bgcolor=C["bg"],
            padding=ft.Padding.symmetric(horizontal=18, vertical=16),
        )
        for ctl in (self.sidebar, self.top, self.settings, self.panels):
            ctl.opacity = 0
            ctl.animate_opacity = True
        self.page.add(self._root)

        async def _intro() -> None:
            import asyncio
            await asyncio.sleep(0.18)
            for ctl in (self.sidebar, self.top, self.settings, self.panels):
                ctl.opacity = 1
            try:
                self.page.update()
            except Exception:
                pass

        try:
            self.page.run_task(_intro)
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass
        self._refresh_env()
        _ensure_cookie()
        global _STUDIO
        _STUDIO = self
        threading.Thread(target=self._ui_loop, daemon=True).start()
        threading.Thread(target=self._csv_poll_loop, daemon=True).start()
        self._install_recorder_hook()
        self._install_log_handler()

    def _csv_poll_loop(self) -> None:
        """按文件偏移只读新增行，避免大文件重读和 seen 集合膨胀。"""
        while True:
            time.sleep(2.0)
            try:
                base = _writable_root() / "data"
                if not base.is_dir():
                    continue
                for gift_f in base.rglob("gift.csv"):
                    self._tail_csv(gift_f, "gift")
                for chat_f in base.rglob("chat.csv"):
                    self._tail_csv(chat_f, "chat")
            except Exception:
                pass

    def _tail_csv(self, path: Path, kind: str) -> None:
        try:
            key = str(path)
            size = path.stat().st_size
            if size <= 0:
                return
            off = self._csv_offsets.get(key)
            if off is None or off > size:
                off = max(0, size - 4096)
            with open(path, "rb") as f:
                f.seek(off)
                chunk = f.read()
                new_off = f.tell()
            if not chunk:
                self._csv_offsets[key] = new_off
                return
            self._csv_offsets[key] = new_off
            text = chunk.decode("utf-8", errors="replace")
            # 丢弃可能不完整的首行
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines and lines[0].startswith("time,"):
                lines = lines[1:]
            if off > 0 and lines:
                lines = lines[1:]
            for ln in lines[-50:]:
                if kind == "gift":
                    parts = ln.split(",")
                    if len(parts) >= 6:
                        name, gname = parts[2], parts[5]
                        cnt = parts[6] if len(parts) > 6 else "1"
                        dia = parts[7] if len(parts) > 7 else ""
                        to = parts[4] if len(parts) > 4 else ""
                        extra = f" → {to}" if to and to not in ("", '""') else ""
                        dia_s = f" ({dia}抖币)" if dia and dia not in ("", '""') else ""
                        self.events.put(("gift", f"{name} 送出 {gname}×{cnt}{extra}{dia_s}"))
                    else:
                        self.events.put(("gift", ln))
                else:
                    parts = ln.split(",", 3)
                    if len(parts) >= 4:
                        name, content = parts[2], parts[3].rstrip(",")
                        self.events.put(("chat", f"{name}: {content}"))
                    else:
                        self.events.put(("chat", ln))
        except Exception:
            pass

    def _install_log_handler(self) -> None:
        """把 Barrage 的 logging 接到界面日志。"""
        import logging

        studio = self

        class _H(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    if record.levelno < logging.INFO:
                        return
                    msg = record.getMessage()
                    # 过滤过碎的 debug 无关项
                    if not msg or msg.startswith("[数据] 未注册") or msg.startswith("[数据] 低价值"):
                        return
                    studio.events.put(("log", f"{time.strftime('%H:%M:%S')} {msg}"))
                except Exception:
                    pass

        h = _H()
        h.setLevel(logging.INFO)
        logging.getLogger().addHandler(h)
        for name in ("service", "service.fetcher", "base", "base.output"):
            logging.getLogger(name).addHandler(h)

    # ---------- UI 构建 ----------
    def _build_top(self) -> None:
        self.link = ft.TextField(
            hint_text="粘贴直播间链接，或输入房间号",
            prefix_icon=ft.Icons.LINK_ROUNDED,
            width=520,
            height=48,
            bgcolor=C["surface"],
            color=C["text"],
            cursor_color=C["blue"],
            text_size=14,
            border_radius=12,
            border_color=C["border"],
            focused_border_color=C["blue"],
            focused_bgcolor=C["surface"],
            on_submit=lambda _e: self.add_room(),
        )
        self.add_btn = _button(
            "开始采集",
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            fg=C["surface"],
            bg=C["blue"],
            on_click=lambda _e: self.add_room(),
        )

        brand = ft.Row(
            [
                _icon_badge(
                    ft.Icons.VIDEOCAM_ROUNDED,
                    fg=C["surface"],
                    bg=C["blue"],
                    size=42,
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment.TOP_LEFT,
                        end=ft.Alignment.BOTTOM_RIGHT,
                        colors=[C["blue"], "#5AC8FA"],
                    ),
                ),
                ft.Column(
                    [
                        _txt("直播采集工作台", size=24, weight=ft.FontWeight.W_700),
                        _txt("把直播间的弹幕、礼物与录制集中到一个控制台", size=12, color=C["muted"]),
                    ],
                    spacing=3,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.top = _card(
            ft.Column(
                [
                    ft.Row(
                        [
                            brand,
                            _pill("等待接入", fg=C["blue"], bg=C["blue_soft"]),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [self.link, self.add_btn],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=16,
            ),
            padding=18,
            radius=22,
        )

    def _build_sidebar(self) -> None:
        data_btn = _button(
            "数据目录",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=lambda _e: self._open(_writable_root() / "data"),
        )
        video_btn = _button(
            "视频目录",
            icon=ft.Icons.VIDEO_LIBRARY,
            on_click=lambda _e: self._open_videos_root(),
        )
        check_btn = _button(
            "检查环境",
            icon=ft.Icons.REFRESH_ROUNDED,
            on_click=lambda _e: self._check_cookie(),
        )

        self.sidebar = _card(
            ft.Column(
                [
                    ft.Row(
                        [
                            _icon_badge(
                                ft.Icons.DASHBOARD_ROUNDED,
                                fg=C["blue"],
                                bg=C["blue_soft"],
                                size=34,
                            ),
                            _txt("工作台", size=16, weight=ft.FontWeight.W_700),
                        ],
                        spacing=9,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=1, bgcolor=C["border"]),
                    _txt("快捷操作", size=11, color=C["muted"], weight=ft.FontWeight.W_600),
                    data_btn,
                    video_btn,
                    check_btn,
                    ft.Container(height=1, bgcolor=C["border"]),
                    _txt("运行环境", size=11, color=C["muted"], weight=ft.FontWeight.W_600),
                    self.cookie_st,
                    self.env,
                ],
                spacing=12,
                expand=True,
            ),
            padding=16,
            radius=22,
            width=224,
            expand=False,
        )

    def _build_settings(self) -> None:
        self.record_sw = ft.Switch(
            label="录制",
            value=True,
            active_color=C["blue"],
            inactive_thumb_color=C["surface"],
            inactive_track_color="#D1D1D6",
        )
        self.gift_sw = ft.Switch(
            label="记录礼物",
            value=True,
            active_color=C["blue"],
            inactive_thumb_color=C["surface"],
            inactive_track_color="#D1D1D6",
        )
        self.chat_sw = ft.Switch(
            label="弹幕",
            value=True,
            active_color=C["blue"],
            inactive_thumb_color=C["surface"],
            inactive_track_color="#D1D1D6",
        )
        self.quality_dd = ft.Dropdown(
            label="画质",
            width=116,
            options=[
                ft.dropdown.Option(k)
                for k in ("原画", "蓝光", "超清", "高清", "标清")
            ],
            value="原画",
            bgcolor=C["surface"],
            color=C["text"],
            text_size=13,
            border_color=C["border"],
            focused_border_color=C["blue"],
            border_radius=10,
            height=44,
        )
        self.cookie_btn = _button(
            "检查 Cookie",
            icon=ft.Icons.REFRESH_ROUNDED,
            on_click=lambda _e: self._check_cookie(),
        )
        self.cookie_st = _txt("", size=12, color=C["muted"])
        self.env = _txt("", size=11, color=C["muted"])

        controls = ft.Row(
            [
                self.record_sw,
                self.gift_sw,
                self.chat_sw,
                self.quality_dd,
                self.cookie_btn,
                self.cookie_st,
            ],
            spacing=16,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.settings = _card(
            ft.Column(
                [
                    ft.Row(
                        [
                            _icon_badge(
                                ft.Icons.SETTINGS_ROUNDED,
                                fg=C["blue"],
                                bg=C["blue_soft"],
                                size=32,
                            ),
                            _txt("采集设置", size=15, weight=ft.FontWeight.W_600),
                        ],
                        spacing=9,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    controls,
                    _txt(
                        "开关对之后添加的房间生效；已添加的房间可在卡片上单独调整",
                        size=11,
                        color=C["muted"],
                    ),
                    self.env,
                ],
                spacing=10,
            ),
            padding=16,
            radius=18,
        )

    def _build_panels(self) -> None:
        # 实时数据默认不预填，只有真正收到事件后才展示列表。
        self.chat_list = ft.ListView(auto_scroll=True, height=248, spacing=5, visible=False)
        self.gift_list = ft.ListView(auto_scroll=True, height=248, spacing=5, visible=False)
        self.log_list = ft.ListView(auto_scroll=True, height=248, spacing=3, visible=False)
        self.gift_sum = _pill("礼物", fg=C["purple"], bg=C["purple_soft"])
        self.chat_sum = _pill("弹幕", fg=C["blue"], bg=C["blue_soft"])
        log_sum = _pill("日志", fg=C["muted"], bg=C["soft"])
        self.log_count = log_sum

        def empty_state(title: str, subtitle: str, icon: ft.IconData, fg: str, bg: str) -> ft.Container:
            return ft.Container(
                ft.Column(
                    [
                        _icon_badge(icon, fg=fg, bg=bg, size=42),
                        _txt(title, size=14, weight=ft.FontWeight.W_600),
                        _txt(subtitle, size=11, color=C["muted"]),
                    ],
                    spacing=7,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                expand=True,
                alignment=ft.Alignment.CENTER,
            )

        self.chat_empty = empty_state(
            "等待弹幕",
            "接入直播间后，实时弹幕会出现在这里",
            ft.Icons.CHAT_BUBBLE_OUTLINE,
            C["blue"],
            C["blue_soft"],
        )
        self.gift_empty = empty_state(
            "等待礼物",
            "收到礼物事件后，会在这里自动汇总",
            ft.Icons.CARD_GIFTCARD_ROUNDED,
            C["purple"],
            C["purple_soft"],
        )
        self.log_empty = empty_state(
            "等待运行日志",
            "启动采集后，关键状态会显示在这里",
            ft.Icons.INFO_OUTLINE,
            C["muted"],
            C["soft"],
        )

        self.tab_chat = _button(
            "弹幕",
            icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
            fg=C["blue"],
            bg=C["blue_soft"],
            on_click=lambda _e: self._set_feed("chat"),
        )
        self.tab_gift = _button(
            "礼物",
            icon=ft.Icons.CARD_GIFTCARD_ROUNDED,
            fg=C["purple"],
            bg=C["purple_soft"],
            on_click=lambda _e: self._set_feed("gift"),
        )
        self.tab_log = _button(
            "日志",
            icon=ft.Icons.INFO_OUTLINE,
            fg=C["muted"],
            bg=C["soft"],
            on_click=lambda _e: self._set_feed("log"),
        )

        self.feed_title = _txt("实时动态", size=16, weight=ft.FontWeight.W_700)
        self.panels = _card(
            ft.Column(
                [
                    ft.Row(
                        [
                            self.feed_title,
                            self.chat_sum,
                            self.gift_sum,
                            self.log_count,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        wrap=True,
                    ),
                    ft.Row(
                        [self.tab_chat, self.tab_gift, self.tab_log],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.chat_empty,
                    self.chat_list,
                    self.gift_empty,
                    self.gift_list,
                    self.log_empty,
                    self.log_list,
                ],
                spacing=10,
                expand=True,
            ),
            padding=16,
            radius=22,
            expand=True,
            height=380,
        )
        self.active_feed = "chat"
        self._set_feed("chat", push=False)

    def _set_feed(self, kind: str, *, push: bool = True) -> None:
        self.active_feed = kind
        tabs = {
            "chat": (self.tab_chat, C["blue"], C["blue_soft"]),
            "gift": (self.tab_gift, C["purple"], C["purple_soft"]),
            "log": (self.tab_log, C["muted"], C["soft"]),
        }
        for key, (btn, fg, bg) in tabs.items():
            active = key == kind
            btn.bgcolor = bg if active else C["soft"]
            btn.color = fg if active else C["muted"]

        self.chat_empty.visible = kind == "chat" and not self.chat_list.controls
        self.chat_list.visible = kind == "chat" and bool(self.chat_list.controls)
        self.gift_empty.visible = kind == "gift" and not self.gift_list.controls
        self.gift_list.visible = kind == "gift" and bool(self.gift_list.controls)
        self.log_empty.visible = kind == "log" and not self.log_list.controls
        self.log_list.visible = kind == "log" and bool(self.log_list.controls)

        titles = {"chat": "弹幕流", "gift": "礼物动态", "log": "运行日志"}
        self.feed_title.value = titles.get(kind, "实时动态")
        if push:
            self._push()

    def _open(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            pass

    def _open_videos_root(self) -> None:
        """打开 data 下最新的 videos 目录，没有则打开 data。"""
        data = _writable_root() / "data"
        try:
            vids = list(data.rglob("videos"))
            if vids:
                vids.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                self._open(vids[0])
            else:
                self._open(data)
        except Exception:
            self._open(data)

    def _refresh_env(self) -> None:
        import shutil

        node = shutil.which("node")
        ff = shutil.which("ffmpeg")
        cookie = _writable_root() / "cookie.txt"
        if not cookie.is_file():
            cookie = MEIPASS / "cookie.txt"
        has = cookie.is_file() and "sessionid=" in cookie.read_text(encoding="utf-8", errors="replace")
        self.env.value = (
            f"Node {'OK' if node else '缺'}  ·  FFmpeg {'OK' if ff else '缺'}"
        )
        self.env.tooltip = f"输出目录：{_writable_root() / 'data'}"
        self.cookie_st.value = "Cookie 正常" if has else "Cookie 未登录"
        self.cookie_st.color = C["green"] if has else C["orange"]
        self._push()

    def _check_cookie(self) -> None:
        self._refresh_env()
        self._toast("已检查 Cookie / Node / FFmpeg")

    def _push(self) -> None:
        """后台线程刷新界面：Flet 在 Windows 上仅 page.update() 常不生效，需 schedule_update + 主线程 task。"""
        try:
            self.page.schedule_update()
        except Exception:
            pass
        try:
            async def _do():
                try:
                    self.page.update()
                except Exception:
                    pass

            self.page.run_task(_do)
        except Exception:
            try:
                self.page.update()
            except Exception:
                pass

    def _toast(self, msg: str) -> None:
        s = ft.SnackBar(ft.Text(msg))
        try:
            self.page.overlay.append(s)
            s.open = True
            self.page.schedule_update()
        except Exception:
            try:
                self.page.update()
            except Exception:
                pass

    def _log(self, msg: str) -> None:
        self.events.put(("log", f"{time.strftime('%H:%M:%S')} {msg}"))

    # ---------- 采集钩子 ----------
    def _install_recorder_hook(self) -> None:
        if self._patched:
            return
        try:
            from base.output import DataRecorder

            orig = DataRecorder.record
            studio = self

            def record(self, rec_type, data):
                orig(self, rec_type, data)
                if not isinstance(data, dict):
                    return
                try:
                    if rec_type == "chat":
                        name = data.get("user_name") or "?"
                        content = data.get("content") or ""
                        studio.events.put(("chat", f"{name}: {content}"))
                    elif rec_type == "gift":
                        name = data.get("user_name") or "?"
                        gname = data.get("gift_name") or "礼物"
                        cnt = data.get("gift_count") or 1
                        dia = data.get("diamond_total") or 0
                        to_name = data.get("to_user_name") or getattr(self, "_anchor_name", "") or ""
                        extra = f" → {to_name}" if to_name else ""
                        dia_s = f" ({dia}抖币)" if dia else ""
                        studio.events.put(
                            ("gift", f"{name} 送出 {gname}×{cnt}{extra}{dia_s}")
                        )
                except Exception:
                    pass

            DataRecorder.record = record
            self._patched = True
        except Exception as e:
            self._log(f"挂钩失败: {e}")

    # ---------- 房间 ----------
    def add_room(self, _e=None) -> None:
        raw = (self.link.value or "").strip()
        rid = normalize_room(raw)
        if not rid:
            self._toast("请输入直播间链接或 ID")
            return
        if rid in self.rooms and self.rooms[rid].running:
            self._toast("该房间已在运行")
            return
        rt = RoomRuntime(
            rid,
            rid,
            record=bool(self.record_sw.value),
            quality=self.quality_dd.value or "原画",
            gift=bool(self.gift_sw.value),
            chat=bool(self.chat_sw.value),
        )
        self.rooms[rid] = rt
        self.link.value = ""
        self._render_rooms()
        threading.Thread(target=self._run_room, args=(rt,), daemon=True).start()

    def _run_room(self, rt: RoomRuntime) -> None:
        rt.running = True
        rt.status = "启动中"
        self.events.put(("room", rt.live_id))
        try:
            self._write_runtime_config(rt)
            _ensure_cookie()
            from service.fetcher import DouyinBarrage

            def on_info(rid: str, anchor: str) -> None:
                rt.anchor = anchor
                rt.name = anchor or rid
                self.events.put(("log", f"{time.strftime('%H:%M:%S')} 房间信息: {anchor} ({rid})"))
                self.events.put(("room", rt.live_id))

            rt.inst = DouyinBarrage(
                rt.live_id,
                config_file=str(_writable_root() / "ui_runtime.yaml"),
                log_level="INFO",
                on_room_info=on_info,
            )
            rt.status = "采集中"
            self.events.put(("room", rt.live_id))
            self.events.put(
                (
                    "log",
                    f"{time.strftime('%H:%M:%S')} 开始采集 {rt.live_id} "
                    f"录制={rt.record} 礼物={rt.gift} 弹幕={rt.chat}",
                )
            )
            rt.inst.start()
            rt.status = "已结束"
        except Exception as e:
            rt.status = f"错误: {e}"
            self.events.put(("log", f"{time.strftime('%H:%M:%S')} 异常: {e}"))
        finally:
            rt.running = False
            self.events.put(("room", rt.live_id))

    def _write_runtime_config(self, rt: RoomRuntime) -> None:
        """按 UI 开关生成 Barrage 运行配置（写到可写目录）。"""
        rec = "true" if rt.record else "false"
        gift = "true" if rt.gift else "false"
        chat = "true" if rt.chat else "false"
        out_dir = (_writable_root() / "data").as_posix()
        yaml_text = f"""output_dir: {out_dir}
live_stop: false
live_check_interval: 160
log_level: INFO
output:
  chat: {chat}
  gift: {gift}
  like: false
  social: false
  stats: true
  lucky_bag: false
  control: true
  member: false
  rank: false
  fansclub: false
  emoji: false
  room: false
  roomstats: false
barrage:
  csv: true
  sqlite: true
  local_first: false
record:
  enabled: {rec}
  format: ts
  quality: {rt.quality}
  segment_time: 900
  segment_size: 0
  auto_convert: true
api:
  enabled: false
"""
        (_writable_root() / "ui_runtime.yaml").write_text(yaml_text, encoding="utf-8")

    def _render_rooms(self) -> None:
        self.rooms_row.controls.clear()
        for rt in self.rooms.values():
            self.rooms_row.controls.append(self._card(rt))
        row_height = 200 if self.rooms else 84
        self.rooms_row.height = row_height
        self.rooms_row_wrap.height = row_height
        self._push()

    def _card(self, rt: RoomRuntime) -> ft.Control:
        if rt.running:
            status_fg, status_bg, status_text = C["green"], C["green_soft"], "采集中"
        elif "错误" in rt.status:
            status_fg, status_bg, status_text = C["red"], C["red_soft"], "异常"
        elif "停止" in rt.status:
            status_fg, status_bg, status_text = C["orange"], C["orange_soft"], rt.status
        elif rt.status in ("已结束", "结束"):
            status_fg, status_bg, status_text = C["muted"], C["soft"], "已结束"
        else:
            status_fg, status_bg, status_text = C["blue"], C["blue_soft"], rt.status

        chip = ft.Row(
            [
                ft.Container(
                    width=7,
                    height=7,
                    border_radius=999,
                    bgcolor=status_fg,
                ),
                _txt(status_text, size=11, color=status_fg, weight=ft.FontWeight.W_600),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        def stop_room() -> None:
            if rt.inst:
                threading.Thread(target=lambda: rt.inst.stop(), daemon=True).start()
                rt.status = "停止中…"
                self.events.put(("room", rt.live_id))

        def on_record(e, r=rt) -> None:
            r.record = bool(e.control.value)
            r.apply_runtime_flags()
            self.events.put(
                (
                    "log",
                    f"{time.strftime('%H:%M:%S')} [{r.name}] 录制 {'开' if r.record else '关'}",
                )
            )
            self._render_rooms()

        def on_gift(e, r=rt) -> None:
            r.gift = bool(e.control.value)
            r.apply_runtime_flags()
            self.events.put(
                (
                    "log",
                    f"{time.strftime('%H:%M:%S')} [{r.name}] 礼物 {'开' if r.gift else '关'}",
                )
            )
            self._render_rooms()

        def on_chat(e, r=rt) -> None:
            r.chat = bool(e.control.value)
            r.apply_runtime_flags()
            self.events.put(
                (
                    "log",
                    f"{time.strftime('%H:%M:%S')} [{r.name}] 弹幕 {'开' if r.chat else '关'}",
                )
            )
            self._render_rooms()

        return _card(
            ft.Column(
                [
                    ft.Row(
                        [
                            _txt(
                                rt.name or rt.live_id,
                                size=15,
                                weight=ft.FontWeight.W_700,
                            ),
                            chip,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            _pill(f"ID {rt.live_id}", fg=C["muted"], bg=C["soft"]),
                            _pill(f"画质 {rt.quality}", fg=C["blue"], bg=C["blue_soft"]),
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.Switch(
                                label="录制",
                                value=rt.record,
                                active_color=C["blue"],
                                inactive_thumb_color=C["surface"],
                                inactive_track_color="#D1D1D6",
                                on_change=on_record,
                            ),
                            ft.Switch(
                                label="礼物",
                                value=rt.gift,
                                active_color=C["blue"],
                                inactive_thumb_color=C["surface"],
                                inactive_track_color="#D1D1D6",
                                on_change=on_gift,
                            ),
                            ft.Switch(
                                label="弹幕",
                                value=rt.chat,
                                active_color=C["blue"],
                                inactive_thumb_color=C["surface"],
                                inactive_track_color="#D1D1D6",
                                on_change=on_chat,
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.IconButton(
                                ft.Icons.STOP_CIRCLE_OUTLINED,
                                tooltip="停止采集",
                                icon_color=C["red"],
                                bgcolor=C["red_soft"],
                                icon_size=19,
                                on_click=lambda _e, r=rt: stop_room(),
                            ),
                            ft.IconButton(
                                ft.Icons.DELETE_OUTLINE,
                                tooltip="移除房间",
                                icon_color=C["muted"],
                                bgcolor=C["soft"],
                                icon_size=19,
                                on_click=lambda _e, r=rt: self._remove_room(r),
                            ),
                            _txt("采集控制", size=11, color=C["muted"]),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=10,
            ),
            padding=16,
            radius=18,
            width=340,
            height=186,
        )

    def _remove_room(self, rt: RoomRuntime) -> None:
        if rt.running:
            self._toast("请先停止采集")
            return
        self.rooms.pop(rt.live_id, None)
        self._render_rooms()

    # ---------- UI 事件循环 ----------
    def _ui_loop(self) -> None:
        chat_n = 0
        gift_n = 0
        last_render = 0.0
        MAX_CHAT, MAX_GIFT, MAX_LOG = 80, 60, 100
        while True:
            try:
                kind, payload = self.events.get(timeout=0.2)
            except queue.Empty:
                kind = None
                payload = None
            dirty = False
            if kind == "chat":
                chat_n += 1
                self.chat_list.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.CHAT_BUBBLE_OUTLINE,
                                    size=14,
                                    color=C["blue"],
                                ),
                                _txt(str(payload), size=12),
                            ],
                            spacing=7,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding.symmetric(vertical=7, horizontal=9),
                        border_radius=10,
                        bgcolor=C["surface_alt"],
                    )
                )
                if len(self.chat_list.controls) > MAX_CHAT:
                    self.chat_list.controls = self.chat_list.controls[-MAX_CHAT:]
                self.chat_sum.content.value = f"弹幕 {chat_n}"
                self._set_feed(self.active_feed, push=False)
                dirty = True
            elif kind == "gift":
                gift_n += 1
                self.gift_list.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.CARD_GIFTCARD_ROUNDED,
                                    size=14,
                                    color=C["purple"],
                                ),
                                _txt(str(payload), size=12),
                            ],
                            spacing=7,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding.symmetric(vertical=7, horizontal=9),
                        border_radius=10,
                        bgcolor=C["purple_soft"],
                    )
                )
                if len(self.gift_list.controls) > MAX_GIFT:
                    self.gift_list.controls = self.gift_list.controls[-MAX_GIFT:]
                self.gift_sum.content.value = f"礼物 {gift_n}"
                self._set_feed(self.active_feed, push=False)
                dirty = True
            elif kind == "log":
                self.log_list.controls.append(
                    ft.Container(
                        _txt(str(payload), size=11, color=C["muted"]),
                        padding=ft.Padding.symmetric(vertical=5, horizontal=8),
                        border_radius=8,
                        bgcolor=C["surface_alt"],
                    )
                )
                if len(self.log_list.controls) > MAX_LOG:
                    self.log_list.controls = self.log_list.controls[-MAX_LOG:]
                self.log_count.content.value = f"日志 {len(self.log_list.controls)}"
                self._set_feed(self.active_feed, push=False)
                dirty = True
            elif kind == "room":
                now = time.time()
                if now - last_render > 0.3:
                    self._render_rooms()
                    last_render = now
                else:
                    time.sleep(0.25)
                    self._render_rooms()
                    last_render = time.time()
            if kind or dirty:
                self._push()


_STUDIO: Optional[Studio] = None


def main() -> None:
    global _STUDIO

    def run(page: ft.Page) -> None:
        global _STUDIO
        _STUDIO = Studio(page)

    ft.app(target=run)


if __name__ == "__main__":
    main()




