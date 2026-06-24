"""VAD 静音分段：把连续音频流切成完整语段。

策略（基于 RMS 能量的简单但有效的 VAD）：
- 累积输入音频块
- 逐块计算 RMS 能量
- 说话中：能量 ≥ 阈值 视为有声
- 静音累计达到 silence_duration 且之前有有声内容 → 切段
- 段长超过 max_segment 强制截断（防长发言堆积延迟）
- 段长不足 min_segment 丢弃（防噪声误触发）
"""
from __future__ import annotations

import numpy as np


class Segmenter:
    def __init__(self,
                 sample_rate: int = 16000,
                 threshold: float = 0.012,
                 silence_duration: float = 0.45,
                 min_segment: float = 0.5,
                 max_segment: float = 15.0) -> None:
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.silence_duration = silence_duration
        self.min_segment = min_segment
        self.max_segment = max_segment

        self._buffer: list[np.ndarray] = []
        self._buffer_samples = 0
        self._speaking = False            # 当前是否处于有声段
        self._silence_samples = 0         # 连续静音采样数

    def reset(self) -> None:
        self._buffer.clear()
        self._buffer_samples = 0
        self._speaking = False
        self._silence_samples = 0

    def update_params(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def feed(self, chunk: np.ndarray) -> list[np.ndarray]:
        """喂入一个音频块，返回本次产出的完整语段列表（可能为空）。"""
        segments: list[np.ndarray] = []
        if isinstance(chunk, dict):
            return segments  # 错误占位，忽略
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)

        rms = float(np.sqrt(np.mean(chunk ** 2) + 1e-12))
        is_voiced = rms >= self.threshold

        self._buffer.append(chunk)
        self._buffer_samples += chunk.size

        max_samples = int(self.max_segment * self.sample_rate)
        min_samples = int(self.min_segment * self.sample_rate)
        silence_limit = int(self.silence_duration * self.sample_rate)

        if is_voiced:
            self._speaking = True
            self._silence_samples = 0
        else:
            if self._speaking:
                self._silence_samples += chunk.size

        # 触发切段：静音够长 & 之前有内容
        if self._speaking and self._silence_samples >= silence_limit:
            seg = self._flush()
            if seg is not None and seg.size >= min_samples:
                segments.append(seg)
            return segments

        # 触发截断：超最大段长（无论是否静音）
        if self._speaking and self._buffer_samples >= max_samples:
            seg = self._flush()
            if seg is not None and seg.size >= min_samples:
                segments.append(seg)
            return segments

        return segments

    def flush(self) -> np.ndarray | None:
        """强制吐出当前缓冲（停止采集时调用）。"""
        return self._flush()

    def _flush(self) -> np.ndarray | None:
        if not self._buffer or self._buffer_samples == 0:
            return None
        seg = np.concatenate(self._buffer) if len(self._buffer) > 1 else self._buffer[0]
        self._buffer.clear()
        self._buffer_samples = 0
        self._speaking = False
        self._silence_samples = 0
        return np.ascontiguousarray(seg, dtype=np.float32)
