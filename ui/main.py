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
        page.theme_mode = ft.ThemeMode.DARK
        try:
            page.window.width = 1180
            page.window.height = 860
        except Exception:
            page.width = 1180
            page.height = 860
        page.padding = 12
        page.spacing = 10

        self._build_top()
        self._build_settings()
        self._build_panels()
        self.rooms_row = ft.Row(
            spacing=10,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._chat_n = 0
        self._gift_n = 0
        self._csv_offsets: dict[str, int] = {}
        # 主列：顶栏/设置/房间可滚动，下面列表撑满剩余高度
        self.page.add(
            ft.Column(
                [
                    self.top,
                    self.settings,
                    ft.Text("直播间", weight=ft.FontWeight.BOLD),
                    self.rooms_row,
                    self.panels,
                ],
                expand=True,
                spacing=10,
            )
        )
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
        self._log("已接入 Barrage 日志")

    # ---------- UI 构建 ----------
    def _build_top(self) -> None:
        self.link = ft.TextField(
            label="直播间链接 / ID",
            hint_text="https://live.douyin.com/房间号 或 纯数字",
            width=360,
            height=46,
            on_submit=lambda _e: self.add_room(),
        )
        self.add_btn = ft.Button(
            "添加",
            on_click=lambda _e: self.add_room(),
            bgcolor=ft.Colors.PURPLE_400,
            color=ft.Colors.WHITE,
        )
        self.open_data = ft.OutlinedButton(
            "打开数据目录",
            on_click=lambda _e: self._open(_writable_root() / "data"),
        )
        self.open_videos = ft.OutlinedButton(
            "打开视频目录",
            on_click=lambda _e: self._open_videos_root(),
        )
        self.top = ft.Row(
            [
                ft.Container(
                    ft.Icon(ft.Icons.VIDEOCAM_ROUNDED, color=ft.Colors.WHITE, size=20),
                    bgcolor=ft.Colors.PURPLE_400,
                    width=34,
                    height=34,
                    border_radius=8,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Text("抖音直播助手", size=18, weight=ft.FontWeight.BOLD),
                self.link,
                self.add_btn,
                self.open_data,
                self.open_videos,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_settings(self) -> None:
        self.record_sw = ft.Switch(
            label="录制",
            value=True,
            active_color=ft.Colors.PURPLE_300,
        )
        self.gift_sw = ft.Switch(
            label="记录礼物",
            value=True,
            active_color=ft.Colors.PURPLE_300,
        )
        self.chat_sw = ft.Switch(
            label="弹幕",
            value=True,
            active_color=ft.Colors.PURPLE_300,
        )
        self.quality_dd = ft.Dropdown(
            label="画质",
            width=100,
            options=[
                ft.dropdown.Option(k)
                for k in ("原画", "蓝光", "超清", "高清", "标清")
            ],
            value="原画",
        )
        self.cookie_btn = ft.OutlinedButton("检查Cookie", on_click=lambda _e: self._check_cookie())
        self.cookie_st = ft.Text("", size=12, color=ft.Colors.BLUE_GREY_300)
        self.env = ft.Text("", size=11, color=ft.Colors.BLUE_GREY_400)
        self.settings = ft.Container(
            bgcolor=ft.Colors.BLUE_GREY_900,
            border_radius=10,
            padding=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("设置", weight=ft.FontWeight.BOLD),
                            self.record_sw,
                            self.gift_sw,
                            self.chat_sw,
                            self.quality_dd,
                            self.cookie_btn,
                            self.cookie_st,
                        ],
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "开关对「之后添加的房间」生效；已添加的房间在卡片上单独看录制/礼物状态",
                        size=11,
                        color=ft.Colors.BLUE_GREY_400,
                    ),
                    self.env,
                ],
                spacing=6,
            ),
        )

    def _build_panels(self) -> None:
        # 必须给固定高度：expand 在无约束父级里会塌成 0，看起来就是空的
        self.chat_list = ft.ListView(auto_scroll=True, height=280, spacing=2)
        self.gift_list = ft.ListView(auto_scroll=True, height=280, spacing=2)
        self.log_list = ft.ListView(auto_scroll=True, height=200, spacing=1)
        self.gift_sum = ft.Text("礼物 0 条", size=13, color=ft.Colors.PURPLE_200)
        self.chat_sum = ft.Text("弹幕 0 条", size=13, color=ft.Colors.PURPLE_200)

        def box(title: str, extra: ft.Control, lst: ft.ListView) -> ft.Control:
            return ft.Container(
                bgcolor=ft.Colors.BLUE_GREY_900,
                border_radius=10,
                padding=10,
                expand=True,
                content=ft.Column(
                    [
                        ft.Row(
                            [ft.Text(title, weight=ft.FontWeight.BOLD), extra],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        lst,
                    ],
                    spacing=6,
                    tight=True,
                ),
            )

        self.panels = ft.Row(
            [
                box("弹幕", self.chat_sum, self.chat_list),
                box("礼物", self.gift_sum, self.gift_list),
                box("日志", ft.Text("", size=12), self.log_list),
            ],
            spacing=10,
            expand=True,
        )

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
            f"Node: {'OK' if node else '缺'}  ·  FFmpeg: {'OK' if ff else '缺'}  ·  "
            f"输出: {_writable_root() / 'data'}"
        )
        self.cookie_st.value = "Cookie OK（含 sessionid）" if has else "Cookie 缺失/无登录态"
        self.cookie_st.color = ft.Colors.GREEN_400 if has else ft.Colors.ORANGE_400
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
            self._log("已挂钩弹幕/礼物到界面")
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
        self._push()

    def _card(self, rt: RoomRuntime) -> ft.Control:
        color = (
            ft.Colors.GREEN_400
            if rt.running
            else (ft.Colors.ORANGE_400 if "错误" in rt.status else ft.Colors.BLUE_GREY_400)
        )
        chip = ft.Container(
            ft.Text(rt.status, size=12, color=ft.Colors.WHITE),
            bgcolor=color,
            padding=ft.Padding.symmetric(vertical=2, horizontal=10),
            border_radius=12,
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

        return ft.Container(
            width=320,
            bgcolor=ft.Colors.BLUE_GREY_900,
            border_radius=12,
            padding=12,
            content=ft.Column(
                [
                    ft.Row([ft.Text(rt.name or rt.live_id, weight=ft.FontWeight.BOLD, expand=True), chip]),
                    ft.Text(f"ID: {rt.live_id}", size=11, color=ft.Colors.BLUE_GREY_400),
                    ft.Text(f"画质: {rt.quality}", size=12, color=ft.Colors.BLUE_GREY_200),
                    ft.Row(
                        [
                            ft.Switch(
                                label="录制",
                                value=rt.record,
                                active_color=ft.Colors.PURPLE_300,
                                on_change=on_record,
                            ),
                            ft.Switch(
                                label="礼物",
                                value=rt.gift,
                                active_color=ft.Colors.PURPLE_300,
                                on_change=on_gift,
                            ),
                            ft.Switch(
                                label="弹幕",
                                value=rt.chat,
                                active_color=ft.Colors.PURPLE_300,
                                on_change=on_chat,
                            ),
                        ],
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.IconButton(
                                ft.Icons.STOP_CIRCLE_OUTLINED,
                                tooltip="停止",
                                on_click=lambda _e, r=rt: stop_room(),
                            ),
                            ft.IconButton(
                                ft.Icons.DELETE_OUTLINE,
                                tooltip="移除",
                                on_click=lambda _e, r=rt: self._remove_room(r),
                            ),
                        ]
                    ),
                ],
                spacing=8,
            ),
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
                self.chat_list.controls.append(ft.Text(payload, size=12))
                if len(self.chat_list.controls) > MAX_CHAT:
                    self.chat_list.controls = self.chat_list.controls[-MAX_CHAT:]
                self.chat_sum.value = f"弹幕 {chat_n} 条（显示最近 {MAX_CHAT}）"
                dirty = True
            elif kind == "gift":
                gift_n += 1
                self.gift_list.controls.append(
                    ft.Text(payload, size=12, color=ft.Colors.PURPLE_200)
                )
                if len(self.gift_list.controls) > MAX_GIFT:
                    self.gift_list.controls = self.gift_list.controls[-MAX_GIFT:]
                self.gift_sum.value = f"礼物 {gift_n} 条（显示最近 {MAX_GIFT}）"
                dirty = True
            elif kind == "log":
                self.log_list.controls.append(ft.Text(payload, size=12, color=ft.Colors.WHITE70))
                if len(self.log_list.controls) > MAX_LOG:
                    self.log_list.controls = self.log_list.controls[-MAX_LOG:]
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
