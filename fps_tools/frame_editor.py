"""Exposure editor and live proxy playback. Source pictures are never edited in place."""
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path
import tempfile
import threading
import time

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QItemSelectionModel, QSignalBlocker
from PySide6.QtGui import QKeySequence, QShortcut, QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
    QSpinBox,QCheckBox,QScrollArea,QListView,QAbstractItemView,QSlider,QProgressBar,
    QFileDialog,QMessageBox,QFrame,QSizePolicy,QSplitter)
from .frame_plan import FramePlan, FrameHistory, resample_plan, save_project, load_project
from .frame_media import ExportSettings, prepare_clip, export_frames, prepare_audio_preview
from .frame_widgets import FilmstripModel,FilmstripDelegate,PreviewLabel
from .media import parse_fps
from .process import MediaError
from .gui import STYLE


class Job(QThread):
    result=Signal(object)
    error=Signal(str)
    progress=Signal(str,float)
    def __init__(self,fn,cancel,parent):super().__init__(parent);self.fn=fn;self.cancel=cancel
    def run(self):
        try:self.result.emit(self.fn(self.cancel,self.progress.emit))
        except Exception as e:self.error.emit(str(e))


class FrameEditor(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE + "QComboBox {font-size:14px; min-height:20px; padding:7px;} QComboBox QLineEdit{font-size:16px;} QSpinBox{padding:6px; border:1px solid #4c6957; border-radius:5px;} QPushButton{padding:8px 12px;}")
        self.clip=None;self.history=None;self.cache=None;self.thread=None
        self.busy=False;self.cancel=threading.Event();self.dirty=False;self.project_path=None
        self.last_output=None;self._closing=False;self._loading=False;self.position=0
        self._audio_key=None;self._pending_play=False;self._play_started=0;self._play_offset=0
        self.player=QMediaPlayer(self);self.audio_output=QAudioOutput(self);self.player.setAudioOutput(self.audio_output)
        self.player.errorOccurred.connect(lambda *_:self.status.setText('声音预览不可用；画面仍可播放，导出不受影响。'))
        self.timer=QTimer(self);self.timer.setInterval(10);self.timer.timeout.connect(self.tick)
        self._build();self._sync()
        self.setAcceptDrops(True)

    @property
    def plan(self):return self.history.current if self.history else None

    def _button(self,text,fn,layout):
        b=QPushButton(text);b.clicked.connect(fn);layout.addWidget(b);return b

    def _build(self):
        root=QVBoxLayout(self);root.setContentsMargins(18,12,18,12);root.setSpacing(9)
        header=QHBoxLayout();root.addLayout(header)
        title=QLabel('逐帧，安排节奏。');title.setStyleSheet('font-size:23px;font-weight:700;');header.addWidget(title);header.addStretch()
        self.open_button=self._button('打开视频',self.choose_video,header)
        self.project_button=self._button('打开工程',self.choose_project,header)
        self.save_button=self._button('保存工程',self.save_dialog,header)
        self.file_label=QLabel('删减、重复、保留运动关键帧。预览使用缩影，导出读取原始画面。');self.file_label.setWordWrap(True);root.addWidget(self.file_label)
        self.splitter=QSplitter(Qt.Orientation.Vertical);root.addWidget(self.splitter,1)
        upper=QWidget();up=QHBoxLayout(upper);up.setContentsMargins(0,0,0,0)
        viewer=QWidget();vl=QVBoxLayout(viewer);vl.setContentsMargins(0,0,0,0)
        self.preview=PreviewLabel();vl.addWidget(self.preview,1)
        self.frame_label=QLabel('原片 —  /  结果 —');vl.addWidget(self.frame_label)
        self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.sliderMoved.connect(self.seek_to);vl.addWidget(self.seek)
        controls=QHBoxLayout();vl.addLayout(controls)
        self._button('◀ 上一帧',lambda:self.step(-1),controls)
        self.play_button=self._button('播放  ▶',self.play_pause,controls)
        self._button('下一帧 ▶',lambda:self.step(1),controls)
        self.loop=QCheckBox('循环');self.loop.setChecked(True);controls.addWidget(self.loop);controls.addStretch()
        up.addWidget(viewer,1)
        self.settings_panel=QWidget();sl=QVBoxLayout(self.settings_panel);sl.setContentsMargins(12,4,12,8);sl.setSpacing(10)
        def label(text):
            x=QLabel(text);x.setWordWrap(True);sl.addWidget(x);return x
        label('目标帧率 / FPS')
        self.rate=QComboBox();self.rate.setEditable(True);self.rate.addItems(['12','24','25','30','50','60','23.976','29.97']);self.rate.setCurrentText('24');sl.addWidget(self.rate)
        self.rate.currentTextChanged.connect(self.rate_changed)
        self.keep=QCheckBox('保持原片时长');sl.addWidget(self.keep);self.keep.toggled.connect(self.mode_changed)
        self.resample_button=self._button('自动分配删帧 / 重复帧',self.confirm_resample,sl)
        self.summary=label('等待原片');self.summary.setStyleSheet('color:#b5f5cd; font-size:15px;')
        line=QFrame();line.setFrameShape(QFrame.Shape.HLine);sl.addWidget(line)
        label('导出编码')
        self.codec=QComboBox();self.codec.addItem('H.264 · MP4','h264');self.codec.addItem('ProRes 422 HQ · MOV','prores');sl.addWidget(self.codec)
        br=QHBoxLayout();sl.addLayout(br);br.addWidget(QLabel('码率 Mbps'))
        self.bitrate=QSpinBox();self.bitrate.setRange(1,500);self.bitrate.setValue(100);br.addWidget(self.bitrate)
        self.encoding_note=label('H.264 为目标平均码率，实际码率随内容变化。')
        self.codec.currentIndexChanged.connect(self.settings_changed);self.bitrate.valueChanged.connect(self.settings_changed)
        label('声音处理')
        self.audio=QComboBox()
        self.audio.addItem('整体变速 · 音调不变','tempo');self.audio.addItem('原时间轴 · 裁切 / 补静音','original');self.audio.addItem('静音','mute');sl.addWidget(self.audio)
        self.audio.currentIndexChanged.connect(self.settings_changed)
        label('声音按整段处理，不随单帧复制或删除。预览播放第一条音轨，导出保留全部音轨。')
        label('原分辨率重新编码 · 不插值\nProRes 422 HQ 使用 10 位 4:2:2；H.264 使用 4:2:0，保留源片 8 / 10 位深度。')
        sl.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.settings_panel);scroll.setMinimumWidth(295);scroll.setMaximumWidth(365)
        up.addWidget(scroll);self.splitter.addWidget(upper)
        strips=QWidget();st=QVBoxLayout(strips);st.setContentsMargins(0,0,0,0);st.setSpacing(5)
        toolbar=QHBoxLayout();st.addLayout(toolbar)
        self.edit_buttons=[]
        for text,act in [('删除','delete'),('复制 +1','duplicate'),('恢复 ×1','restore')]:
            self.edit_buttons.append(self._button(text,lambda checked=False,a=act:self.edit_selected(a),toolbar))
        self.repeat_count=QSpinBox();self.repeat_count.setRange(0,10000);self.repeat_count.setValue(1);self.repeat_count.setPrefix('次数 ');toolbar.addWidget(self.repeat_count)
        self.edit_buttons.append(self._button('设置',lambda:self.edit_selected('set'),toolbar))
        self.edit_buttons.append(self._button('移给前帧',lambda:self.move_exposure(-1),toolbar))
        self.edit_buttons.append(self._button('移给后帧',lambda:self.move_exposure(1),toolbar))
        toolbar.addStretch()
        self.undo_button=self._button('撤销',self.undo,toolbar);self.redo_button=self._button('重做',self.redo,toolbar)
        label1=QLabel('原片缩影轴  ·  红色＝删除   绿色 ×N＝重复   Ctrl / ⌘ / Shift 多选');st.addWidget(label1)
        self.source_model=FilmstripModel(parent=self);self.output_model=FilmstripModel(True,self)
        self.source_view=self._strip(self.source_model);st.addWidget(self.source_view)
        self.source_view.selectionModel().currentChanged.connect(self.source_selected)
        st.addWidget(QLabel('结果缩影轴  ·  按此顺序回放和导出'))
        self.output_view=self._strip(self.output_model);self.output_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);st.addWidget(self.output_view)
        self.output_view.clicked.connect(lambda index:self.seek_to(index.row()))
        self.splitter.addWidget(strips);self.splitter.setSizes([390,320]);self.splitter.setStretchFactor(0,1)
        bottom=QHBoxLayout();root.addLayout(bottom)
        self.status=QLabel('准备就绪');self.status.setWordWrap(True);self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);bottom.addWidget(self.status,1)
        self.reveal_button=self._button('查看输出',self.reveal_output,bottom);self.reveal_button.setEnabled(False)
        self.cancel_button=self._button('取消处理',lambda:self.cancel.set(),bottom)
        self.export_button=self._button('导出视频  →',self.choose_export,bottom);self.export_button.setMinimumHeight(42);self.export_button.setStyleSheet('background:#b5f5cd;color:#102219;font-weight:700;padding:8px 22px;')
        self.progress=QProgressBar();self.progress.setRange(0,1000);self.progress.setTextVisible(False);self.progress.setFixedHeight(5);root.addWidget(self.progress)
        for key,fn in [('Space',self.play_pause),('Ctrl+Z',self.undo),('Ctrl+Shift+Z',self.redo),('Ctrl+S',self.save_dialog),('Delete',lambda:self.edit_selected('delete'))]:
            shortcut=QShortcut(QKeySequence(key),self);shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);shortcut.activated.connect(fn)

    def _strip(self,model):
        view=QListView();view.setModel(model);view.setItemDelegate(FilmstripDelegate(view));view.setFlow(QListView.Flow.LeftToRight)
        view.setWrapping(False);view.setUniformItemSizes(True);view.setResizeMode(QListView.ResizeMode.Fixed)
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);view.setFixedHeight(136)
        view.setStyleSheet('QListView{background:#101b15;border:1px solid #2a4033;border-radius:8px;}');return view

    def _sync(self):
        active=bool(self.plan) and not self.busy
        for widget in [self.rate,self.keep,self.resample_button,self.codec,self.audio,*self.edit_buttons,self.repeat_count,self.source_view,self.output_view,self.seek]:widget.setEnabled(active)
        self.bitrate.setEnabled(active and self.codec.currentData()=='h264')
        self.open_button.setEnabled(not self.busy);self.project_button.setEnabled(not self.busy)
        self.save_button.setEnabled(active);self.play_button.setEnabled(active and self.plan.total>0)
        self.undo_button.setEnabled(active and self.history.index>0);self.redo_button.setEnabled(active and self.history.index<len(self.history.items)-1)
        self.cancel_button.setVisible(self.busy)
        valid=True
        try: parse_fps(self.rate.currentText())
        except MediaError:valid=False
        self.export_button.setEnabled(active and valid and self.plan.exportable)
        if self.plan:
            p=self.plan
            balance=f'目标 {p.desired} 帧 · '+('已平衡' if p.balance==0 else f'还需删除 {p.balance} 帧' if p.balance>0 else f'还需增加 {-p.balance} 帧')
            self.summary.setText(f'原片 {p.source_frames} 帧 / {float(p.source_frames/p.source_fps):.3f} 秒\n结果 {p.total} 帧 / {float(p.duration):.3f} 秒'+(f'\n{balance}\n时长误差 {float(p.duration_error):+.4f} 秒' if p.keep_duration else ''))
        self.encoding_note.setText('ProRes 422 HQ 按档位控制码率，文件通常较大。' if self.codec.currentData()=='prores' else 'H.264 为目标平均码率，实际码率随内容变化。')

    def _job(self,fn,done):
        if self.busy:return
        self.pause();self.busy=True;self.cancel=threading.Event();self._sync()
        self.thread=Job(fn,self.cancel,self)
        self.thread.result.connect(done);self.thread.error.connect(self.failed)
        self.thread.progress.connect(self.update_progress);self.thread.finished.connect(self.finished)
        self.thread.start()

    def failed(self,error):self._pending_play=False;self.status.setText(error)
    def update_progress(self,msg,value):self.status.setText(msg);self.progress.setValue(int(value*1000))
    def finished(self):
        job=self.thread;self.thread=None;self.busy=False
        if job:job.deleteLater()
        if getattr(self,'_import_cache',None):self._import_cache.cleanup();self._import_cache=None
        self._sync()
        if self._closing:QTimer.singleShot(0,self.close)
        elif self._pending_play:self._pending_play=False;self._start_play()

    def confirm_discard(self):
        if not self.dirty:return True
        answer=QMessageBox.question(self,'尚未保存工程','保存当前帧编辑工程吗？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        if answer==QMessageBox.StandardButton.Cancel:return False
        if answer==QMessageBox.StandardButton.Save:return self.save_dialog()
        return True

    def choose_video(self):
        if not self.confirm_discard():return
        path,_=QFileDialog.getOpenFileName(self,'打开视频','','视频 (*.mp4 *.mov *.mkv *.avi *.m4v *.webm)')
        if path:self.open_video(Path(path))
    def choose_project(self):
        if not self.confirm_discard():return
        path,_=QFileDialog.getOpenFileName(self,'打开帧工程','','FPS Tools 工程 (*.fpsedit)')
        if path:self.open_project(Path(path))

    def open_video(self,path,project=None,project_path=None):
        if self.busy:return
        new_cache=tempfile.TemporaryDirectory(prefix='fps-studio-preview-')
        self._import_cache=new_cache
        def work(cancel,progress):
            clip=prepare_clip(path,Path(new_cache.name),cancel,progress)
            if project and (clip.info.packet_hash!=project.fingerprint or clip.info.frame_count!=project.plan.source_frames or clip.info.fps!=project.plan.source_fps):
                raise MediaError('工程引用的原片不匹配，未载入。')
            incoming_plan=project.plan if project else FramePlan.original(clip.info.frame_count,clip.info.fps)
            incoming_settings=ExportSettings(**project.settings) if project else ExportSettings()
            return clip,incoming_plan,incoming_settings
        def done(result):
            clip,incoming_plan,settings=result
            self.player.stop();self.player.setSource(QUrl());self._audio_key=None
            if self.cache:self.cache.cleanup()
            self.cache=new_cache;self.clip=clip;self._import_cache=None
            self.history=FrameHistory(incoming_plan)
            self.project_path=Path(project_path) if project_path else None
            self._loading=True
            self.rate.setCurrentText(str(self.plan.target_fps));self.keep.setChecked(self.plan.keep_duration)
            self.codec.setCurrentIndex(self.codec.findData(settings.codec));self.bitrate.setValue(settings.bitrate_mbps);self.audio.setCurrentIndex(self.audio.findData(settings.audio_mode))
            self._loading=False;self.dirty=False;self.position=0
            self.file_label.setText(f'{clip.info.path.name}   ·   {clip.info.width} × {clip.info.height}   ·   {clip.info.fps} fps')
            self.file_label.setToolTip(str(clip.info.path));self.refresh();self.select_source(0)
            self.status.setText('原片已展开。选择缩影后，可删除、复制或将曝光移给相邻帧。');self.progress.setValue(1000)
        self._job(work,done)

    def open_project(self,path):
        try:
            project=load_project(path);ExportSettings(**project.settings)
            source=project.source
            if not source.is_file():
                source,_=QFileDialog.getOpenFileName(self,'定位工程原片（将校验画面指纹）')
                if not source:return
            self.open_video(Path(source),project,path)
        except (MediaError,TypeError) as e:self.status.setText(str(e))

    def current_settings(self):return ExportSettings(self.codec.currentData(),self.bitrate.value(),self.audio.currentData())
    def save_to(self,path):
        if not self.clip or self.busy:return False
        save_project(path,self.clip.info,self.plan,asdict(self.current_settings()))
        self.project_path=Path(path);self.dirty=False;self.status.setText(f'工程已保存：{path}');return True
    def save_dialog(self):
        if not self.clip or self.busy:return False
        path=str(self.project_path or self.clip.info.path.with_suffix('.fpsedit'))
        path,_=QFileDialog.getSaveFileName(self,'保存帧工程',path,'FPS Tools 工程 (*.fpsedit)')
        if not path:return False
        if not path.endswith('.fpsedit'):path+='.fpsedit'
        try:return self.save_to(Path(path))
        except (OSError,MediaError) as e:self.status.setText(str(e));return False

    def refresh(self):
        if not self.plan:return
        selection=self.selected_sources();current=self.source_view.currentIndex().row()
        self.source_model.update_plan(self.clip,self.plan);self.output_model.update_plan(self.clip,self.plan)
        for i in selection:self.source_view.selectionModel().select(self.source_model.index(i),QItemSelectionModel.SelectionFlag.Select)
        if 0<=current<self.plan.source_frames:self.source_view.selectionModel().setCurrentIndex(self.source_model.index(current),QItemSelectionModel.SelectionFlag.NoUpdate)
        self.seek.setRange(0,max(0,self.plan.total-1));self.position=min(self.position,max(0,self.plan.total-1));self.show_output(self.position)
        self._sync()

    def commit_plan(self,plan):
        self.pause();self._audio_key=None;self.player.setSource(QUrl())
        if plan!=self.plan:self.history.push(plan);self.dirty=True
        self.refresh()
    def selected_sources(self):return sorted({i.row() for i in self.source_view.selectionModel().selectedIndexes()})
    def select_source(self,index):
        self.source_view.setCurrentIndex(self.source_model.index(index))
    def source_selected(self,current,previous):
        if not current.isValid() or not self.plan or self.busy:return
        self.pause();i=current.row();self.preview.show_image(self.clip.preview(i))
        self.position=min(self.plan.prefix[i],max(0,self.plan.total-1));self.seek.setValue(self.position)
        self.frame_label.setText(f'原片第 {i+1} / {self.plan.source_frames} 帧  ·  输出 {self.plan.repeats[i]} 次')
    def edit_selected(self,action):
        if not self.plan or self.busy:return
        ids=self.selected_sources()
        if not ids:return
        try:
            plan=self.plan.increment(ids) if action=='duplicate' else self.plan.set_counts(ids,{'delete':0,'restore':1,'set':self.repeat_count.value()}[action])
            self.commit_plan(plan)
        except MediaError as e:self.status.setText(str(e))
    def move_exposure(self,direction):
        if not self.plan or self.busy:return
        ids=self.selected_sources()
        if len(ids)!=1:self.status.setText('请只选择一帧，将一次曝光移给相邻帧。');return
        try:self.commit_plan(self.plan.transfer(ids[0],ids[0]+direction))
        except MediaError as e:self.status.setText(str(e))
    def undo(self):
        if self.history and not self.busy:
            self.pause();self.history.undo();self._history_changed()
    def redo(self):
        if self.history and not self.busy:
            self.pause();self.history.redo();self._history_changed()
    def _history_changed(self):
        self._loading=True;self.rate.setCurrentText(str(self.plan.target_fps));self.keep.setChecked(self.plan.keep_duration);self._loading=False
        self._audio_key=None;self.player.setSource(QUrl());self.dirty=True;self.refresh()
    def rate_changed(self,*_):
        if self._loading or not self.plan or self.busy:return
        try:self.commit_plan(replace(self.plan,target_fps=parse_fps(self.rate.currentText())))
        except MediaError as e:self.status.setText(str(e));self._sync()
    def mode_changed(self,checked):
        if self._loading or not self.plan or self.busy:return
        self.commit_plan(replace(self.plan,keep_duration=checked))
        if checked:self.status.setText('已开启保持时长。可自动分配，或手动调整到目标帧数；不会自动覆盖已有编辑。')
    def confirm_resample(self):
        if not self.plan:return
        if any(x!=1 for x in self.plan.repeats):
            answer=QMessageBox.question(self,'重新自动分配','重新生成会替换当前删帧与重复次数，可以撤销。继续吗？')
            if answer!=QMessageBox.StandardButton.Yes:return
        self.generate_resample()
    def generate_resample(self):
        if not self.plan or self.busy:return
        try:
            self.commit_plan(resample_plan(self.plan.source_frames,self.plan.source_fps,parse_fps(self.rate.currentText())))
            self._loading=True;self.keep.setChecked(True);self._loading=False
            self.audio.setCurrentIndex(self.audio.findData('original'))
        except MediaError as e:self.status.setText(str(e))
    def settings_changed(self,*_):
        if self._loading:return
        self.pause();self._audio_key=None;self.player.setSource(QUrl())
        if self.plan:self.dirty=True
        self._sync()

    def pause(self):
        self.timer.stop();self.player.pause()
        if hasattr(self,'play_button'):self.play_button.setText('播放  ▶')
    def play_pause(self):
        if self.busy or not self.plan or not self.plan.total:return
        if self.timer.isActive():self.pause();return
        key=(self.plan,self.audio.currentData())
        if self.clip.info.audio and key[1]!='mute' and self._audio_key!=key:
            path=Path(self.cache.name)/'audio.wav';self.player.setSource(QUrl())
            def done(result):
                if result:self.player.setSource(QUrl.fromLocalFile(str(result)))
                self._audio_key=key;self._pending_play=True
            self.status.setText('准备声音预览…')
            self._job(lambda cancel,progress:prepare_audio_preview(self.clip.info,self.plan,key[1],path,cancel),done)
        else:self._start_play()
    def _start_play(self):
        if self.position>=self.plan.total-1:self.position=0
        self._play_offset=self.position/float(self.plan.target_fps);self._play_started=time.monotonic()
        if self.clip.info.audio and self.audio.currentData()!='mute':
            self.player.setPosition(round(self._play_offset*1000));self.player.play()
        self.timer.start();self.play_button.setText('暂停  ❚❚');self.status.setText('回放编辑结果 · 预览缩影不用于导出')
    def tick(self):
        seconds=self._play_offset+time.monotonic()-self._play_started
        index=int(seconds*float(self.plan.target_fps))
        if index>=self.plan.total:
            if self.loop.isChecked():self.position=0;self._start_play();index=0
            else:self.pause();index=self.plan.total-1
        if index!=self.position:self.show_output(index,True)
    def show_output(self,index,sync_selection=False):
        if not self.plan or not self.plan.total:
            self.frame_label.setText('结果为空，请恢复至少一帧。');return
        self.position=max(0,min(index,self.plan.total-1));source=self.plan.source_at(self.position)
        if sync_selection:
            with QSignalBlocker(self.source_view.selectionModel()):
                self.source_view.setCurrentIndex(self.source_model.index(source))
        self.preview.show_image(self.clip.preview(source));self.seek.setValue(self.position)
        self.frame_label.setText(f'结果 {self.position+1} / {self.plan.total} 帧  ←  原片 {source+1} 帧   ·   {self.position/float(self.plan.target_fps):.3f} 秒')
        idx=self.output_model.index(self.position);self.output_view.setCurrentIndex(idx);self.output_view.scrollTo(idx)
    def seek_to(self,index):self.pause();self.show_output(index,True)
    def step(self,direction):
        if not self.busy and self.plan:self.seek_to(self.position+direction)

    def choose_export(self):
        if not self.clip:return
        directory=QFileDialog.getExistingDirectory(self,'选择导出文件夹',str(self.clip.info.path.parent))
        if directory:self.export_to(Path(directory))
    def export_to(self,directory):
        if self.busy or not self.plan:return
        try:
            parse_fps(self.rate.currentText());settings=self.current_settings()
            if not self.plan.exportable:raise MediaError('请先平衡输出帧数。')
            plan=self.plan;info=self.clip.info
            def done(result):
                self.last_output=result.path;self.reveal_button.setEnabled(True)
                self.status.setText(f'导出完成 · {result.frames} 帧 · {float(result.duration):.3f} 秒\n{result.path}')
            self._job(lambda cancel,progress:export_frames(info,plan,settings,directory,cancel,progress),done)
        except MediaError as e:self.status.setText(str(e))
    def reveal_output(self):
        if self.last_output:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output.parent)))
    def dragEnterEvent(self,event):
        if not self.busy and event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):
        paths=[Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths and not self.busy and self.confirm_discard():
            (self.open_project if paths[0].suffix=='.fpsedit' else self.open_video)(paths[0]);event.acceptProposedAction()
    def cleanup(self):
        self.pause();self.player.stop();self.player.setSource(QUrl())
        if self.cache:self.cache.cleanup();self.cache=None
        if getattr(self,'_import_cache',None):self._import_cache.cleanup();self._import_cache=None
    def closeEvent(self,event):
        if not self._closing and not self.confirm_discard():event.ignore();return
        self._closing=True
        if self.busy:self.cancel.set();event.ignore();return
        self.cleanup();event.accept()
