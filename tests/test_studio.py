import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication,QEvent
from fps_tools.studio import StudioWindow


def test_tabs_and_close_during_import(make_video):
    app=QApplication.instance() or QApplication([])
    w=StudioWindow();w.show()
    assert w.tabs.count()==2
    assert 'Studio' in w.windowTitle()
    w.editor.open_video(make_video(frames=120,audio=False));w.close()
    deadline=time.monotonic()+30
    while w.isVisible() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert not w.isVisible() and not w.editor.busy
    w.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
