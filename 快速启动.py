"""DouyinBarrage 交互启动器：填房间号，选是否录制。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _add_tools_path() -> None:
    for rel in (
        "tools/node/node-v20.18.0-win-x64",
        "tools/ffmpeg/bin",
    ):
        d = ROOT / rel
        if d.is_dir():
            os.environ["PATH"] = f"{d};{os.environ.get('PATH', '')}"


def _check_env() -> bool:
    import shutil

    ok = True
    node = shutil.which("node")
    ff = shutil.which("ffmpeg")
    print("=" * 42)
    print("  DouyinBarrage 快速启动")
    print("=" * 42)
    print(f"Node:    {node or '未找到（礼物签名需要）'}")
    print(f"FFmpeg:  {ff or '未找到（录制需要）'}")
    cookie = ROOT / "cookie.txt"
    has_sid = False
    if cookie.is_file():
        text = cookie.read_text(encoding="utf-8", errors="replace")
        has_sid = "sessionid=" in text
        print(f"Cookie:  {'有 sessionid' if has_sid else '缺少 sessionid，礼物可能受限'}  ({cookie})")
    else:
        print("Cookie:  缺少 cookie.txt")
        ok = False
    rooms = ROOT / "rooms.txt"
    print(f"rooms:   {rooms if rooms.is_file() else '（无，可直接输入房间号）'}")
    print("=" * 42)
    return ok


def _load_rooms() -> list[tuple[str, str]]:
    path = ROOT / "rooms.txt"
    if not path.is_file():
        return []
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if parts and parts[0]:
            out.append((parts[0], parts[1] if len(parts) > 1 else parts[0]))
    return out


def main() -> None:
    os.chdir(ROOT)
    _add_tools_path()
    if not _check_env():
        print("\n请先补齐 cookie.txt 再启动。")
        sys.exit(1)

    rooms = _load_rooms()
    if rooms:
        print("\nrooms.txt 中的房间:")
        for i, (rid, name) in enumerate(rooms, 1):
            print(f"  {i}. {rid}  {name}")

    print("\n[1] rooms.txt 全部")
    print("[2] 输入直播间 ID")
    choice = input("选择 [1]: ").strip() or "1"
    rec = input("是否录制? Y/n [Y]: ").strip().lower() not in ("n", "no")

    cmd = [sys.executable, "main.py"]
    if choice == "2":
        rid = input("直播间 ID: ").strip()
        if not rid:
            print("未输入 ID")
            sys.exit(1)
        cmd.append(rid)
    else:
        if not rooms:
            print("rooms.txt 为空，请改用 [2] 输入 ID")
            sys.exit(1)
        cmd.append("--all")
    if rec:
        cmd.append("--record")

    print(f"\n运行: {' '.join(cmd)}\n")
    os.execv(sys.executable, cmd)


if __name__ == "__main__":
    main()
