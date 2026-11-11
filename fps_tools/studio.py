"""Separate Studio application; the original conform workflow stays available."""
import sys
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QCoreApplication,QEvent
from PySide6.QtGui import QFont,QIcon
from PySide6.QtWidgets import QApplication,QMainWindow,QTabWidget
from . import __version__
from .gui import MainWindow,STYLE
from .frame_editor import FrameEditor

class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle(f'帧节奏工作室 · FPS Tools Studio {__version__}')
        self.resize(1200,900);self.setMinimumSize(960,740);self.setStyleSheet(STYLE)
        self.tabs=QTabWidget();self.setCentralWidget(self.tabs)
        self.editor=FrameEditor();self.legacy=MainWindow();self.legacy.setWindowFlags(Qt.WindowType.Widget)
        self.legacy.setMinimumSize(0,0)
        self.tabs.addTab(self.editor,'逐帧编辑');self.tabs.addTab(self.legacy,'原帧率工具 · 画面不重编码')
        self._closing=False;self.close_timer=QTimer(self);self.close_timer.setInterval(50);self.close_timer.timeout.connect(self.close)
    def closeEvent(self,event):
        if not self._closing:
            if not self.editor.confirm_discard():event.ignore();return
            self._closing=True
        if self.editor.busy or self.legacy.busy:
            self.editor.cancel.set();self.legacy.cancel_job();self.close_timer.start();event.ignore();return
        self.close_timer.stop();self.editor.cleanup();event.accept()


def main():
    app=QApplication(sys.argv);app.setApplicationName('FPS Tools Studio');app.setOrganizationName('fps-tools-studio')
    app.setFont(QFont('.AppleSystemUIFont' if sys.platform=='darwin' else 'Microsoft YaHei',11))
    resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    app.setWindowIcon(QIcon(str(resources/'assets/icon.png')))
    window=StudioWindow();window.show();result=app.exec()
    window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    return result
