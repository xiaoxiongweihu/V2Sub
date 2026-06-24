# 实时语音翻译字幕

采集**系统音频**（视频/直播/网课/会议正在播放的声音）→ **faster-whisper** 本地转写 →
**OpenAI 兼容大模型**翻译 → **透明置顶悬浮窗**实时显示字幕，并支持**专业术语表**管理。

## ✨ 功能特性

- 🎙️ **系统音频回环采集**：无需麦克风，直接捕获电脑正在播放的声音
- ⚡ **faster-whisper 本地识别**：GPU 加速（CUDA），低延迟、隐私好
- 🌐 **OpenAI 兼容翻译**：支持 OpenAI 官方及 DeepSeek / Moonshot / 智谱 / 本地 Ollama 等任何兼容接口
- 📺 **透明悬浮字幕**：始终置顶、半透明、可鼠标穿透（不挡下层视频/游戏操作）
- 📖 **专业术语表**：界面增删改查 + Excel/CSV 导入导出，自动注入翻译确保术语一致
- 🎯 **目标语言可选**：默认中文，下拉可切换英/日/韩/法等
- 🖥️ **系统托盘**：最小化到托盘，热键/双击恢复

## 📦 项目结构

```
ZCodeProject/
├── main.py                 # 程序入口（含 CUDA DLL 路径自动设置）
├── config.py               # 配置管理（settings.json 持久化）
├── requirements.txt
├── README.md
├── core/                   # 核心处理层
│   ├── audio_capture.py    # 系统音频回环采集（soundcard WASAPI loopback）
│   ├── segmenter.py        # VAD 静音分段（RMS 能量阈值）
│   ├── transcriber.py      # faster-whisper 封装（GPU/CPU 自动选择）
│   ├── translator.py       # OpenAI 兼容翻译 + 术语注入
│   └── glossary.py         # 术语表管理 + CSV/Excel 导入导出
├── ui/                     # PyQt5 界面层
│   ├── overlay.py          # 透明置顶悬浮窗（鼠标穿透、拖动、滚轮调透明度）
│   ├── main_window.py      # 主控窗口 + 3 线程流水线编排 + 系统托盘
│   ├── settings_dialog.py  # 设置对话框（API/Whisper/音频/VAD/悬浮窗）
│   └── glossary_dialog.py  # 术语增删改查对话框
└── data/
    └── glossary.json       # 默认术语表（示例）
```

## 🚀 安装

### 环境要求
- **Python 3.10 ~ 3.14**（稳定版）
- **NVIDIA GPU（可选但强烈推荐）**：faster-whisper 在 CUDA 上速度快几倍
  - 本机实测：RTX 4070 + CUDA int8_float16，tiny 模型转写延迟 < 1s
- **Windows 10/11**（系统音频回环依赖 WASAPI loopback）

### 安装步骤

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 2. 安装所有依赖（含 CUDA 12 运行时，约 600MB）
pip install -r requirements.txt
```

> 首次运行 faster-whisper 会自动下载所选模型到用户缓存目录：
> | 模型 | 大小 | 速度 | 准确度 |
> |------|------|------|--------|
> | tiny | ~75MB | 最快 | 一般 |
> | base | ~150MB | 快 | 尚可 |
> | **small**（推荐） | ~460MB | **快** | **好** |
> | medium | ~1.5GB | 中等 | 很好 |
> | large-v3 | ~3GB | 慢 | 最好 |

### CUDA 说明

程序启动时 `main.py` 会自动把 pip 安装的 CUDA 12 DLL 加入搜索路径，
无需手动配置环境变量。如果你已有系统级 CUDA Toolkit 12.x（`cublas64_12.dll` 在 PATH 中），
可以跳过 `requirements.txt` 中的 `nvidia-*-cu12` 三行。

如果系统只有 CUDA 13.x（如本机），则需要 `nvidia-cublas-cu12` 等包提供 CUDA 12 运行时，
因为 ctranslate2 当前仅兼容 CUDA 12.x。

## 🎮 使用

```bash
.venv\Scripts\activate
python main.py
```

1. 打开后点击 **⚙ 设置**：
   - 填写翻译 API 的 **Base URL** 和 **API Key**，选择模型：
     - OpenAI：`https://api.openai.com/v1`，模型 `gpt-4o-mini`
     - DeepSeek：`https://api.deepseek.com/v1`，模型 `deepseek-chat`
     - 本地 Ollama：`http://localhost:11434/v1`，模型 `qwen2.5:7b`（key 随便填）
   - 选择 Whisper 模型大小、设备（有 GPU 选 auto 会自动走 CUDA）
   - 设置目标语言（默认中文）
   - 点 **测试连接** 确认翻译 API 可用
2. 播放任意带声音的视频/直播（系统音频即被采集）
3. 点 **▶ 开始翻译**，悬浮窗实时显示字幕
4. 点 **📖 术语表** 添加专业词汇（如 `API=应用程序接口`），或在对话框中导入 Excel/CSV

### 悬浮窗操作

| 操作 | 功能 |
|------|------|
| 拖动 | 移动位置 |
| 双击 | 切换鼠标穿透（穿透后可点透到下层窗口） |
| 滚轮 | 调节背景不透明度 |
| 右键 | 菜单（穿透开关 / 开始停止 / 清空字幕 / 隐藏） |

## ⚙️ 关键参数调优

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `vad_threshold` | 静音检测 RMS 阈值（太小=噪声误触发，太大=漏检） | `0.012` |
| `vad_silence_duration` | 多久静音算一句话结束（秒） | `0.45` |
| `whisper_model` | 实时推荐 `small`，离线精翻用 `large-v3` | `small` |
| `overlay_opacity` | 悬浮窗背景不透明度 | `0.75` |

## 🔧 故障排查

- **音频采不到声音**：确认播放音源正在出声；设置里点"刷新设备"选正确的回环设备
- **悬浮窗挡住鼠标**：双击它开启鼠标穿透（变透明可点穿）
- **翻译失败只显示原文**：检查 API Key / Base URL / 模型名；悬浮窗会用红色标记失败条目
- **首次启动卡住**：faster-whisper 正在下载/加载模型，状态栏会提示进度
- **`cublas64_12.dll not found`**：GPU 模式需要 CUDA 12 运行时，确认已 `pip install nvidia-cublas-cu12`

## 📐 架构

```
[AudioWorker 线程] 采集系统音频 + VAD分段 → segment(音频块)
        ↓ Qt 信号
[TranscribeWorker 线程] faster-whisper GPU/CPU 转写 → 文本
        ↓ Qt 信号
[TranslateWorker 线程] 调大模型(术语注入prompt) → 译文
        ↓ Qt 信号
   主线程更新 悬浮窗 + 历史列表
```

三段各自独立线程、信号解耦：识别慢不阻塞采集，翻译慢不阻塞识别。
