import time
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication,QEvent,QItemSelectionModel
from fps_tools.frame_editor import FrameEditor

@pytest.fixture(scope='session')
def app(): return QApplication.instance() or QApplication([])

def settle(app,w):
    deadline=time.monotonic()+30
    while w.busy and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    app.processEvents();assert not w.busy

@pytest.fixture
def editor(app):
    w=FrameEditor();w.show()
    yield w
    w.dirty=False
    if w.busy: w.cancel.set();settle(app,w)
    w.close();w.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

def test_edit_history_balance_and_export(app,editor,make_video,tmp_path):
    editor.open_video(make_video(frames=12,audio=False));settle(app,editor)
    assert editor.plan.total==12
    editor.select_source(3);editor.edit_selected('delete')
    assert editor.plan.total==11 and editor.plan.repeats[3]==0
    editor.edit_selected('restore');editor.edit_selected('duplicate')
    assert editor.plan.repeats[3]==2
    editor.undo();assert editor.plan.total==12
    editor.rate.setEditText('12');editor.generate_resample()
    assert editor.plan.total==6 and editor.plan.keep_duration
    editor.select_source(1);editor.edit_selected('duplicate')
    assert not editor.export_button.isEnabled() and editor.plan.balance==1
    editor.undo();assert editor.export_button.isEnabled()
    editor.export_to(tmp_path);settle(app,editor)
    assert editor.last_output.is_file()

def test_project_and_compact_layout(app,editor,make_video,tmp_path):
    editor.resize(960,740)
    editor.open_video(make_video(frames=6,audio=False));settle(app,editor)
    editor.select_source(2);editor.edit_selected('duplicate')
    dest=tmp_path/'edit.fpsedit';editor.save_to(dest)
    assert not editor.dirty
    editor.open_project(dest);settle(app,editor)
    assert editor.plan.repeats[2]==2 and not editor.dirty
    assert editor.source_model.rowCount()==6 and editor.output_model.rowCount()==7
    assert editor.export_button.isVisible()
    editor.play_pause();app.processEvents()
    assert editor.timer.isActive()
    editor.edit_selected('delete');assert not editor.timer.isActive()

def test_multiselection_and_transfer(app,editor,make_video):
    editor.open_video(make_video(frames=8,audio=False));settle(app,editor)
    editor.select_source(1)
    editor.source_view.selectionModel().select(editor.source_model.index(2),QItemSelectionModel.SelectionFlag.Select)
    editor.edit_selected('duplicate')
    assert editor.plan.repeats[1:3]==(2,2)
    editor.select_source(1);editor.move_exposure(1)
    assert editor.plan.repeats[1:3]==(1,3)


def test_failed_import_preserves_current_and_cleans(app,editor,make_video,tmp_path):
    editor.open_video(make_video(frames=6,audio=False));settle(app,editor)
    old=editor.clip;oldcache=editor.cache.name
    bad=tmp_path/'bad.mov';bad.write_bytes(b'bad')
    editor.open_video(bad);settle(app,editor)
    assert editor.clip==old and editor.cache.name==oldcache
    assert editor._import_cache is None


def test_close_cancels_worker(app,make_video):
    w=FrameEditor();w.show()
    w.open_video(make_video(frames=120,audio=False));w.close()
    settle(app,w)
    assert not w.isVisible() and w.cache is None
    w.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
