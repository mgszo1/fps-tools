import time

import pytest
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QCoreApplication, QEvent, QMimeData, QPointF
from PySide6.QtGui import QDropEvent

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
    assert window.table.horizontalHeaderItem(3).text() == "原片时长"
    assert "2.000" in window.table.item(0,3).text()
    assert "1.600" in window.preview.text()
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


def test_queue_reorder_remove_and_export_keep_file_associations(app, make_video, tmp_path):
    first = make_video(name="first.mp4",frames=24,audio=False)
    second = make_video(name="second.mp4",frames=48,audio=False)
    bad = tmp_path/"bad.mov"
    bad.write_bytes(b"bad")
    window = MainWindow()
    window.show()
    window.add_files([first,bad,second])
    settle(app,window)
    # Same callback as the table's internal drag-and-drop event.
    window.table.row_moved.emit(2,0)
    assert window.paths == [second,first,bad]
    assert window.infos[0].path == second and window.infos[1].path == first
    assert "失败" in window.table.item(2,4).text()
    QTest.mouseClick(window.table.cellWidget(2,5),Qt.MouseButton.LeftButton)
    assert window.paths == [second,first]
    window.rate.setEditText("12")
    assert "2.000" in window.table.item(0,3).text()
    assert "1.000" in window.table.item(1,3).text()
    assert "6.000" in window.preview.text()
    window.start_export()
    before = list(window.paths)
    window.move_queue_row(0,1)
    window.remove_queue_row(0)
    assert window.paths == before  # worker events still address these row indexes
    settle(app,window)
    assert len(window.outputs) == 2
    assert window.outputs[0].stem.startswith("second_")
    assert window.outputs[1].stem.startswith("first_")
    QTest.mouseClick(window.table.cellWidget(0,5),Qt.MouseButton.LeftButton)
    assert window.paths == [first] and window.infos[0].path == first
    assert window.table.item(0,0).text() == first.name
    window.table.selectRow(0)
    QTest.keyClick(window.table,Qt.Key.Key_Delete)
    assert not window.paths and not window.infos
    assert not window.start_button.isEnabled()


def test_queue_drop_positions_and_keyboard_reordering(app, make_video):
    files = [make_video(name=f"row{i}.mp4",frames=24,audio=False) for i in range(3)]
    window = MainWindow()
    window.show()
    window.add_files(files)
    settle(app,window)
    table = window.table

    class InternalDrop(QDropEvent):
        def source(self):
            return table

    def drop(source, position):
        mime = QMimeData()
        mime.setData(table.MIME,str(source).encode("ascii"))
        event = InternalDrop(QPointF(position),Qt.DropAction.MoveAction,mime,
                             Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        table.dropEvent(event)
        assert event.isAccepted()

    # Upper/lower halves mean before/after, not replace an existing row.
    drop(2,table.visualItemRect(table.item(0,0)).topLeft())
    assert window.paths == [files[2],files[0],files[1]]
    drop(0,table.visualItemRect(table.item(2,0)).bottomLeft())
    assert window.paths == files
    table.selectRow(1)
    QTest.keyClick(table,Qt.Key.Key_Up,Qt.KeyboardModifier.AltModifier)
    assert window.paths == [files[1],files[0],files[2]]


def test_small_window_keeps_settings_readable_and_remove_visible(app, make_video):
    window = MainWindow()
    window.resize(900,620)
    window.show()
    window.add_files([make_video(frames=24,audio=False)])
    settle(app,window)
    window.log.show()
    window.output_label.setText("/一个很长的项目文件夹/原始素材/剪辑之后的输出文件/最终确认版本")
    app.processEvents()
    layout = window.settings_scroll.widget().layout()
    bottom = -1
    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if widget is None:
            continue
        assert widget.y() > bottom
        bottom = widget.y()+widget.height()-1
        if isinstance(widget,QLabel):
            needed = widget.heightForWidth(widget.width()) if widget.hasHeightForWidth() else widget.sizeHint().height()
            assert widget.height() >= needed
    assert window.settings_scroll.verticalScrollBar().maximum() > 0
    assert window.start_button.isVisible()
    assert window.table.columnViewportPosition(5)+window.table.columnWidth(5) <= window.table.viewport().width()
