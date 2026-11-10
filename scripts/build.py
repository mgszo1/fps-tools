"""Build a portable app, verify it without PATH tools, then produce a ZIP."""
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
from fps_tools import __version__


def make_icon():
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QPainter, QColor, QPolygonF
    img = QImage(1024,1024,QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#183724")); p.drawRoundedRect(32,32,960,960,220,220)
    for x, color in [(204,"#548a65"),(340,"#85c99b"),(476,"#c1fbd5")]:
        p.setBrush(QColor(color)); p.drawRoundedRect(x,260,98,504,30,30)
    p.setBrush(QColor("#c1fbd5"))
    p.drawPolygon(QPolygonF([QPointF(674,360),QPointF(850,512),QPointF(674,664)]))
    p.end()
    assets = ROOT/"assets"
    assets.mkdir(exist_ok=True)
    img.save(str(assets/"icon.png"))
    if sys.platform == "darwin":
        iconset=ROOT/"build/FPS Tools.iconset"
        iconset.mkdir(parents=True,exist_ok=True)
        for size in (16,32,128,256,512):
            for multiplier in (1,2):
                suffix="@2x" if multiplier==2 else ""
                img.scaled(size*multiplier,size*multiplier,Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation).save(str(iconset/f"icon_{size}x{size}{suffix}.png"))
        icon=ROOT/"build/app.icns"
        subprocess.run(["iconutil","-c","icns",str(iconset),"-o",str(icon)],check=True)
    else:
        icon=ROOT/"build/app.ico"
        icon.parent.mkdir(exist_ok=True)
        if not img.scaled(256,256).save(str(icon),"ICO"):
            raise RuntimeError("Cannot write app icon")
    return icon


def main():
    icon=make_icon()
    licenses=ROOT/"build/third-party"
    licenses.mkdir(parents=True,exist_ok=True)
    versions={}
    for name in ["av","PySide6-Essentials","shiboken6","imageio-ffmpeg","PyInstaller"]:
        dist=importlib.metadata.distribution(name)
        versions[name]=dist.version
        for item in dist.files or []:
            if "license" in str(item).lower() or "copying" in str(item).lower():
                src=Path(dist.locate_file(item))
                if src.is_file():
                    dst=licenses/name/str(item)
                    dst.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(src,dst)
    (licenses/"versions.json").write_text(json.dumps(versions,indent=2),encoding="utf-8")
    args=[sys.executable,"-m","PyInstaller","--noconfirm","--clean","--windowed","--onedir",
          "--name","FPS Tools","--specpath","build","--paths",str(ROOT),
          "--icon",str(icon),"--collect-all","av","--collect-data","imageio_ffmpeg",
          "--add-data",f"{ROOT/'assets'}{os.pathsep}assets",
          "--add-data",f"{ROOT/'licenses'}{os.pathsep}licenses",
          "--add-data",f"{licenses}{os.pathsep}third-party",
          "--add-data",f"{ROOT/'THIRD_PARTY_NOTICES.md'}{os.pathsep}.",
          "--exclude-module","pytest","--exclude-module","numpy","--exclude-module","tkinter",
          "--osx-bundle-identifier","com.mgszo1.fpstools","scripts/launch.py"]
    subprocess.run(args,check=True)
    if sys.platform=="darwin":
        app=ROOT/"dist/FPS Tools.app"
        exe=app/"Contents/MacOS/FPS Tools"
    else:
        app=ROOT/"dist/FPS Tools"
        exe=app/"FPS Tools.exe"
    report=ROOT/"dist/smoke-report.json"
    env=os.environ.copy()
    env["PATH"]="/usr/bin:/bin" if sys.platform=="darwin" else str(Path(os.environ["SystemRoot"])/"System32")
    env.pop("PYTHONPATH",None)
    env.pop("IMAGEIO_FFMPEG_EXE",None)
    env["QT_QPA_PLATFORM"]="offscreen"
    subprocess.run([str(exe),"--smoke-test",str(report)],check=True,env=env,timeout=120)
    data=json.loads(report.read_text(encoding="utf-8"))
    if not data.get("ok") or str(ROOT/".venv") in data.get("engine",""):
        raise RuntimeError(f"Packaged smoke test failed: {data}")
    print(json.dumps(data,ensure_ascii=False))
    arch="arm64" if platform.machine().lower() in {"arm64","aarch64"} else "x64"
    system="macOS" if sys.platform=="darwin" else "Windows"
    archive=ROOT/f"dist/FPS-Tools-{__version__}-{system}-{arch}.zip"
    if sys.platform=="darwin":
        subprocess.run(["ditto","-c","-k","--sequesterRsrc","--keepParent",str(app),str(archive)],check=True)
    else:
        shutil.copyfile(ROOT/"README.md",app/"使用说明.md")
        shutil.copyfile(ROOT/"THIRD_PARTY_NOTICES.md",app/"THIRD_PARTY_NOTICES.md")
        shutil.make_archive(str(archive.with_suffix("")),"zip",app.parent,app.name)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n",encoding="utf-8")
    print(f"Built and verified: {archive} ({archive.stat().st_size/1024/1024:.1f} MiB)")


if __name__=="__main__":
    main()
