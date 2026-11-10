from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QUrl, QCoreApplication, QEvent
from PySide6.QtGui import QDesktopServices, QFont, QColor, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QProgressBar, QPlainTextEdit, QSizePolicy)

from . import __version__
from .media import EXTENSIONS, Cancelled, MediaError, MediaInfo, convert, inspect_media, parse_fps


STYLE = """
QWidget { background: #101714; color: #edf3ef; font-size: 13px; }
QLabel { background: transparent; }
QLabel#muted { color: #96aaa0; }
QLabel#brand { font-size: 18px; font-weight: 700; }
QLabel#hero { font-size: 30px; font-weight: 700; }
QLabel#section { font-weight: 600; font-size: 15px; }
QLabel#chip { color: #a3d8bd; background: #20372b; border-radius: 12px; padding: 6px 12px; }
QLabel#number { color: #b7f5cf; font-size: 32px; font-weight: 600; }
QFrame#card { background: #19231e; border: 1px solid #2b3d32; border-radius: 14px; }
QFrame#drop { background: #14231b; border: 1px dashed #527c61; border-radius: 12px; }
QFrame#separator { background: #2b3d32; border: none; }
QPushButton { background: #26392d; border: 1px solid #3b5143; border-radius: 8px; padding: 10px 16px; }
QPushButton:hover { background: #334c3c; border-color: #8ac8a0; }
QPushButton:pressed { background: #1c2e23; }
QPushButton:disabled { color: #688173; background: #202d25; border-color: #2b3d32; }
QPushButton#primary { background: #b7f5cf; color: #13251a; border: none; font-size: 15px; font-weight: 700; padding: 14px; }
QPushButton#primary:hover { background: #d0ffdf; }
QPushButton#primary:disabled { background: #385b44; color: #87a490; }
QPushButton#quiet { background: transparent; border: none; color: #a2b7aa; padding: 6px 10px; }
QComboBox { border: 1px solid #4c6957; border-radius: 9px; padding: 10px; background: #101a14; min-height: 28px; font-size: 23px; }
QComboBox QAbstractItemView { background: #203328; selection-background-color: #3d654b; font-size: 15px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QLineEdit { background: transparent; }
QTableWidget { background: #19231e; border: none; gridline-color: #2b3d32; selection-background-color: #284733; }
QTableWidget::item { padding: 10px 6px; border-bottom: 1px solid #2a3b30; }
QHeaderView::section { background: #19231e; color: #8fa99a; border: none; border-bottom: 1px solid #2b3d32; padding: 9px 6px; font-size: 11px; }
QTableCornerButton::section { background: #19231e; border: none; }
QProgressBar { background: #293b30; border: none; border-radius: 3px; height: 6px; color: transparent; }
QProgressBar::chunk { background: #b7f5cf; border-radius: 3px; }
QPlainTextEdit { background: #0c120f; color: #b4c7bb; border: 1px solid #3a4e41; border-radius: 8px; }
QScrollBar:vertical { width: 8px; background: #19231e; }
QScrollBar::handle:vertical { background: #4a6353; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #24392c; color: #edf3ef; border: 1px solid #527c61; padding: 8px; }
"""


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def seconds(value):
    return f"{float(value):.3f} 秒"


