"""实时语音翻译字幕 - 程序入口。

流程：系统音频 → faster-whisper 转写 → OpenAI 兼容大模型翻译 → 透明悬浮窗显示。
"""
import sys
import os

# 确保当前目录在 sys.path，便于包导入（core/ui）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _setup_cuda_dlls() -> None:
    """把 pip 安装的 CUDA 12 运行时 DLL 加入搜索路径。

    ctranslate2(GPU)/faster-whisper 需要 cublas64_12.dll 等，而 pip 装的
    nvidia-*-cu12 包默认不在系统 PATH 里。必须在 import 任何 CUDA 依赖前完成。
    无 nvidia 包时静默跳过（CPU 模式不受影响）。
    """
    import glob
    for path in (sys.prefix, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv")):
        base = os.path.join(path, "Lib", "site-packages", "nvidia")
        if not os.path.isdir(base):
            continue
        dll_dirs = []
        for r, _ds, _fs in os.walk(base):
            if glob.glob(os.path.join(r, "*.dll")):
                dll_dirs.append(r)
        for d in dll_dirs:
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(d)
            except OSError:
                pass


_setup_cuda_dlls()
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# ⚠️ 必须在 PyQt5 之前导入 faster_whisper/ctranslate2，否则 Qt5 DLL 与
# ctranslate2 的 DLL 加载顺序冲突，导致 0xC0000005 内存访问违规崩溃。
from core.transcriber import Transcriber  # noqa: E402

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# 高 DPI 支持
try:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
except Exception:
    pass


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("实时语音翻译字幕")
    app.setQuitOnLastWindowClosed(False)  # 由托盘控制退出

    # 全局未捕获异常钩子：确保 Python 层异常能以消息框显示，而非静默退出
    def _exception_hook(exc_type, exc_value, exc_tb):
        import traceback
        from PyQt5.QtWidgets import QMessageBox
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        QMessageBox.critical(None, "未捕获异常", msg)
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _exception_hook

    # 延迟导入，让上面 sys.path 调整生效
    from ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
