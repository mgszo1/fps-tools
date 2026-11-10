# Third-party components

FPS Tools source code is available in this repository. Portable distributions bundle unmodified third-party runtimes and libraries with their own licenses; those licenses are independent of the application source license.

| Component | Version | License / source |
|---|---|---|
| CPython | 3.11 | PSF License; https://github.com/python/cpython/tree/3.11 |
| PySide6 Essentials / Shiboken6 / Qt | 6.12.0 | LGPL-3.0 / GPL alternatives; https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/qtbase.git/ |
| PyAV | 18.1.0 | BSD-3-Clause; https://github.com/PyAV-Org/PyAV/tree/v18.1.0 |
| imageio-ffmpeg wrapper | 0.8.1 | BSD-2-Clause; https://github.com/imageio/imageio-ffmpeg/tree/v0.8.1 |
| FFmpeg executable | Platform wheel supplied by imageio-ffmpeg | GPL build; see `ffmpeg -version` / `ffmpeg -L` for build configuration and license. https://ffmpeg.org/download.html ; upstream packaging sources https://github.com/imageio/imageio-ffmpeg/tree/v0.8.1/tools |
| FFmpeg libraries used by PyAV | Wheel supplied by PyAV | FFmpeg license according to library configuration; https://github.com/PyAV-Org/PyAV and https://github.com/PyAV-Org/pyav-ffmpeg |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with bootloader exception; https://github.com/pyinstaller/pyinstaller |

License texts and available wheel license notices are included under `licenses/` and `third-party/` inside the portable app. Qt and PyAV remain separate dynamically linked libraries; the FFmpeg executable is invoked as a separate process. The executable and libraries can be replaced by compatible builds (macOS may require re-signing a modified application). No third-party trademark ownership is claimed.

The application does not enable a video encoder for exports. Video encoders are used only by development/packaged smoke tests to generate synthetic test fixtures.
