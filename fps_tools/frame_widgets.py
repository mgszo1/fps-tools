"""Virtual filmstrips: bounded image cache, no widget per source frame."""
from collections import OrderedDict
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QSize, QRect
from PySide6.QtGui import QColor, QPixmap, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QLabel

class FilmstripModel(QAbstractListModel):
    def __init__(self, output=False, parent=None):
        super().__init__(parent);self.output=output;self.plan=None;self.clip=None;self.cache=OrderedDict()

    def update_plan(self,clip,plan):
        self.beginResetModel()
        if clip!=self.clip: self.cache.clear()
        self.clip=clip;self.plan=plan;self.endResetModel()

    def rowCount(self,parent=QModelIndex()):
        if parent.isValid() or self.plan is None:return 0
        return self.plan.total if self.output else self.plan.source_frames

    def source_index(self,index): return self.plan.source_at(index) if self.output else index

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<self.rowCount():return None
        source=self.source_index(index.row());n=self.plan.repeats[source]
        if role==Qt.ItemDataRole.DisplayRole:
            return f'{index.row()+1:04d}  ← 原 {source+1:04d}' if self.output else f'原 {source+1:04d}  ·  '+('删除' if n==0 else f'×{n}' if n>1 else '保留')
        if role==Qt.ItemDataRole.UserRole:return n
        if role==Qt.ItemDataRole.ToolTipRole:
            return f'原片第 {source+1} 帧 · 输出 {n} 次。按住 Ctrl / ⌘ 或 Shift 多选。'
        if role==Qt.ItemDataRole.DecorationRole:
            if source not in self.cache:
                self.cache[source]=QPixmap(str(self.clip.thumbnail(source)))
                if len(self.cache)>128:self.cache.popitem(last=False)
            else:self.cache.move_to_end(source)
            return self.cache[source]

class FilmstripDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):return QSize(154,116)
    def paint(self,painter,option,index):
        painter.save();rect=option.rect.adjusted(3,3,-3,-3)
        selected=bool(option.state & QStyle.StateFlag.State_Selected)
        n=index.data(Qt.ItemDataRole.UserRole)
        color=QColor('#ed9c80' if n==0 else '#b4f4cc' if n>1 else '#92a69b')
        painter.setBrush(QColor('#244b38' if selected else '#17251e'))
        painter.setPen(QPen(QColor('#b4f4cc') if selected else QColor('#31463a'),2 if selected else 1))
        painter.drawRoundedRect(rect,7,7)
        pix=index.data(Qt.ItemDataRole.DecorationRole)
        if pix and not pix.isNull():
            scaled=pix.scaled(140,78,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            target=QRect(rect.center().x()-scaled.width()//2,rect.y()+4,scaled.width(),scaled.height())
            if n==0:painter.setOpacity(.4)
            painter.drawPixmap(target,scaled);painter.setOpacity(1)
            if n==0:
                painter.setPen(QPen(color,2));painter.drawLine(target.topLeft(),target.bottomRight())
        painter.setPen(color)
        painter.drawText(rect.adjusted(5,84,-3,-2),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,index.data())
        painter.restore()

class PreviewLabel(QLabel):
    def __init__(self):
        super().__init__('打开视频，开始调整每一帧的节奏')
        self.original=QPixmap();self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240,140);self.setStyleSheet('background:#080e0a;border-radius:10px;color:#82998b;')
    def show_image(self,path):
        self.original=QPixmap(str(path));self._scale()
    def _scale(self):
        if not self.original.isNull():self.setPixmap(self.original.scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self,event):super().resizeEvent(event);self._scale()
