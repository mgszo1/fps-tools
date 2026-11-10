import time

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QCoreApplication, QEvent

from fps_tools.gui import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean_windows(app):
    yield
    for window in app.topLevelWidgets():
        if isinstance(window, MainWindow):
            if window.busy:
                window.cancel_job()
                settle(app, window)
            window.close()
            window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def settle(app, window):
    deadline = time.monotonic() + 30
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        # qWait can retain the Python GIL on some PySide/Windows builds,
        # starving the Python QThread worker we are waiting for.
        time.sleep(.01)
    app.processEvents()
    assert not window.busy


def test_gui_exports_real_file_and_rejects_bad_rate(app, make_video, tmp_path):
    src = make_video(frames=48)
    window = MainWindow()
    window.show()
    assert not window.start_button.isEnabled()
    window.add_files([src])
    settle(app, window)
    assert window.start_button.isEnabled()
    window.rate.setEditText("oops")
    assert not window.start_button.isEnabled()
    window.rate.setEditText("30")
    assert "1.600" in window.table.item(0,3).text()
    QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    settle(app, window)
    assert len(window.outputs) == 1
    assert window.outputs[0].exists()
    assert "通过" in window.table.item(0,4).text()
    window.close()


def test_gui_cancel_recovers_and_bad_files_do_not_enable_export(app, tmp_path):
    bad = tmp_path / "坏视频.mp4"
    bad.write_bytes(b"bad")
    window = MainWindow()
    window.add_files([bad])
    settle(app, window)
    assert not window.start_button.isEnabled()
    assert "失败" in window.table.item(0,4).text()
    window.clear_queue()
    assert window.table.rowCount() == 0
    window.close()


def test_cancel_inspection_can_be_retried(app, make_video):
    src = make_video(frames=240)
    window = MainWindow()
    window.add_files([src])
    window.cancel_job()
    settle(app, window)
    assert window.add_button.isEnabled()
    window.clear_queue()
    window.add_files([src])
    settle(app, window)
    assert window.start_button.isEnabled()
    window.close()
