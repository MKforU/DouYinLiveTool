"""UI 入口：设置 PATH 后启动 Flet。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 打包后 resources 在 _internal
if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS", ROOT))

for rel in (
    "tools/node/node-v20.18.0-win-x64",
    "tools/ffmpeg/bin",
):
    d = ROOT / rel
    if d.is_dir():
        os.environ["PATH"] = f"{d};{os.environ.get('PATH', '')}"

# 源码运行时也把 DouyinBarrage 根目录加入 path
src_root = Path(__file__).resolve().parent
if str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))

from ui.main import main  # noqa: E402

if __name__ == "__main__":
    main()