class Worker(QThread):
    result = Signal(int, object)
    error = Signal(int, str)
    update = Signal(str, float)

    def __init__(self, jobs, target=None, directory=None, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.target = target
        self.directory = directory
        self.cancel = threading.Event()

    def run(self):
        for position, (index, path) in enumerate(self.jobs):
            if self.cancel.is_set():
                break
            def progress(phase, value):
                self.update.emit(f"{position+1}/{len(self.jobs)} · {path.name} · {phase}",
                                 (position + value)/len(self.jobs))
            progress("正在读取" if self.target is None else "准备导出", 0)
            try:
                if self.target is None:
                    result = inspect_media(path, self.cancel, progress)
                else:
                    result = convert(path, self.target, self.directory or path.parent, self.cancel, progress)
                self.result.emit(index, result)
            except Cancelled:
                self.error.emit(index, "已取消")
                break
            except Exception as error:
                self.error.emit(index, str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("帧率小工具 · FPS Tools")
        self.resize(1080, 780)
        self.setMinimumSize(900, 700)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self.paths: list[Path] = []
        self.infos: dict[int, MediaInfo] = {}
        self.outputs: list[Path] = []
        self.output_dir: Path | None = None
        self.worker = None
        self.busy = False
        self._closing = False
        self._errors = 0
        base = QWidget()
        self.setCentralWidget(base)
        root = QVBoxLayout(base)
        root.setContentsMargins(30, 24, 30, 22)
        root.setSpacing(18)
        header = QHBoxLayout()
        header.addWidget(label("▥   FPS TOOLS", "brand"))
        header.addWidget(label(f"v{__version__}", "muted"))
        header.addStretch()
        header.addWidget(label("本地处理 · 无需联网", "chip"))
        root.addLayout(header)
        hero = QVBoxLayout()
        hero.setSpacing(9)
        hero.addWidget(label("换个帧率，每一帧都在。", "hero"))
        hero.addWidget(label("改变播放速度，保留原始画面。拖入视频，选择帧率，即可导出。", "muted"))
        root.addLayout(hero)
        content = QHBoxLayout()
        content.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(16)
        drop = QFrame()
        drop.setObjectName("drop")
        dropbox = QVBoxLayout(drop)
        dropbox.setContentsMargins(18, 20, 18, 20)
        title = label("＋   拖入一个或多个视频", "section")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dropbox.addWidget(title)
        types = label("MP4  ·  MOV  ·  MKV  ·  AVI  ·  WebM  ·  M4V", "muted")
        types.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dropbox.addWidget(types)
        self.add_button = QPushButton("选择视频文件")
        self.add_button.clicked.connect(self.pick_files)
        dropbox.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignCenter)
        left.addWidget(drop)
        queue = QFrame()
        queue.setObjectName("card")
        qbox = QVBoxLayout(queue)
        qbox.setContentsMargins(14, 12, 14, 10)
        qhead = QHBoxLayout()
        self.queue_title = label("待处理视频", "section")
        qhead.addWidget(self.queue_title)
        qhead.addStretch()
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("quiet")
        self.clear_button.clicked.connect(self.clear_queue)
        qhead.addWidget(self.clear_button)
        qbox.addLayout(qhead)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["文件", "源帧率", "总帧数", "导出时长", "状态"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in [(1,75),(2,68),(3,100),(4,116)]:
            self.table.setColumnWidth(col,width)
        self.table.verticalHeader().setDefaultSectionSize(48)
        qbox.addWidget(self.table)
        self.empty = label("视频将显示在这里\n先检查帧数，再为你计算新的时长。", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setContentsMargins(0, 24, 0, 24)
        qbox.addWidget(self.empty)
        left.addWidget(queue, 1)
        content.addLayout(left, 1)
        settings = QFrame()
        settings.setObjectName("card")
        settings.setFixedWidth(270)
        right = QVBoxLayout(settings)
        right.setContentsMargins(22, 20, 22, 20)
        right.setSpacing(10)
        right.addWidget(label("导出设置", "section"))
        right.addWidget(label("目标帧率 / FPS", "muted"))
        self.rate = QComboBox()
        self.rate.setEditable(True)
        self.rate.addItems(["23.976","24","25","29.97","30","48","50","59.94","60","120"])
        self.rate.setCurrentText("30")
        self.rate.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.rate.setAccessibleName("目标帧率")
        self.rate.currentTextChanged.connect(self.refresh)
        right.addWidget(self.rate)
        right.addWidget(label("可直接输入 1–240\n支持小数或 30000/1001", "muted", True))
        self.preview = label("—", "number")
        right.addWidget(self.preview)
        self.preview_note = label("添加视频后显示预计时长", "muted", True)
        right.addWidget(self.preview_note)
        line = QFrame()
        line.setObjectName("separator")
        line.setFixedHeight(1)
        right.addWidget(line)
        right.addWidget(label("声音同步变速，音调不变", "section", True))
        right.addWidget(label("画面不重编码；音频采用高质量处理。", "muted", True))
        right.addStretch()
        right.addWidget(label("保存位置", "muted"))
        self.output_label = label("与原视频相同的文件夹", None, True)
        self.output_label.setMaximumHeight(58)
        right.addWidget(self.output_label)
        self.output_button = QPushButton("更改文件夹…")
        self.output_button.clicked.connect(self.pick_output)
        right.addWidget(self.output_button)
        self.start_button = QPushButton("开始导出  →")
        self.start_button.setMinimumHeight(50)
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_export)
        right.addWidget(self.start_button)
        content.addWidget(settings)
        root.addLayout(content, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0,1000)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.status = label("就绪 · 导出为新文件，原文件始终保留", "muted")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status,1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancel_job)
        self.cancel_button.hide()
        bottom.addWidget(self.cancel_button)
        self.reveal_button = QPushButton("打开输出文件夹")
        self.reveal_button.clicked.connect(self.reveal_output)
        self.reveal_button.hide()
        bottom.addWidget(self.reveal_button)
        self.log_button = QPushButton("处理记录")
        self.log_button.setObjectName("quiet")
        bottom.addWidget(self.log_button)
        root.addLayout(bottom)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.hide()
        self.log_button.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        root.addWidget(self.log)
        self.refresh()

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self,"选择视频", "", "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)")
        self.add_files(files)

    def pick_output(self):
        folder = QFileDialog.getExistingDirectory(self,"选择输出文件夹", str(self.output_dir or Path.home()))
        if folder:
            self.output_dir = Path(folder)
            self.output_label.setText(str(self.output_dir))
            self.output_label.setToolTip(str(self.output_dir))

    def add_files(self, paths):
        if self.busy:
            return
        jobs = []
        for value in paths:
            path = Path(value).resolve()
            if path in self.paths:
                continue
            index = len(self.paths)
            self.paths.append(path)
            self.table.insertRow(index)
            for col, text in enumerate([path.name,"—","—","—","等待检查"]):
                item = QTableWidgetItem(text)
                item.setToolTip(str(path) if col == 0 else text)
                self.table.setItem(index,col,item)
            jobs.append((index,path))
        if jobs:
            self.launch(Worker(jobs,parent=self))
        self.refresh()

    def clear_queue(self):
        if self.busy:
            return
        self.paths.clear()
        self.infos.clear()
        self.table.setRowCount(0)
        self.refresh()

    def refresh(self, *_):
        try:
            target = parse_fps(self.rate.currentText())
        except MediaError:
            target = None
        for row, info in self.infos.items():
            self.table.item(row,3).setText(seconds(info.frame_count/target) if target else "无效帧率")
        self.empty.setVisible(not self.paths)
        self.queue_title.setText(f"待处理视频 · {len(self.paths)}" if self.paths else "待处理视频")
        count = sum(i.frame_count for i in self.infos.values())
        self.preview.setText(f"{float(count/target):.3f} s" if count and target else "—")
        self.preview_note.setText(f"{len(self.infos)} 个视频 · 共 {count:,} 帧\n预计导出总时长" if count and target
                                  else "请输入有效帧率" if not target else "添加视频后显示预计时长")
        self.start_button.setEnabled(bool(self.infos) and target is not None and not self.busy)
        for widget in [self.rate,self.add_button,self.clear_button,self.output_button]:
            widget.setEnabled(not self.busy)
        self.cancel_button.setVisible(self.busy)
        self.reveal_button.setVisible(bool(self.outputs) and not self.busy)

    def start_export(self):
        if self.busy or not self.infos:
            return
        try:
            target = parse_fps(self.rate.currentText())
        except MediaError as error:
            self.status.setText(str(error))
            return
        self.outputs = []
        jobs = [(i,self.paths[i]) for i in self.infos]
        for i,_ in jobs:
            self.table.item(i,4).setText("等待导出")
        self.launch(Worker(jobs,target,self.output_dir,parent=self))

    def launch(self, worker):
        self.worker = worker
        self.busy = True
        self._errors = 0
        self.progress.setValue(0)
        worker.result.connect(self.on_result)
        worker.error.connect(self.on_error)
        worker.update.connect(self.on_progress)
        worker.finished.connect(self.on_finished)
        self.refresh()
        worker.start()

    def on_result(self, row, result):
        if isinstance(result, MediaInfo):
            self.infos[row] = result
            self.table.item(row,1).setText(f"{float(result.fps):.3f}".rstrip("0").rstrip("."))
            self.table.item(row,2).setText(f"{result.frame_count:,}")
            text = "就绪"
            self.log.appendPlainText(f"已检查：{result.path.name} · {result.codec} · {result.width}×{result.height} · {result.frame_count} 帧")
        else:
            self.outputs.append(result.path)
            text = "✓ 校验通过"
            self.log.appendPlainText(f"已导出：{result.path}\n{result.frames} 帧 · {result.fps} fps · {seconds(result.duration)}\n画面 SHA-256：{result.video_hash}")
        self.table.item(row,4).setText(text)
        self.table.item(row,4).setForeground(QColor("#b7f5cf"))
        self.refresh()

    def on_error(self, row, message):
        self._errors += 1
        self.table.item(row,4).setText("已取消" if message == "已取消" else "处理失败")
        self.table.item(row,4).setToolTip(message)
        self.table.item(row,4).setForeground(QColor("#f0b98b"))
        self.log.appendPlainText(f"{self.paths[row].name}：{message}\n")
        if message != "已取消":
            self.log.show()

    def on_progress(self, text, value):
        self.status.setText(text)
        self.progress.setValue(int(value*1000))

    def on_finished(self):
        cancelled = self.worker.cancel.is_set()
        exporting = self.worker.target is not None
        for row in range(self.table.rowCount()):
            if self.table.item(row,4).text().startswith("等待"):
                self.table.item(row,4).setText("未处理")
        self.busy = False
        self.worker.deleteLater()
        self.worker = None
        if cancelled:
            text = "已取消 · 已完成的文件保留，其余未完成输出已清理"
        elif exporting:
            text = f"完成 · 成功 {len(self.outputs)} 个，失败 {self._errors} 个 · 画面校验通过后才保存"
            self.progress.setValue(1000)
        else:
            text = f"检查完成 · {len(self.infos)} 个视频可导出" + (" · 问题详见处理记录" if self._errors else "")
            self.progress.setValue(0)
        self.status.setText(text)
        self.refresh()
        if self._closing:
            self.close()

    def cancel_job(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("正在取消并清理临时文件…")

    def reveal_output(self):
        if self.outputs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outputs[-1].parent)))

    def dragEnterEvent(self,event):
        if not self.busy and event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self,event):
        if not self.busy:
            self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()

    def closeEvent(self,event):
        if self.busy:
            self._closing = True
            self.cancel_job()
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FPS Tools")
    app.setOrganizationName("fps-tools")
    app.setFont(QFont(".AppleSystemUIFont" if sys.platform == "darwin" else "Microsoft YaHei", 11))
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    app.setWindowIcon(QIcon(str(resources / "assets/icon.png")))
    window = MainWindow()
    window.show()
    result = app.exec()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    return result
