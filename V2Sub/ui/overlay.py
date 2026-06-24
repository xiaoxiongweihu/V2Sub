"""透明置顶悬浮字幕窗。

特性：
- 无边框 + 始终置顶 + 半透明圆角背景
- 拖拽边缘自由调整大小；拖动中间移动窗口
- Windows 下 ctypes 实现"鼠标穿透"（点击穿透到下层窗口/视频）
- 双击切换穿透模式；滚轮调透明度；右键菜单
- 最近 N 条字幕滚动显示，原文行小字灰、译文行大字白
"""
from __future__ import annotations

from collections import deque
from enum import IntEnum

from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPainterPath, QBrush, QCursor,
)
from PyQt5.QtWidgets import QWidget, QMenu, QAction, QDesktopWidget

from config import Config

try:
    import ctypes
    _WIN = True
except Exception:
    _WIN = False


# Windows 扩展样式常量
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

# WM_NCHITTEST 返回值（Windows 原生 resize）
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
HTCLIENT = 1
WM_NCHITTEST = 0x0084


class _Edge(IntEnum):
    NONE = 0
    LEFT = 1
    RIGHT = 2
    TOP = 3
    BOTTOM = 4
    TOPLEFT = 5
    TOPRIGHT = 6
    BOTTOMLEFT = 7
    BOTTOMRIGHT = 8


_resize_margin = 6  # 边缘拖拽调整大小的检测宽度（像素）


def _edge_from_pos(pos: QPoint, w: int, h: int) -> _Edge:
    """根据鼠标位置判断在哪个边缘/角落。"""
    x, y = pos.x(), pos.y()
    m = _resize_margin
    on_left = x < m
    on_right = x > w - m
    on_top = y < m
    on_bottom = y > h - m
    if on_top and on_left:
        return _Edge.TOPLEFT
    if on_top and on_right:
        return _Edge.TOPRIGHT
    if on_bottom and on_left:
        return _Edge.BOTTOMLEFT
    if on_bottom and on_right:
        return _Edge.BOTTOMRIGHT
    if on_left:
        return _Edge.LEFT
    if on_right:
        return _Edge.RIGHT
    if on_top:
        return _Edge.TOP
    if on_bottom:
        return _Edge.BOTTOM
    return _Edge.NONE


_CURSOR_MAP = {
    _Edge.LEFT: Qt.SizeHorCursor,
    _Edge.RIGHT: Qt.SizeHorCursor,
    _Edge.TOP: Qt.SizeVerCursor,
    _Edge.BOTTOM: Qt.SizeVerCursor,
    _Edge.TOPLEFT: Qt.SizeFDiagCursor,
    _Edge.BOTTOMRIGHT: Qt.SizeFDiagCursor,
    _Edge.TOPRIGHT: Qt.SizeBDiagCursor,
    _Edge.BOTTOMLEFT: Qt.SizeBDiagCursor,
}


