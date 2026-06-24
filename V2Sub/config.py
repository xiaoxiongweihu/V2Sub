"""配置管理：持久化到 settings.json，单例访问。

所有可配置项集中于此，GUI 通过 Config 实例读写并触发保存。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any


# 默认设置；用户改动会覆盖保存到 settings.json
DEFAULTS: dict[str, Any] = {
    # --- AI 翻译（OpenAI 兼容接口）---
    "api_base_url": "https://api.openai.com/v1",
    "api_key": "",
    "llm_model": "gpt-4o-mini",
    "target_language": "中文",          # 默认译为中文
    "translation_temperature": 0.3,

    # --- Whisper 本地转写 ---
    "whisper_model": "small",            # tiny/base/small/medium/large-v3
    "whisper_model_path": "",            # 本地模型路径（空=使用上方模型名从 HuggingFace 下载）
    "whisper_device": "auto",            # auto / cpu / cuda
    "whisper_compute_type": "float32",      # auto / int8 / int8_float16 / float16 / float32（CPU 推荐 float32）
    "source_language": "auto",           # auto=自动检测，或 en/ja/zh/...

    # --- 音频采集 ---
    "audio_device": "",                  # 空字符串=默认回环设备
    "sample_rate": 16000,

    # --- VAD 静音分段 ---
    "vad_threshold": 0.012,              # RMS 能量阈值（float32 振幅）
    "vad_silence_duration": 0.45,        # 静音多久判定一句话结束（秒）
    "vad_min_segment": 0.5,             # 最小语段长度（秒），过短丢弃
    "vad_max_segment": 15.0,            # 最大语段长度（秒），过长强制截断

    # --- 悬浮窗 ---
    "overlay_opacity": 0.75,             # 背景不透明度 0~1
    "overlay_font_size": 22,             # 译文字号
    "show_original": True,               # 是否在悬浮窗显示原文行
    "overlay_max_lines": 3,             # 悬浮窗最多显示几条
    "overlay_x": -1,                     # 悬浮窗 X 坐标（-1=自动居中）
    "overlay_y": -1,                     # 悬浮窗 Y 坐标（-1=屏幕底部）
    "overlay_width": 720,                # 悬浮窗宽度
    "overlay_height": 140,              # 悬浮窗高度

    # --- 其它 ---
    "hotkey_toggle": "ctrl+alt+t",       # 全局热键：开始/停止
    "auto_start_overlay": True,          # 启动即显示悬浮窗
}


class Config:
    """单例配置：load/save 到 JSON，支持 dict 式访问与回调通知。"""

    _instance: "Config | None" = None

    def __init__(self, path: str = "settings.json") -> None:
        self._path = path
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._callbacks: list = []
        self.load()

    @classmethod
    def instance(cls, path: str = "settings.json") -> "Config":
        if cls._instance is None:
            cls._instance = cls(path)
        return cls._instance

    # ---- 持久化 ----
    def load(self) -> None:
        if os.path.isfile(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 合并：保留默认项，覆盖已保存项
                self._data.update(saved)
            except (json.JSONDecodeError, OSError):
                pass  # 损坏则用默认值

    def save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ---- dict 式访问 ----
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        if save:
            self.save()
        for cb in self._callbacks:
            try:
                cb(key, value)
            except Exception:
                pass

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def update(self, mapping: dict[str, Any], save: bool = True) -> None:
        for k, v in mapping.items():
            self._data[k] = v
        if save:
            self.save()
        for cb in self._callbacks:
            try:
                cb(None, None)
            except Exception:
                pass

    def on_change(self, callback) -> None:
        self._callbacks.append(callback)
