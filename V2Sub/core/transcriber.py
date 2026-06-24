"""faster-whisper 封装：模型加载 + 语段转写。

使用 CTranslate2 后端，GPU（CUDA）优先。模型在首次构造时下载缓存。
"""
from __future__ import annotations

import numpy as np

try:
    from faster_whisper import WhisperModel
    _FW_OK = True
except Exception:
    WhisperModel = None  # type: ignore
    _FW_OK = False


def resolve_device(device: str) -> str:
    if device == "auto":
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda"
        except Exception:
            pass
        return "cpu"
    return device


def resolve_compute_type(device: str, compute_type: str) -> str:
    if compute_type != "auto":
        return compute_type
    # GPU 用 int8_float16 兼顾速度与显存；CPU 用 float32（更稳定兼容）
    return "int8_float16" if device == "cuda" else "float32"


class Transcriber:
    def __init__(self,
                 model_size: str = "small",
                 device: str = "auto",
                 compute_type: str = "auto",
                 language: str = "auto",
                 model_path: str = "") -> None:
        if not _FW_OK:
            raise RuntimeError(
                "faster-whisper 未安装，请 `pip install faster-whisper`。"
            )
        self.model_size = model_size
        self.model_path = model_path  # 本地路径，优先于 model_size
        self.language = None if language in ("auto", "", None) else language
        self._device = resolve_device(device)
        self._compute_type = resolve_compute_type(self._device, compute_type)
        # 模型懒加载
        self._model: "WhisperModel | None" = None

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    def load(self) -> None:
        """显式加载模型（首次较慢）。model_path 非空时优先使用本地路径。"""
        if self._model is None:
            model_ref = self.model_path or self.model_size
            print(f"[DEBUG] WhisperModel(ref={model_ref}, device={self._device}, compute={self._compute_type})...", flush=True)
            self._model = WhisperModel(
                model_ref,
                device=self._device,
                compute_type=self._compute_type,
            )
            print("[DEBUG] WhisperModel 构造完成", flush=True)

    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: np.ndarray) -> str:
        """转写一段 16kHz float32 音频，返回纯文本。"""
        self.load()
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            vad_filter=True,
            beam_size=5,
            without_timestamps=True,
        )
        # faster-whisper 的 segments 是生成器，需迭代消费
        return "".join(seg.text for seg in segments).strip()
