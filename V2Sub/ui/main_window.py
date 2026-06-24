"""主控窗口：编排音频→转写→翻译流水线，管理悬浮窗/设置/术语/历史。

流水线用 3 个 QThread 串行解耦：
  AudioWorker（采集+分段） → TranscribeWorker（转写） → TranslateWorker（翻译）
通过 Qt 信号在主线程安全更新 UI。
"""
from __future__ import annotations

import threading
import time

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QIcon, QPixmap, QColor, QPainter, QBrush
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QStatusBar, QMessageBox, QSystemTrayIcon, QMenu, QAction,
    QSplitter, QFrame,
)

from config import Config
from core.audio_capture import AudioCapture
from core.segmenter import Segmenter
from core.transcriber import Transcriber
from core.translator import Translator
from core.glossary import Glossary
from ui.overlay import OverlayWindow


def _make_tray_icon() -> QIcon:
    """程序化生成一个托盘图标（绿色圆形 + 白色麦克风符号），无需 .ico 文件。"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    # 绿色圆底
    p.setBrush(QBrush(QColor("#2196F3")))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 60, 60)
    # 白色麦克风符号 🎙
    p.setBrush(QBrush(Qt.white))
    p.drawRoundedRect(24, 18, 16, 24, 8, 8)
    p.drawRoundedRect(20, 36, 24, 8, 4, 4)
    p.end()
    return QIcon(pixmap)


# ---------- 工作线程 ----------

class AudioWorker(QObject):
    """采集系统音频 + VAD 分段，产出完整语段（numpy）。"""
    segment_ready = pyqtSignal(object)   # np.ndarray
    error = pyqtSignal(str)
    level = pyqtSignal(float)            # 当前能量等级

    def __init__(self, cfg: Config, seg: Segmenter) -> None:
        super().__init__()
        self.cfg = cfg
        self.seg = seg
        self._running = False
        self._cap: AudioCapture | None = None

    def start(self) -> None:
        print("[DEBUG] AudioWorker.start() 开始", flush=True)
        self._running = True
        try:
            print("[DEBUG] 创建 AudioCapture...", flush=True)
            self._cap = AudioCapture(
                sample_rate=self.cfg.get("sample_rate", 16000),
                device_name=self.cfg.get("audio_device") or None,
                block_ms=100,
            )
            print("[DEBUG] 启动 AudioCapture...", flush=True)
            self._cap.start()
            print("[DEBUG] AudioCapture 已启动", flush=True)
        except Exception as e:
            self.error.emit(f"音频采集启动失败: {e}")
            self._running = False
            return
        # 采集循环
        while self._running:
            chunk = self._cap.read(timeout=0.3)
            if chunk is None:
                continue
            if isinstance(chunk, dict) and "error" in chunk:
                self.error.emit(str(chunk["error"]))
                break
            # 能量指示
            import numpy as np
            rms = float((np.asarray(chunk) ** 2).mean() ** 0.5)
            self.level.emit(rms)
            # 分段
            for seg_audio in self.seg.feed(chunk):
                self.segment_ready.emit(seg_audio)
        # 停止：吐出残余缓冲
        tail = self.seg.flush()
        if tail is not None and tail.size >= int(self.seg.min_segment * self.seg.sample_rate):
            self.segment_ready.emit(tail)
        if self._cap:
            self._cap.stop()

    def stop(self) -> None:
        self._running = False


class TranscribeWorker(QObject):
    """消费语段，faster-whisper 转写，产出文本。"""
    text_ready = pyqtSignal(str, object)  # (text, audio_ref)
    error = pyqtSignal(str)
    loaded = pyqtSignal(str)              # 模型加载完成（设备信息）

    def __init__(self, transcriber: Transcriber) -> None:
        super().__init__()
        self.tr = transcriber
        self._running = False
        from queue import Queue
        self._q: "Queue" = Queue()

    def submit(self, audio) -> None:
        self._q.put(audio)

    def start(self) -> None:
        print("[DEBUG] TranscribeWorker.start() 开始", flush=True)
        self._running = True
        try:
            print("[DEBUG] 加载 Whisper 模型 (TranscribeWorker)...", flush=True)
            self.tr.load()
            print("[DEBUG] Whisper 模型加载完成 (TranscribeWorker)", flush=True)
            self.loaded.emit(f"{self.tr.model_size} @ {self.tr.device}({self.tr.compute_type})")
        except Exception as e:
            self.error.emit(f"模型加载失败: {e}")
            return
        from queue import Empty
        while self._running:
            try:
                audio = self._q.get(timeout=0.5)
            except Empty:
                continue
            try:
                text = self.tr.transcribe(audio)
                if text:
                    self.text_ready.emit(text, audio)
            except Exception as e:
                self.error.emit(f"转写失败: {e}")

    def stop(self) -> None:
        self._running = False


class TranslateWorker(QObject):
    """消费转写文本，调用大模型翻译，产出 (original, translated, failed)。"""
    result = pyqtSignal(str, str, bool)
    error = pyqtSignal(str)

    def __init__(self, translator: Translator, glossary: Glossary) -> None:
        super().__init__()
        self.tr = translator
        self.gl = glossary
        self._running = False
        from queue import Queue
        self._q: "Queue" = Queue()

    def submit(self, text: str) -> None:
        self._q.put(text)

    def start(self) -> None:
        self._running = True
        from queue import Empty
        while self._running:
            try:
                text = self._q.get(timeout=0.5)
            except Empty:
                continue
            errs: list[str] = []
            hint = self.gl.hint_string()
            translated = self.tr.translate(
                text, glossary_hint=hint,
                on_error=lambda m: errs.append(m))
            failed = bool(errs)
            if failed:
                self.error.emit(errs[-1])
            self.result.emit(text, translated, failed)

    def stop(self) -> None:
        self._running = False


# ---------- 主窗口 ----------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = Config.instance()
        self.glossary = Glossary()

        self.setWindowTitle("实时语音翻译字幕")
        self.resize(640, 560)

        self.overlay = OverlayWindow()

        self._build_ui()
        self._build_tray()
        self._apply_overlay_style()

        self.audio_thread: QThread | None = None
        self.audio_worker: AudioWorker | None = None
        self.trans_thread: QThread | None = None
        self.trans_worker: TranscribeWorker | None = None
        self.tl_thread: QThread | None = None
        self.tl_worker: TranslateWorker | None = None
        self._running = False

        # 启动时检查音频设备可用性并提示
        self._check_audio_devices()

        if self.cfg.get("auto_start_overlay", True):
            self.overlay.show()

    # ---- UI 构建 ----
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("🎙️ 实时语音翻译字幕")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        layout.addWidget(title)

        # 控制按钮行
        row = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始翻译")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.btn_start.clicked.connect(self.toggle_run)
        self.btn_overlay = QPushButton("👁 显示悬浮窗")
        self.btn_overlay.setMinimumHeight(36)
        self.btn_overlay.clicked.connect(self.toggle_overlay)
        self.btn_glossary = QPushButton("📖 术语表")
        self.btn_glossary.clicked.connect(self.open_glossary)
        self.btn_settings = QPushButton("⚙ 设置")
        self.btn_settings.clicked.connect(self.open_settings)
        for b in (self.btn_start, self.btn_overlay, self.btn_glossary, self.btn_settings):
            row.addWidget(b)
        layout.addLayout(row)

        # 电平指示 + 状态
        info = QHBoxLayout()
        self.lbl_level = QLabel("音量: ─")
        self.lbl_level.setMinimumWidth(140)
        self.lbl_status = QLabel("状态: 未启动")
        info.addWidget(self.lbl_level)
        info.addStretch()
        info.addWidget(self.lbl_status)
        layout.addLayout(info)

        # 字幕历史
        layout.addWidget(QLabel("字幕历史："))
        self.history = QListWidget()
        self.history.setWordWrap(True)
        layout.addWidget(self.history, 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪 — 请先在设置中配置 API Key 和音频设备")

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(_make_tray_icon(), self)
        self.tray.setToolTip("实时语音翻译字幕")
        menu = QMenu()
        act_show = QAction("显示主窗口", self)
        act_show.triggered.connect(self.showNormal)
        act_run = QAction("开始/停止", self)
        act_run.triggered.connect(self.toggle_run)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addAction(act_run)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.showNormal() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def _check_audio_devices(self) -> None:
        """启动时检查音频设备可用性，结果反映在状态栏。"""
        if not AudioCapture.available():
            self.statusBar().showMessage("⚠ soundcard 未安装，音频采集不可用", 10000)
            return
        devs = AudioCapture.list_loopback_devices()
        if devs:
            self.statusBar().showMessage(
                f"就绪 — 检测到 {len(devs)} 个音频回环设备，请配置后开始翻译", 8000)
        else:
            self.statusBar().showMessage(
                "⚠ 未检测到系统音频回环设备，请在设置中检查", 10000)

    # ---- 悬浮窗样式同步 ----
    def _apply_overlay_style(self) -> None:
        self.overlay.apply_style(
            opacity=self.cfg.get("overlay_opacity", 0.75),
            font_size=self.cfg.get("overlay_font_size", 22),
            show_original=self.cfg.get("show_original", True),
            max_lines=self.cfg.get("overlay_max_lines", 3),
        )

    # ---- 启停流水线 ----
    def toggle_run(self) -> None:
        if self._running:
            self.stop_pipeline()
        else:
            self.start_pipeline()

    def start_pipeline(self) -> None:
        # 校验 API
        if not self.cfg.get("api_key"):
            QMessageBox.warning(self, "提示", "请先在设置中配置翻译 API Key。")
            return
        try:
            transcriber = Transcriber(
                model_size=self.cfg.get("whisper_model", "small"),
                model_path=self.cfg.get("whisper_model_path", ""),
                device=self.cfg.get("whisper_device", "auto"),
                compute_type=self.cfg.get("whisper_compute_type", "auto"),
                language=self.cfg.get("source_language", "auto"),
            )
            translator = Translator(
                base_url=self.cfg.get("api_base_url"),
                api_key=self.cfg.get("api_key"),
                model=self.cfg.get("llm_model"),
                target_language=self.cfg.get("target_language", "中文"),
                temperature=self.cfg.get("translation_temperature", 0.3),
            )
        except Exception as e:
            QMessageBox.critical(self, "初始化失败", str(e))
            return

        # 在主线程中预加载 Whisper 模型，避免子线程中 CUDA 初始化导致 C++ 崩溃
        print("[DEBUG] 开始加载 Whisper 模型...", flush=True)
        try:
            transcriber.load()
            print("[DEBUG] Whisper 模型加载完成", flush=True)
        except Exception as e:
            QMessageBox.critical(self, "Whisper 模型加载失败", str(e))
            return

        print("[DEBUG] 创建 Segmenter...", flush=True)
        segmenter = Segmenter(
            sample_rate=self.cfg.get("sample_rate", 16000),
            threshold=self.cfg.get("vad_threshold", 0.012),
            silence_duration=self.cfg.get("vad_silence_duration", 0.45),
            min_segment=self.cfg.get("vad_min_segment", 0.5),
            max_segment=self.cfg.get("vad_max_segment", 15.0),
        )

        # 音频线程
        print("[DEBUG] 创建音频线程...", flush=True)
        self.audio_thread = QThread()
        self.audio_worker = AudioWorker(self.cfg, segmenter)
        self.audio_worker.moveToThread(self.audio_thread)
        self.audio_worker.segment_ready.connect(self._on_segment)
        self.audio_worker.level.connect(self._on_level)
        self.audio_worker.error.connect(self._on_error)
        self.audio_thread.started.connect(self.audio_worker.start)
        print("[DEBUG] 启动音频线程...", flush=True)
        self.audio_thread.start()
        print("[DEBUG] 音频线程已启动", flush=True)

        # 转写线程
        print("[DEBUG] 创建转写线程...", flush=True)
        self.trans_thread = QThread()
        self.trans_worker = TranscribeWorker(transcriber)
        self.trans_worker.moveToThread(self.trans_thread)
        self.trans_worker.text_ready.connect(self._on_transcribed)
        self.trans_worker.loaded.connect(
            lambda m: self.statusBar().showMessage(f"Whisper 已加载: {m}", 4000))
        self.trans_worker.error.connect(self._on_error)
        self.trans_thread.started.connect(self.trans_worker.start)
        print("[DEBUG] 启动转写线程...", flush=True)
        self.trans_thread.start()
        print("[DEBUG] 转写线程已启动", flush=True)

        # 翻译线程
        print("[DEBUG] 创建翻译线程...", flush=True)
        self.tl_thread = QThread()
        self.tl_worker = TranslateWorker(translator, self.glossary)
        self.tl_worker.moveToThread(self.tl_thread)
        self.tl_worker.result.connect(self._on_translated)
        self.tl_worker.error.connect(self._on_error)
        self.tl_thread.started.connect(self.tl_worker.start)
        print("[DEBUG] 启动翻译线程...", flush=True)
        self.tl_thread.start()
        print("[DEBUG] 翻译线程已启动", flush=True)

        self._running = True
        self.btn_start.setText("⏹ 停止翻译")
        self.btn_start.setStyleSheet(
            "font-size: 14px; font-weight: bold; background-color: #ff4444; color: white;")
        self.lbl_status.setText("状态: 运行中")
        self.statusBar().showMessage("翻译已开始，Whisper 正在加载模型…", 5000)
        if not self.overlay.isVisible():
            self.overlay.show()

    def stop_pipeline(self) -> None:
        for worker, thread in (
            (self.audio_worker, self.audio_thread),
            (self.trans_worker, self.trans_thread),
            (self.tl_worker, self.tl_thread),
        ):
            if worker:
                worker.stop()
            if thread:
                thread.quit()
                thread.wait(3000)
        self.audio_worker = self.audio_thread = None
        self.trans_worker = self.trans_thread = None
        self.tl_worker = self.tl_thread = None
        self._running = False
        self.btn_start.setText("▶ 开始翻译")
        self.btn_start.setStyleSheet(
            "font-size: 14px; font-weight: bold;")
        self.lbl_status.setText("状态: 已停止")
        self.lbl_level.setText("音量: ─")
        self.statusBar().showMessage("已停止", 3000)

    # ---- 信号槽 ----
    def _on_segment(self, audio) -> None:
        if self.trans_worker:
            self.trans_worker.submit(audio)

    def _on_transcribed(self, text, _audio) -> None:
        # 立即在悬浮窗占位（原文先显示），翻译完成后更新
        self.overlay.add_subtitle(text, "")
        if self.tl_worker:
            self.tl_worker.submit(text)

    def _on_translated(self, original, translated, failed) -> None:
        self.overlay.add_subtitle(original, translated, failed)
        tag = "[失败]" if failed else ""
        self.history.insertItem(0, f"{original}\n→ {translated} {tag}")

    def _on_level(self, rms: float) -> None:
        import math
        bar_count = min(20, int(rms / max(self.cfg.get("vad_threshold", 0.012), 1e-6) * 4))
        self.lbl_level.setText("音量: " + "█" * bar_count + "░" * (20 - bar_count))

    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"⚠ {msg}", 8000)

    # ---- 按钮 ----
    def toggle_overlay(self) -> None:
        if self.overlay.isVisible():
            self.overlay.hide()
            self.btn_overlay.setText("👁 显示悬浮窗")
        else:
            self.overlay.show()
            self.btn_overlay.setText("🙈 隐藏悬浮窗")

    def open_glossary(self) -> None:
        from ui.glossary_dialog import GlossaryDialog
        dlg = GlossaryDialog(self.glossary, self)
        dlg.exec_()

    def open_settings(self) -> None:
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec_():
            self.cfg.save()
            self._apply_overlay_style()

    # ---- 关闭 ----
    def closeEvent(self, event) -> None:
        if self._running:
            self.stop_pipeline()
        if self.tray.isVisible():
            self.hide()
            event.ignore()
            self.tray.showMessage("实时语音翻译字幕",
                                  "已最小化到托盘，双击图标恢复。")
        else:
            self._quit()
            event.accept()

    def _quit(self) -> None:
        if self._running:
            self.stop_pipeline()
        self.overlay.close()
        self.tray.hide()
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
