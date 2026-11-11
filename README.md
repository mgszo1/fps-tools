# FPS Tools Studio 2.0 · 帧节奏工作室

逐帧删减、复制、安排停顿，再以指定帧率导出。Mac / Windows 本地工具，免安装 Python 和 FFmpeg，无上传、账号或遥测。

**稳定版 1.1.0 保留不变。** [下载原版帧率工具](https://github.com/mgszo1/fps-tools/releases/tag/v1.1.0)；Studio 是不同名称的独立应用，也保留“原帧率工具”标签页。

## 下载

在 [Releases](https://github.com/mgszo1/fps-tools/releases) 下载 `FPS-Tools-Studio-2.0.0-系统-架构.zip`，解压后运行：

| 系统 | 包名结尾 | 打开方式 |
|---|---|---|
| Mac M 系列 | macOS-arm64.zip | FPS Tools Studio.app |
| Mac Intel | macOS-x64.zip | FPS Tools Studio.app |
| Windows 64 位 | Windows-x64.zip | 整包解压，运行 FPS Tools Studio.exe，保留 _internal 文件夹 |

构建目标 macOS 14+ / Windows 10+，原生自动验证平台 macOS 15 / Windows Server 2022。应用未购买开发者签名和 Apple 公证，首次打开可能需要在系统安全设置中允许。

## 逐帧编辑

1. 打开或拖入一个视频。后台检查后，展开**原片缩影轴**与**结果缩影轴**。
2. 点击原片缩影查看对应画面。Ctrl / ⌘ / Shift 多选；“删除”设为 0 次，“复制 +1”增加一次，“恢复 ×1”恢复一次，也能直接设置次数。
3. 红色斜线表示删除，绿色 ×N 表示重复。结果轴就是最终播放顺序。复制的帧紧随原帧，形成停顿，不生成新画面、不插值。
4. “移给前帧 / 后帧”把选中帧的一次曝光交给邻帧，总帧数保持不变；可用它调整自动方案的取舍。支持最多 100 步撤销 / 重做。
5. 播放、逐帧前后移动或拖动进度条检查效果。画面预览使用最多 640 像素缓存，**最终导出重新读取原始画面和原始分辨率**。高负载下屏幕预览可能跳过刷新，但导出仍按每个曝光完整编码。
6. 保存 `.fpsedit` 工程，下次继续编辑。工程引用原视频，不包含视频本体；移动文件后可重新定位，载入时校验视频指纹。复制工程时请一起保管原片。

### 保持时长改帧率

勾选“保持原片时长”，设置 FPS，点击“自动分配删帧 / 重复帧”。

- 100 帧 / 24 fps → 12 fps：50 帧；→ 30 fps：125 帧，均保持 4.1667 秒。
- 自动方案均匀采样，不分析运动内容。你可以手动改变删帧或重复的选择。
- 不能整除时，目标帧数四舍五入（半帧向上），界面显示实际时长误差。
- 手动编辑可以暂时偏离目标；界面显示还需增加或删除多少帧，平衡后才可导出。
- 修改帧率或勾选模式不会自动覆盖已有取舍；重新自动分配可撤销。

### 编码与声音

| 选项 | 行为 |
|---|---|
| H.264 / MP4 | 默认目标平均码率 **100 Mbps**，可设 1–500 Mbps；实际码率随内容与编码器变化；4:2:0，源片 8 / 10 位对应输出 8 / 10 位 |
| ProRes 422 HQ / MOV | profile 3，10 位 4:2:2，按档位控制码率；不提供固定 Mbps 设置 |
| 整体变速，音调不变 | 原声音整体适配结果时长，不因画面复制而重复音频片段 |
| 原时间轴 | 保持原声音速度；超长裁切、不足补静音，自动等时长方案默认使用此项 |
| 静音 | 不输出音轨 |

新帧编辑模块**重新编码，不能宣称像素无损**。不缩放原片，不做插值。H.264 导出音频 AAC，ProRes 导出音频 PCM 24 位。声音预览使用第一条音轨，导出处理全部音轨。极端变速可能产生算法痕迹。

输出命名 `原名_edited_30fps.mp4` / `.mov`；重名自动编号，不覆盖原片。编码、音频和验证都可取消；失败时删除未完成文件。保存前检查帧数、帧率、尺寸及音轨数量。

## 当前边界

- 单视频轨、恒定帧率、完整时间轴；MP4 / MOV / MKV / AVI / WebM / M4V 需通过原片检查。标准 MOV 时间码轨可读，但帧编辑不沿用旧时间码，因为剪删后原时间码不再连续。
- 为避免隐性降级，帧编辑暂拒绝 HDR、透明通道、超过 10 位以及奇数宽高。需要只改帧率时，可使用原帧率工具。预览缩影不用于精度判断。
- 一个工程一个视频，按原顺序保留或重复帧，不提供跨片段拼接、任意重排、滤镜或光流。
- 每原始帧最多 10000 次，总原片帧数及输出帧数最多 100 万。长视频需生成磁盘预览缓存，关闭后清理；缓存和导出需要足够磁盘空间。
- 原帧率工具继续直接复制视频编码包，保留全帧、调整播放速度，详情见[原版说明](docs/原帧率工具-v1.1.md)。

## 开源技术取舍

研究了 [OpenShot libopenshot](https://github.com/OpenShot/libopenshot)、[MLT](https://github.com/mltframework/mlt) 与 [LosslessCut](https://github.com/mifi/lossless-cut)。前两者是完整剪辑框架，后者以片段级 stream copy 为主。此版本选择延续 [PyAV](https://github.com/PyAV-Org/PyAV)＋[Qt](https://doc.qt.io/qtforpython-6/)：用轻量曝光表表达每帧次数，直接控制每张源画面的输出时间，减少新增框架依赖；未复制上述编辑器的代码。

编码参考：[FFmpeg ProRes](https://ffmpeg.org/ffmpeg-codecs.html#ProRes)、[atempo](https://ffmpeg.org/ffmpeg-filters.html#atempo)。许可与运行库见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 开发 / 构建

```sh
python -m venv .venv
# 激活环境
python -m pip install -e ".[dev]"
python -m fps_tools
python -m pytest -q
python scripts/build.py
```

原生 CI 覆盖 Mac arm64 / Intel / Windows x64。打包测试清除开发环境 PATH，验证旧转换与 H.264、ProRes 帧编辑导出，并生成 ZIP + SHA-256。
