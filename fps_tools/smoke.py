"""Self-contained packaged application acceptance test; no installed tools needed."""
import json
import tempfile
from fractions import Fraction
from pathlib import Path

from .media import convert, inspect_media
from .process import engine_path, run_engine


def smoke(report_path):
    report = Path(report_path).resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="fps-tools-smoke-") as folder:
            src = Path(folder)/"sample.mp4"
            run_engine(["-y","-f","lavfi","-i","testsrc2=size=160x90:rate=24",
                        "-f","lavfi","-i","sine=frequency=440:sample_rate=48000",
                        "-t","10","-frames:v","240","-c:v","libx264","-bf","3","-c:a","aac",str(src)])
            result = convert(src, Fraction(30), Path(folder))
            info = inspect_media(result.path)
            assert info.frame_count == 240 and info.duration == 8 and info.fps == 30
            assert len(info.audio) == 1
            # Exercise Qt plugin loading in addition to the media pipeline.
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QCoreApplication, QEvent
            from .studio import StudioWindow
            app = QApplication.instance() or QApplication([])
            window = StudioWindow()
            window.show()
            app.processEvents()
            from .frame_plan import FramePlan
            from .frame_media import ExportSettings, export_frames, prepare_clip
            clip = prepare_clip(src,Path(folder)/"preview")
            plan = FramePlan.original(240,Fraction(24)).set_counts([0,2],0).increment([4],2)
            edited = export_frames(clip.info,plan,ExportSettings(),Path(folder))
            assert inspect_media(edited.path).frame_count == 240
            prores = export_frames(clip.info,plan,ExportSettings(codec="prores"),Path(folder))
            assert inspect_media(prores.path).codec == "prores"
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            data = {"ok": True, "frames": info.frame_count, "duration": float(info.duration),
                    "fps": str(info.fps), "video_sha256": result.video_hash, "engine": engine_path(),
                    "gui": "Studio and original tool created and shown", "editor": "H264 and ProRes exports verified"}
        report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        return 0
    except Exception as error:
        report.write_text(json.dumps({"ok":False,"error":str(error)},ensure_ascii=False,indent=2),encoding="utf-8")
        return 1
