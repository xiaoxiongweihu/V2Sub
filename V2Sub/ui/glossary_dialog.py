"""术语增删改查对话框：表格 + 搜索 + 导入/导出（CSV/Excel）。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QHeaderView,
    QAbstractItemView, QInputDialog,
)

from core.glossary import Glossary


class GlossaryDialog(QDialog):
    def __init__(self, glossary: Glossary, parent=None) -> None:
        super().__init__(parent)
        self.gl = glossary
        self.setWindowTitle("专业术语表")
        self.resize(640, 520)
        self._build()
        self._reload()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel("术语会自动注入翻译提示，确保专业词汇译文一致。"
                      "右键表格行可编辑/删除。")
        info.setWordWrap(True)
        layout.addWidget(info)

        # 搜索 + 导入导出
        top = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索术语…")
        self.ed_search.textChanged.connect(self._reload)
        self.btn_import = QPushButton("导入")
        self.btn_import.clicked.connect(self._import)
        self.btn_export = QPushButton("导出")
        self.btn_export.clicked.connect(self._export)
        top.addWidget(QLabel("🔍"))
        top.addWidget(self.ed_search, 1)
        top.addWidget(self.btn_import)
        top.addWidget(self.btn_export)
        layout.addLayout(top)

        # 表格
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["源词 (原文)", "译词 (目标)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table, 1)

        # 操作按钮
        bottom = QHBoxLayout()
        self.btn_add = QPushButton("➕ 新增")
        self.btn_add.clicked.connect(self._add)
        self.btn_del = QPushButton("🗑 删除")
        self.btn_del.clicked.connect(self._delete)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear)
        self.lbl_count = QLabel()
        bottom.addWidget(self.btn_add)
        bottom.addWidget(self.btn_del)
        bottom.addWidget(self.btn_clear)
        bottom.addStretch()
        bottom.addWidget(self.lbl_count)
        layout.addLayout(bottom)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

    def _reload(self) -> None:
        kw = self.ed_search.text().strip()
        results = self.gl.search(kw)
        self.table.blockSignals(True)
        self.table.setRowCount(len(results))
        for row, (idx, e) in enumerate(results):
            s = QTableWidgetItem(e["source"])
            t = QTableWidgetItem(e["target"])
            s.setData(Qt.UserRole, idx)
            self.table.setItem(row, 0, s)
            self.table.setItem(row, 1, t)
        self.table.blockSignals(False)
        self.lbl_count.setText(f"共 {len(self.gl)} 条" +
                               (f"，匹配 {len(results)} 条" if kw else ""))

    def _add(self) -> None:
        s, ok = QInputDialog.getText(self, "新增术语", "源词（原文）：")
        if not ok or not s.strip():
            return
        t, ok = QInputDialog.getText(self, "新增术语", "译词（目标）：")
        if not ok:
            return
        self.gl.add(s, t)
        self._reload()

    def _delete(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            idx = self.table.item(r, 0).data(Qt.UserRole)
            self.gl.remove(idx)
        self._reload()

    def _clear(self) -> None:
        if QMessageBox.question(self, "确认", "清空所有术语？") == QMessageBox.Yes:
            self.gl.clear()
            self._reload()

    def _on_cell_changed(self, row, col) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        idx = item.data(Qt.UserRole)
        if idx is None:
            return
        s = self.table.item(row, 0).text().strip()
        t = self.table.item(row, 1).text().strip() if self.table.item(row, 1) else ""
        if s:
            self.gl.update(idx, s, t)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入术语", "", "术语文件 (*.csv *.xlsx)")
        if not path:
            return
        try:
            n = self.gl.import_file(path, merge=True)
            QMessageBox.information(self, "导入完成", f"已导入 {n} 条术语。")
            self._reload()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def _export(self) -> None:
        if len(self.gl) == 0:
            QMessageBox.information(self, "提示", "术语表为空。")
            return
        path, sel = QFileDialog.getSaveFileName(
            self, "导出术语", "glossary", "CSV (*.csv);;Excel (*.xlsx)")
        if not path:
            return
        try:
            if path.lower().endswith(".xlsx"):
                n = self.gl.export_excel(path)
            else:
                n = self.gl.export_csv(path)
            QMessageBox.information(self, "导出完成", f"已导出 {n} 条术语。")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
