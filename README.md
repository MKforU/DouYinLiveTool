# DouYinLiveTool

抖音直播 **弹幕 / 礼物 / 录制** 桌面工具（基于 [DouyinBarrage](https://github.com/xhynice/DouyinBarrage) 的采集核心 + Flet UI）。

## 功能

- 粘贴直播间链接或 ID
- 独立开关：**录制** / **记录礼物** / **弹幕**
- 实时查看弹幕、礼物
- 数据落盘：CSV + SQLite，录制为 TS（可转 MP4）
- 自带便携 Node（签名）与 FFmpeg（录制）的本地目录结构（不入库）

## 快速开始（源码）

```powershell
# 1. 安装依赖
pip install -r requirements.txt

# 2. Cookie（必填，否则礼物/弹幕受限）
copy cookie.example.txt cookie.txt
# 浏览器登录 douyin.com → F12 → 复制 Cookie → 粘贴覆盖 cookie.txt
# 需包含 sessionid

# 3. 需要 Node.js ≥ 16（WSS 签名）与 FFmpeg（录制）

# 4. 启动 UI
python run_ui.py
# 或
启动UI.bat
```

CLI 方式：

```bash
python main.py <直播间ID> --record
python main.py --all --record
```

## 输出目录

```
data/{主播名}/
├── meta.json
└── YYYYMMDD_HHMM/
    ├── chat.csv / gift.csv / ...
    └── 视频分段.ts
```

## 隐私

- **不要**把 `cookie.txt` 提交到 Git（已在 `.gitignore`）
- 本仓库不含任何真实 Cookie / 录制数据

## 免责声明

仅供学习研究，请遵守平台规则与当地法律，勿用于商业滥用。