class OverlayWindow(QWidget):
    """透明悬浮字幕窗。"""

    toggle_requested = pyqtSignal()  # 右键菜单"开始/停止"触发
    geometry_changed = pyqtSignal()  # 窗口移动/调整大小后触发

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 显示参数
        self.opacity = 0.75          # 背景不透明度
        self.font_size = 22          # 译文字号
        self.show_original = True    # 是否显示原文行
        self.max_lines = 3           # 最多显示几条
        self._click_through = False  # 鼠标穿透开关

        # 字幕缓冲：每条 (original, translated, failed?)
        self._lines: deque[tuple[str, str, bool]] = deque(maxlen=self.max_lines)

        # 窗口默认大小与位置
        self.resize(720, 140)
        self.setMinimumSize(200, 60)
        self._first_show = True      # 首次显示时自动居中

        # 拖拽状态
        self._drag_offset: QPoint | None = None
        self._resize_edge: _Edge = _Edge.NONE
        self._resize_start_geom: QRect | None = None  # 开始 resize 时的窗口几何
        self._resize_start_pos: QPoint | None = None  # 开始 resize 时的全局鼠标位置

        # 允许鼠标追踪（用于边缘检测时切换光标）
        self.setMouseTracking(True)

        # 持久化：从配置恢复上次位置与大小
        self.cfg = Config.instance()
        self.restore_geometry()

    # ---- 鼠标穿透 ----
    def set_click_through(self, enabled: bool) -> None:
        self._click_through = enabled
        if not _WIN:
            return
        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
            style |= WS_EX_LAYERED
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    @property
    def click_through(self) -> bool:
        return self._click_through

    # ---- Windows 原生 resize 支持 ----
    def nativeEvent(self, event_type, message):
        """拦截 WM_NCHITTEST，实现无边框窗口的边缘 resize。"""
        if not _WIN or self._click_through:
            return False, 0
        if event_type == "windows_generic_MSG":
            # message 是 sip.voidptr，需通过 ctypes 转换为 MSG 结构体
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_NCHITTEST:
                # 从 lParam 提取屏幕坐标（低16位=x，高16位=y，有符号）
                lp = msg.lParam
                x = lp & 0xFFFF
                y = (lp >> 16) & 0xFFFF
                if x > 0x7FFF:
                    x -= 0x10000
                if y > 0x7FFF:
                    y -= 0x10000
                local = self.mapFromGlobal(QPoint(x, y))
                edge = _edge_from_pos(local, self.width(), self.height())
                ht_map = {
                    _Edge.LEFT: HTLEFT,
                    _Edge.RIGHT: HTRIGHT,
                    _Edge.TOP: HTTOP,
                    _Edge.BOTTOM: HTBOTTOM,
                    _Edge.TOPLEFT: HTTOPLEFT,
                    _Edge.TOPRIGHT: HTTOPRIGHT,
                    _Edge.BOTTOMLEFT: HTBOTTOMLEFT,
                    _Edge.BOTTOMRIGHT: HTBOTTOMRIGHT,
                }
                if edge in ht_map:
                    return True, ht_map[edge]
        return False, 0

    # ---- 字幕接口 ----
    def add_subtitle(self, original: str, translated: str,
                     failed: bool = False) -> None:
        if not original and not translated:
            return
        self._lines.append((original, translated, failed))
        # 容量随 max_lines 变化
        if self._lines.maxlen != self.max_lines:
            self._lines = deque(self._lines, maxlen=self.max_lines)
        self.update()

    def clear(self) -> None:
        self._lines.clear()
        self.update()

    def apply_style(self, opacity: float, font_size: int,
                    show_original: bool, max_lines: int) -> None:
        self.opacity = max(0.0, min(1.0, opacity))
        self.font_size = font_size
        self.show_original = show_original
        self.max_lines = max(1, max_lines)
        self._lines = deque(self._lines, maxlen=self.max_lines)
        self.update()

    # ---- 窗口自动居中 + 位置持久化 ----
    def center_on_screen(self) -> None:
        """将窗口水平居中、垂直放置于屏幕底部 1/8 处。"""
        screen = QDesktopWidget().availableGeometry(self)
        w, h = self.width(), self.height()
        x = screen.x() + (screen.width() - w) // 2
        y = screen.y() + screen.height() - h - screen.height() // 8
        self.move(max(screen.x(), x), max(screen.y(), y))

    def save_geometry(self) -> None:
        """将当前窗口位置和大小保存到配置。"""
        g = self.frameGeometry()
        self.cfg.set("overlay_x", g.x(), save=False)
        self.cfg.set("overlay_y", g.y(), save=False)
        self.cfg.set("overlay_width", g.width(), save=False)
        self.cfg.set("overlay_height", g.height(), save=True)

    def restore_geometry(self) -> None:
        """从配置恢复窗口位置和大小；未保存时自动居中。"""
        x = self.cfg.get("overlay_x", -1)
        y = self.cfg.get("overlay_y", -1)
        w = self.cfg.get("overlay_width", 720)
        h = self.cfg.get("overlay_height", 140)
        if x >= 0 and y >= 0:
            self.setGeometry(x, y, w, h)
            self._first_show = False  # 已有保存位置，不再自动居中

    def showEvent(self, event) -> None:
        """首次显示时自动居中。"""
        super().showEvent(event)
        if self._first_show:
            self.center_on_screen()
            self._first_show = False

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        radius = 14
        # 圆角背景
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(w), float(h), float(radius), float(radius))
        p.setClipPath(path)
        bg = QColor(20, 20, 24, int(255 * self.opacity))
        p.fillPath(path, QBrush(bg))

        if not self._lines:
            p.end()
            return

        # 文字排版：从下往上画，最新一条在最底部
        margin = 16
        p.setPen(Qt.white)
        y = h - margin

        font_orig = QFont("Microsoft YaHei", max(10, self.font_size - 8))

        lines = list(self._lines)
        visual_count = 0  # 已绘制的视觉行数（原文+译文各算1行）

        # 倒序画：最后一行（最新）先画在底部
        for i in range(len(lines) - 1, -1, -1):
            original, translated, failed = lines[i]
            is_latest = (i == len(lines) - 1)

            # 译文行（最新一行更大）
            size = self.font_size if is_latest else max(12, self.font_size - 6)
            font = QFont("Microsoft YaHei", size, QFont.Medium)
            p.setFont(font)
            p.setPen(QColor(255, 80, 80) if failed else QColor(255, 255, 255))
            text = translated if translated else original
            if not text:
                continue
            rect = p.boundingRect(QRect(margin, 0, w - 2 * margin, 0),
                                  Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop,
                                  text)
            y -= rect.height()
            p.drawText(QRect(margin, y, w - 2 * margin, rect.height()),
                       Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop, text)
            visual_count += 1
            if visual_count >= self.max_lines:
                break

            # 原文行（仅最新一条的译文下方显示）
            if self.show_original and original and is_latest:
                p.setFont(font_orig)
                p.setPen(QColor(180, 180, 190))
                rect_o = p.boundingRect(QRect(margin, 0, w - 2 * margin, 0),
                                        Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop,
                                        original)
                y -= rect_o.height() + 4
                p.drawText(QRect(margin, y, w - 2 * margin, rect_o.height()),
                           Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop, original)
                visual_count += 1
                if visual_count >= self.max_lines:
                    break

            if y < margin:
                break
            y -= 8

        p.end()

    # ---- 鼠标交互 ----
    def _update_cursor(self, pos: QPoint) -> None:
        """根据鼠标位置更新光标样式。"""
        if self._click_through or self._drag_offset is not None:
            return
        edge = _edge_from_pos(pos, self.width(), self.height())
        cur = _CURSOR_MAP.get(edge)
        if cur is not None:
            self.setCursor(QCursor(cur))
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))

    def mousePressEvent(self, event) -> None:
        if self._click_through:
            return
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            edge = _edge_from_pos(pos, self.width(), self.height())
            if edge != _Edge.NONE:
                # 开始 resize
                self._resize_edge = edge
                self._resize_start_geom = self.frameGeometry()
                self._resize_start_pos = event.globalPos()
                event.accept()
                return
            # 开始拖动移动
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._click_through:
            return
        pos = event.pos()

        # 正在 resize
        if self._resize_edge != _Edge.NONE and self._resize_start_geom is not None:
            delta = event.globalPos() - self._resize_start_pos
            g = QRect(self._resize_start_geom)
            mw = self.minimumWidth()
            mh = self.minimumHeight()
            edge = self._resize_edge

            if edge in (_Edge.LEFT, _Edge.TOPLEFT, _Edge.BOTTOMLEFT):
                g.setLeft(min(g.left() + delta.x(), g.right() - mw))
            if edge in (_Edge.RIGHT, _Edge.TOPRIGHT, _Edge.BOTTOMRIGHT):
                g.setRight(max(g.right() + delta.x(), g.left() + mw))
            if edge in (_Edge.TOP, _Edge.TOPLEFT, _Edge.TOPRIGHT):
                g.setTop(min(g.top() + delta.y(), g.bottom() - mh))
            if edge in (_Edge.BOTTOM, _Edge.BOTTOMLEFT, _Edge.BOTTOMRIGHT):
                g.setBottom(max(g.bottom() + delta.y(), g.top() + mh))

            self.setGeometry(g)
            event.accept()
            return

        # 正在拖动移动
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)
            event.accept()
            return

        # 鼠标移动时更新光标
        self._update_cursor(pos)

    def mouseReleaseEvent(self, event) -> None:
        changed = self._resize_edge != _Edge.NONE or self._drag_offset is not None
        if self._resize_edge != _Edge.NONE:
            self._resize_edge = _Edge.NONE
            self._resize_start_geom = None
            self._resize_start_pos = None
        self._drag_offset = None
        if changed:
            self.save_geometry()

    def mouseDoubleClickEvent(self, event) -> None:
        # 双击切换穿透
        self.set_click_through(not self._click_through)

    def leaveEvent(self, event) -> None:
        """鼠标离开窗口时恢复默认光标。"""
        self.setCursor(QCursor(Qt.ArrowCursor))

    def wheelEvent(self, event) -> None:
        # 滚轮调透明度
        if self._click_through:
            return
        delta = event.angleDelta().y() / 1200.0
        self.opacity = max(0.2, min(1.0, self.opacity + delta))
        self.update()

    def contextMenuEvent(self, event) -> None:
        if self._click_through:
            return
        menu = QMenu(self)
        act_toggle_ct = QAction("关闭鼠标穿透" if self._click_through else "开启鼠标穿透",
                                self)
        act_toggle_ct.triggered.connect(
            lambda: self.set_click_through(not self._click_through))
        menu.addAction(act_toggle_ct)

        act_center = QAction("居中显示", self)
        act_center.triggered.connect(self.center_on_screen)
        menu.addAction(act_center)

        act_run = QAction("开始/停止翻译", self)
        act_run.triggered.connect(self.toggle_requested.emit)
        menu.addAction(act_run)

        menu.addSeparator()
        act_clear = QAction("清空字幕", self)
        act_clear.triggered.connect(self.clear)
        menu.addAction(act_clear)

        act_hide = QAction("隐藏悬浮窗", self)
        act_hide.triggered.connect(self.hide)
        menu.addAction(act_hide)

        menu.exec_(event.globalPos())
