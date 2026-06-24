"""设置对话框：API / Whisper / 翻译 / 音频 / VAD / 悬浮窗。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QGroupBox,
    QMessageBox, QSlider, QFileDialog,
)

from config import Config
from core.translator import Translator
from core.audio_capture import AudioCapture
from core.transcriber import Transcriber


LANGS = ["中文", "English", "日本語", "한국어", "Français", "Deutsch",
         "Español", "Русский", "العربية", "Português"]
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("设置")
        self.resize(560, 620)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        # --- API ---
        gb_api = QGroupBox("AI 翻译（OpenAI 兼容接口）")
        f_api = QFormLayout(gb_api)
        self.ed_base = QLineEdit()
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-...")
        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)
        self.cb_model.addItems(["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo",
                                "deepseek-chat", "moonshot-v1-8k"])
        self.cb_target = QComboBox()
        self.cb_target.addItems(LANGS)
        self.sp_temp = QDoubleSpinBox()
        self.sp_temp.setRange(0.0, 1.0)
        self.sp_temp.setSingleStep(0.1)
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test)
        f_api.addRow("Base URL:", self.ed_base)
        f_api.addRow("API Key:", self.ed_key)
        f_api.addRow("模型:", self.cb_model)
        f_api.addRow("目标语言:", self.cb_target)
        f_api.addRow("温度:", self.sp_temp)
        f_api.addRow("", self.btn_test)
        layout.addWidget(gb_api)

        # --- Whisper ---
        gb_wh = QGroupBox("Whisper 语音识别（本地）")
        f_wh = QFormLayout(gb_wh)
        self.cb_model_wh = QComboBox()
        self.cb_model_wh.addItems(WHISPER_MODELS)
        self.cb_device = QComboBox()
        self.cb_device.addItems(["auto", "cpu", "cuda"])
        self.cb_ct = QComboBox()
        self.cb_ct.addItems(["auto", "int8", "int8_float16", "float16", "float32"])
        self.cb_src = QComboBox()
        self.cb_src.setEditable(True)
        self.cb_src.addItems(["auto", "en", "zh", "ja", "ko", "fr", "de", "es"])
        f_wh.addRow("模型:", self.cb_model_wh)
        # 本地模型路径
        path_row = QHBoxLayout()
        self.ed_model_path = QLineEdit()
        self.ed_model_path.setPlaceholderText("留空=自动下载，或填入本地模型目录路径")
        self.btn_browse_model = QPushButton("浏览...")
        self.btn_browse_model.clicked.connect(self._browse_model_path)
        path_row.addWidget(self.ed_model_path)
        path_row.addWidget(self.btn_browse_model)
        f_wh.addRow("本地路径:", path_row)
        f_wh.addRow("设备:", self.cb_device)
        f_wh.addRow("计算精度:", self.cb_ct)
        f_wh.addRow("源语言:", self.cb_src)
        layout.addWidget(gb_wh)

        # --- 音频 + VAD ---
        gb_au = QGroupBox("音频采集 与 分段")
        f_au = QFormLayout(gb_au)
        self.cb_dev = QComboBox()
        self._refresh_devices()
        self.sp_thr = QDoubleSpinBox()
        self.sp_thr.setRange(0.001, 0.2)
        self.sp_thr.setSingleStep(0.001)
        self.sp_thr.setDecimals(3)
        self.sp_silence = QDoubleSpinBox()
        self.sp_silence.setRange(0.1, 3.0)
        self.sp_silence.setSingleStep(0.05)
        self.sp_silence.setSuffix(" 秒")
        self.sp_min = QDoubleSpinBox()
        self.sp_min.setRange(0.1, 3.0)
        self.sp_min.setSingleStep(0.1)
        self.sp_min.setSuffix(" 秒")
        self.sp_max = QDoubleSpinBox()
        self.sp_max.setRange(3.0, 60.0)
        self.sp_max.setSingleStep(1.0)
        self.sp_max.setSuffix(" 秒")
        self.btn_refresh = QPushButton("刷新设备")
        self.btn_refresh.clicked.connect(self._refresh_devices)
        f_au.addRow("系统音频设备:", self.cb_dev)
        f_au.addRow("", self.btn_refresh)
        f_au.addRow("静音阈值(RMS):", self.sp_thr)
        f_au.addRow("静音时长切段:", self.sp_silence)
        f_au.addRow("最小语段:", self.sp_min)
        f_au.addRow("最大语段:", self.sp_max)
        layout.addWidget(gb_au)

        # --- 悬浮窗 ---
        gb_ov = QGroupBox("悬浮窗")
        f_ov = QFormLayout(gb_ov)
        self.sl_op = QSlider(Qt.Horizontal)
        self.sl_op.setRange(20, 100)
        self.lbl_op = QLabel()
        self.sl_op.valueChanged.connect(
            lambda v: self.lbl_op.setText(f"{v}%"))
        self.sp_font = QSpinBox()
        self.sp_font.setRange(10, 48)
        self.sp_font.setSuffix(" pt")
        self.chk_orig = QCheckBox("显示原文行")
        self.sp_lines = QSpinBox()
        self.sp_lines.setRange(1, 6)
        layout_ov = QHBoxLayout()
        layout_ov.addWidget(self.sl_op)
        layout_ov.addWidget(self.lbl_op)
        f_ov.addRow("背景不透明度:", layout_ov)
        f_ov.addRow("译文字号:", self.sp_font)
        f_ov.addRow("", self.chk_orig)
        f_ov.addRow("最多显示行数:", self.sp_lines)
        layout.addWidget(gb_ov)

        # --- 按钮 ---
        btns = QHBoxLayout()
        self.btn_ok = QPushButton("保存")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)

    def _refresh_devices(self) -> None:
        self.cb_dev.clear()
        self.cb_dev.addItem("（默认回环设备）", "")
        for name in AudioCapture.list_loopback_devices():
            self.cb_dev.addItem(name, name)

    def _browse_model_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 Whisper 模型目录")
        if path:
            self.ed_model_path.setText(path)

    def _load(self) -> None:
        c = self.cfg
        self.ed_base.setText(c.get("api_base_url", ""))
        self.ed_key.setText(c.get("api_key", ""))
        self.cb_model.setEditText(c.get("llm_model", "gpt-4o-mini"))
        self.cb_target.setCurrentText(c.get("target_language", "中文"))
        self.sp_temp.setValue(c.get("translation_temperature", 0.3))
        self.cb_model_wh.setCurrentText(c.get("whisper_model", "small"))
        self.ed_model_path.setText(c.get("whisper_model_path", ""))
        self.cb_device.setCurrentText(c.get("whisper_device", "auto"))
        self.cb_ct.setCurrentText(c.get("whisper_compute_type", "auto"))
        self.cb_src.setCurrentText(c.get("source_language", "auto"))
        # 音频设备
        target = c.get("audio_device", "")
        idx = self.cb_dev.findData(target)
        self.cb_dev.setCurrentIndex(idx if idx >= 0 else 0)
        self.sp_thr.setValue(c.get("vad_threshold", 0.012))
        self.sp_silence.setValue(c.get("vad_silence_duration", 0.45))
        self.sp_min.setValue(c.get("vad_min_segment", 0.5))
        self.sp_max.setValue(c.get("vad_max_segment", 15.0))
        self.sl_op.setValue(int(c.get("overlay_opacity", 0.75) * 100))
        self.lbl_op.setText(f"{self.sl_op.value()}%")
        self.sp_font.setValue(c.get("overlay_font_size", 22))
        self.chk_orig.setChecked(c.get("show_original", True))
        self.sp_lines.setValue(c.get("overlay_max_lines", 3))

    def accept(self) -> None:
        c = self.cfg
        c.update({
            "api_base_url": self.ed_base.text().strip(),
            "api_key": self.ed_key.text().strip(),
            "llm_model": self.cb_model.currentText().strip(),
            "target_language": self.cb_target.currentText(),
            "translation_temperature": self.sp_temp.value(),
            "whisper_model": self.cb_model_wh.currentText(),
            "whisper_model_path": self.ed_model_path.text().strip(),
            "whisper_device": self.cb_device.currentText(),
            "whisper_compute_type": self.cb_ct.currentText(),
            "source_language": self.cb_src.currentText(),
            "audio_device": self.cb_dev.currentData() or "",
            "vad_threshold": self.sp_thr.value(),
            "vad_silence_duration": self.sp_silence.value(),
            "vad_min_segment": self.sp_min.value(),
            "vad_max_segment": self.sp_max.value(),
            "overlay_opacity": self.sl_op.value() / 100.0,
            "overlay_font_size": self.sp_font.value(),
            "show_original": self.chk_orig.isChecked(),
            "overlay_max_lines": self.sp_lines.value(),
        })
        super().accept()

    def _test(self) -> None:
        t = Translator(
            base_url=self.ed_base.text().strip(),
            api_key=self.ed_key.text().strip(),
            model=self.cb_model.currentText().strip(),
            target_language=self.cb_target.currentText(),
        )
        self.btn_test.setEnabled(False)
        self.btn_test.setText("测试中...")
        ok, msg = t.test_connection()
        self.btn_test.setEnabled(True)
        self.btn_test.setText("测试连接")
        if ok:
            QMessageBox.information(self, "成功", msg)
        else:
            QMessageBox.warning(self, "失败", msg)
