# 🎬 FFmpeg Ultimate Commander

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![GUI: Tkinter](https://img.shields.io/badge/GUI-Tkinter%20(Dark%20Theme)-blueviolet.svg)](https://docs.python.org/3/library/tkinter.html)
[![FFmpeg](https://img.shields.io/badge/Powered%20By-FFmpeg-green.svg)](https://ffmpeg.org/)
[![Hardware Acceleration](https://img.shields.io/badge/Hardware%20Accel-NVENC%20%7C%20QSV%20%7C%20AMF-orange.svg)](https://trac.ffmpeg.org/wiki/HWAccelIntro)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A professional, dark-themed desktop GUI for **FFmpeg** and **ffprobe**, designed for batch video transcoding, high-efficiency compression, format conversion, and media processing.

Features real-time background ffprobe metadata inspection, dynamic output size estimation, hardware-accelerated encoding, and multi-file queue execution with pause/resume support.

---

## ⚡ Master Feature Highlights

### 1. 📋 Accumulative Batch Queue & Live Size Estimation
* **Multi-Source Queue**: Add individual video files or scan entire directories recursively.
* **Background Metadata Extraction**: Automatically fetches duration, resolution, codec, and container information using `ffprobe`.
* **Live "Est. Size" Calculator**: Dynamically recalculates estimated output file sizes in real time whenever video codec, CRF, or target bitrate settings change.
* **Target File Size Mode**: Specify a target size in megabytes (MB) and the engine calculates the exact required video bitrate:  
  $$\text{Bitrate} = \frac{\text{Size (MB)} \times 8192}{\text{Duration (seconds)}} - \text{Audio Bitrate}$$

### 2. 🚀 Codecs & Hardware Acceleration
* **Modern Video Codecs**:
  * **H.264** (`libx264`)
  * **H.265 / HEVC** (`libx265`)
  * **AV1** (`libsvtav1`)
  * **Google VP9** (`libvpx-vp9`)
  * **Apple ProRes** (`prores_ks`)
  * **Avid DNxHD** (`dnxhd`)
  * **Stream Copy** (Instant remux without re-encoding)
* **Hardware Acceleration**:
  * 🟢 **NVIDIA NVENC** (`h264_nvenc`, `hevc_nvenc`)
  * 🔵 **Intel QSV** (`h264_qsv`, `hevc_qsv`)
  * 🔴 **AMD AMF** (`h264_amf`, `hevc_amf`)
  * ⚪ **Apple VideoToolbox** (`h264_videotoolbox`, `hevc_videotoolbox`)

### 3. 🔊 Audio Processing & Normalization
* **Audio Codecs**: AAC, MP3 (`libmp3lame`), Opus (`libopus`), AC3 Dolby, FLAC Lossless, PCM/WAV uncompressed, or strip audio track completely.
* **Channels**: Original, Stereo (2.0), Mono (1.0), or 5.1 Surround.
* **Sample Rates**: 44.1 kHz (Music), 48.0 kHz (Broadcast Video), or 96.0 kHz (Hi-Res).

### 4. 🎛️ Video Filters & Transforms
* **Resolution Scaling**: 4K (2160p), 1440p, 1080p, 720p, 480p, 360p with customizable algorithms (Lanczos, Bicubic, Bilinear, Spline).
* **Geometry**: Rotate 90° CW/CCW, 180°, or Horizontal/Vertical flip.
* **Timing & Speed**: Speed up or slow down video (0.25x to 4x) and timecode trimming (Start / End offsets).

### 5. ⚙️ Advanced Stream Settings
* **Faststart (`+faststart`)**: Automatically places MP4 `moov atom` at the beginning of the file for instant web playback and streaming.
* **Pixel Formats**: 8-bit `yuv420p`, 10-bit HDR `yuv420p10le`, or pass-through.
* **Custom Flags**: Inject arbitrary FFmpeg parameters directly into the encoding pipeline.

---

## 📂 Repository Structure

```
FFmpeg-Ultimate-Commander/
├── ffmpeg_gui.py          # Primary application source code (1,300+ lines)
├── run_commander.bat      # 1-Click Windows application launcher
├── requirements.txt       # Optional dependencies (psutil)
├── .gitignore
├── LICENSE                # MIT License
└── README.md
```

---

## 🚀 Quick Start Guide

### 1. Requirements
* **Python 3.10+** (Tkinter comes pre-installed with standard Python on Windows/macOS)
* **FFmpeg & ffprobe**: Installed on your system PATH, or placed directly in the application folder / `bin/` directory.

### 2. Installation
Clone the repository:

```bash
git clone https://github.com/inshalstratrum/FFmpeg-Ultimate-Commander.git
cd FFmpeg-Ultimate-Commander
pip install -r requirements.txt
```

### 3. Run the Commander
Double-click `run_commander.bat`, or run via terminal:

```bash
python ffmpeg_gui.py
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
FFmpeg is a trademark of Fabrice Bellard and the FFmpeg development team.
