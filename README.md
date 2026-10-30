# DouYinLiveTool

抖音直播 **弹幕 / 礼物 / 录制** 一体工具。

- 采集核心：[DouyinBarrage](https://github.com/xhynice/DouyinBarrage)（WebSocket + 本地 sign.js）
- 桌面界面：Flet（填房间、开关、实时弹幕/礼物、日志）

## 功能

- 粘贴直播间链接或 ID
- 房间卡片独立开关：**录制** / **礼物** / **弹幕**（运行中可改）
- 全局默认：画质、分段时长（默认 **15 分钟**）、是否自动转 MP4
- 实时查看弹幕、礼物；日志面板
- 数据：CSV + SQLite；视频在会话目录下的 `videos\`
- 自动识别登录 Cookie（含 `sessionid` 时礼物更完整）

## 目录结构

```
data/{主播}/{会话}/
├── chat.csv / gift.csv / …
├── *.db
└── videos/          # 录像（分段 TS，结束后可转 MP4）
```

## 快速开始（源码）

```powershell
pip install -r requirements.txt

# Cookie（必填，否则礼物可能受限）
copy cookie.example.txt cookie.txt
# 浏览器登录 douyin.com → F12 复制 Cookie → 覆盖 cookie.txt

# 需要系统或 tools 下有 Node.js（签名）与 FFmpeg（录制）
python run_ui.py
# 或
启动UI.bat
```

也可用 AI 助手在本机把浏览器导出的 Netscape cookies 转成 `cookie.txt`，Cookie 只留本地、勿提交 Git。

## CLI

```bash
python main.py <直播间ID> --record
python main.py --all --record
```

## Windows 便携版

见 [Releases](../../releases)：下载 zip 解压后运行 `抖音直播助手\抖音直播助手.exe`。  
包内已含 Node / FFmpeg；**不包含** Cookie，请自行放置 `cookie.txt`。

## 配置要点（config.yaml）

| 项 | 说明 |
|----|------|
| `output_dir` | 数据根目录（默认 `data`） |
| `record.segment_time` | 分段秒数（900=15 分钟） |
| `record.quality` | 原画 / 蓝光 / 超清… |
| `output.gift` / `chat` | 消息类型开关 |

## 隐私

- **不要**提交 `cookie.txt`、`data/`、录制文件
- 本仓库不含真实 Cookie / 用户数据

## 免责声明

仅供学习研究，请遵守平台规则与当地法律，勿用于商业滥用。

## License

基于上游 [DouyinBarrage](https://github.com/xhynice/DouyinBarrage)（MIT）扩展。
