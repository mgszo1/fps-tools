# FPS Tools · 帧率小工具

换个帧率，每一帧都在。Mac / Windows 本地视频改帧率工具。

**10 秒 × 24 fps = 240 帧 → 30 fps → 8 秒，仍然是原来的 240 帧。**

视频画面不重编码、不压缩、不增减帧、不插值。声音同步变速并保持音调；音频必须处理和重新编码，因此音频不宣称无损。

## 下载与使用

从 [Releases](https://github.com/mgszo1/fps-tools/releases/latest) 下载对应系统 ZIP，解压即可使用。无需安装 Python、FFmpeg 或其他依赖，无需联网。

| 系统 | 下载包 | 打开方式 |
|---|---|---|
| Mac Apple Silicon（M 系列）| `macOS-arm64.zip` | 双击 `FPS Tools.app` |
| Mac Intel | `macOS-x64.zip` | 双击 `FPS Tools.app` |
| Windows 10/11 64 位 | `Windows-x64.zip` | 解压整个文件夹，双击 `FPS Tools.exe`，请保留旁边的 `_internal` 文件夹 |

当前构建以 macOS 14+ / Windows 10+ 为目标；自动验证运行于 macOS 15 和 Windows Server 2022，较早系统未逐台实测。当前没有开发者证书签名/Apple 公证；下载后首次运行可能出现系统安全提示。Mac 可在系统设置的“隐私与安全性”检查并允许本次打开；Windows 可查看文件来源后决定是否运行。免安装不等于免系统安全检查。

1. 拖入视频，或点击“选择视频文件”。支持批量添加。
2. 等待检查帧数，选择/输入目标帧率，查看导出时长。
3. 点击“开始导出”。成功后点击“打开输出文件夹”。

输出默认位于原视频旁边，例如 `片段_30fps.mp4`。重名会自动编号，源文件不覆盖。支持取消；已经完成的文件保留，未完成输出会清理。

## 无损如何保证

- 原视频编码包直接复制，仅调整播放时间戳和包时长。
- 转换前后完整扫描，核对实际解码帧数、编码包顺序及 SHA-256、编码参数和画面属性。
- 校验目标帧率和时间戳是否均匀，只有全部通过才保存正式输出。
- 没有“失败后自动转码”的后备路径。完整扫描需要时间，4K/长视频会比单纯复制慢；界面任务始终在后台运行。

格式和编码不变，容器的索引/时间信息会重新写入，文件大小或整体文件哈希不必相同；由于播放更快，每秒码率变高也不代表重新压缩。

## 音频与支持范围

- 采用 FFmpeg `atempo` 分段变速，保持音调，音轨的相对延迟同步缩放；尾部适配视频长度。极端速度仍可能产生听感变化，不能承诺完全没有算法痕迹。
- 尽量保留原音频编码，AAC 使用每声道 192 kb/s、最高 768 kb/s。支持 AAC、MP3、Opus、Vorbis、AC-3/E-AC-3、FLAC、ALAC 和 FFmpeg 支持的 PCM。原编码不能写回原容器时明确报错。
- 目标范围 1–240 fps；预设 `23.976`、`29.97`、`59.94` 对应 `24000/1001`、`30000/1001`、`60000/1001`，并非近似的小数。
- 候选容器：MP4、MOV、M4V、MKV、AVI、WebM。支持恒定帧率、单视频轨道和多个音轨；具体编码组合须通过校验。
- 变帧率、缺失/异常时间戳、损坏文件、字幕/章节/数据轨道、多视频轨道会明确拒绝。带 timecode 数据轨道的专业 MOV 也在此限制内，避免静默丢弃信息。
- 所有处理在本机完成，无上传、账号或遥测。没有联网自动更新，后续版本在本仓库发布。

## 开发与构建

```bash
python -m venv .venv
# 激活虚拟环境后：
python -m pip install -e ".[dev]"
python -m fps_tools
python -m pytest -q
python scripts/build.py
```

构建脚本生成自包含应用，在隔离 PATH 下运行真实 240 帧 → 8 秒的打包冒烟测试，并生成 ZIP 与 SHA-256。GitHub Actions 分别在 Mac arm64、Mac Intel、Windows x64 原生环境执行测试和打包。

技术参考：[FFmpeg stream copy](https://ffmpeg.org/ffmpeg.html#Streamcopy)、[音频变速](https://ffmpeg.org/ffmpeg-filters.html#atempo)、[PyAV](https://pyav.org/)、[Qt for Python](https://doc.qt.io/qtforpython-6/)。第三方组件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
