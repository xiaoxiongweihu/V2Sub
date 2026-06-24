"""系统音频回环采集（WASAPI loopback）。

依赖 soundcard：在 Windows 上通过 `include_loopback=True` 拿到回环设备，
能捕获系统正在播放的声音（视频/直播/网课等）。

后台线程持续录制，按块回调推送 16kHz / mono / float32 的 numpy 数组。
"""
from __future__ import annotations

import threading
import queue
import numpy as np
import sys

try:
    import soundcard as sc
    _SOUNDCARD_OK = True
except Exception:
    sc = None
    _SOUNDCARD_OK = False


class AudioCapture:
    """单例式系统音频采集器，向队列/回调推送音频块。"""

    def __init__(self, sample_rate: int = 16000,
                 device_name: str | None = None,
                 block_ms: int = 100) -> None:
        """
        sample_rate: 输出采样率（Whisper 要求 16kHz）
        device_name: 指定回环设备名；None=默认
        block_ms:   每次回调的块时长（毫秒）
        """
        self.sample_rate = sample_rate
        self.device_name = device_name
        self.block_ms = block_ms
        self._running = False
        self._thread: threading.Thread | None = None
        # 默认队列：消费者可改成自己的回调
        self.queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=200)

    # ---- 设备枚举 ----
    @staticmethod
    def list_loopback_devices() -> list[str]:
        """返回可用的系统音频回环设备名列表。"""
        if not _SOUNDCARD_OK:
            return []
        names = []
        try:
            for m in sc.all_microphones(include_loopback=True):
                # soundcard 回环设备名通常含 "Loopback"
                if getattr(m, "isloopback", False) or "loopback" in str(m).lower():
                    names.append(str(m))
        except Exception:
            pass
        # 去重保序
        seen = set()
        out = []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out

    @staticmethod
    def available() -> bool:
        return _SOUNDCARD_OK

    # ---- 启停 ----
    def start(self) -> None:
        if self._running:
            return
        if not _SOUNDCARD_OK:
            raise RuntimeError(
                "soundcard 未安装或初始化失败，请 `pip install soundcard`。"
            )
        self._running = True
        # 清空旧数据
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._running

    # ---- 内部录制循环 ----
    def _run(self) -> None:
        print("[DEBUG] AudioCapture._run() 开始", flush=True)
        # Windows WASAPI loopback 依赖 COM，每个线程必须初始化
        com_ok = False
        if sys.platform == "win32":
            try:
                import ctypes.wintypes
                _CoInitializeEx = ctypes.windll.ole32.CoInitializeEx
                _CoUninitialize = ctypes.windll.ole32.CoUninitialize
                COINIT_MULTITHREADED = 0
                print("[DEBUG] 初始化 COM (MTA)...", flush=True)
                _CoInitializeEx(None, COINIT_MULTITHREADED)
                com_ok = True
                print("[DEBUG] COM 初始化完成", flush=True)
            except Exception as e:
                print(f"[DEBUG] COM 初始化失败: {e}", flush=True)

        blocksize = int(self.sample_rate * self.block_ms / 1000)
        try:
            print("[DEBUG] 打开音频设备...", flush=True)
            mic = self._open_device()
            print(f"[DEBUG] 音频设备已打开: {mic}", flush=True)
            with mic.recorder(samplerate=self.sample_rate,
                              channels=1, blocksize=blocksize) as rec:
                while self._running:
                    data = rec.record(numframes=blocksize)
                    # soundcard 返回 shape=(blocksize,1) 或 (blocksize,)
                    arr = np.asarray(data, dtype=np.float32).reshape(-1)
                    try:
                        self.queue.put(arr, timeout=1)
                    except queue.Full:
                        # 消费慢了，丢最旧的一帧
                        try:
                            self.queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self.queue.put_nowait(arr)
                        except queue.Full:
                            pass
        except Exception as e:
            # 把错误塞进队列让上层感知
            self.queue.put({"error": str(e)})
        finally:
            if com_ok:
                try:
                    _CoUninitialize()
                except Exception:
                    pass

    def _open_device(self):
        if self.device_name:
            # 按名称精确或包含匹配
            for m in sc.all_microphones(include_loopback=True):
                if self.device_name in str(m):
                    return m
        # 默认：取第一个回环设备
        devs = sc.all_microphones(include_loopback=True)
        loopbacks = [m for m in devs
                     if getattr(m, "isloopback", False)
                     or "loopback" in str(m).lower()]
        if not loopbacks:
            raise RuntimeError("未找到任何系统音频回环设备。")
        return loopbacks[0]

    def read(self, timeout: float | None = None) -> np.ndarray | None:
        """阻塞读取一个音频块；超时返回 None。"""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None
