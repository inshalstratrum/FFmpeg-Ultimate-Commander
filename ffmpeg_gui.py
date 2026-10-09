#!/usr/bin/env python3
"""
FFmpeg Ultimate Commander - A professional, dark-themed tkinter GUI for FFmpeg.

Tabs:
  1. Input & Queue  - batch queue, output folder, progress
  2. Video          - encoders, hardware accel, rate control (CRF/CBR/VBR/CQP/Target Size)
  3. Audio          - codecs, bitrate, channels, sample rate, volume, normalization
  4. Filters        - scale, crop, rotate, denoise, sharpen, deinterlace, color eq, speed, trim
  5. Advanced       - container, pixel format, metadata, faststart, custom flags

Features:
  - Accumulative multi-source queue (files + recursive folders)
  - ffprobe metadata (resolution / duration / size) fetched in background
  - Per-file "Est. Size" column, live-updated when settings change
  - Target File Size mode: bitrate = (Size_MB * 8192) / Duration_Seconds - audio
  - START / PAUSE / STOP batch controls (pause uses SIGSTOP on Unix, psutil on Windows)
  - Threaded execution with real-time FFmpeg log + per-file and overall progress bars
  - Graceful error handling for missing ffmpeg/ffprobe or bad files

Requirements: ffmpeg + ffprobe on PATH. Optional: psutil (for Pause on Windows).
"""

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import psutil  # optional, enables Pause on Windows
except ImportError:
    psutil = None

IS_WINDOWS = sys.platform.startswith("win")

# ----------------------------------------------------------------------------
# Theme constants
# ----------------------------------------------------------------------------
BG = "#1e1e2e"
BG_PANEL = "#27273a"
BG_INPUT = "#313148"
FG = "#e0e0e8"
FG_DIM = "#9a9ab0"
ACCENT = "#4f9cf9"
ACCENT_DARK = "#3a7bd5"
SUCCESS = "#4caf7d"
WARNING = "#d99a3d"
ERROR = "#e05a5a"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_SMALL = ("Segoe UI", 9)

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v",
              ".mpg", ".mpeg", ".ts", ".m2ts", ".vob", ".3gp", ".ogv", ".mxf"}

# ----------------------------------------------------------------------------
# Encoder / codec tables
# ----------------------------------------------------------------------------
# encoder label -> (software encoder, {hw mode: hw encoder})
VIDEO_ENCODERS = {
    "H.264 (libx264)":        ("libx264",   {"NVIDIA": "h264_nvenc", "Intel": "h264_qsv", "AMD": "h264_amf", "Apple": "h264_videotoolbox"}),
    "H.265 / HEVC (libx265)": ("libx265",   {"NVIDIA": "hevc_nvenc", "Intel": "hevc_qsv", "AMD": "hevc_amf", "Apple": "hevc_videotoolbox"}),
    "AV1 (libsvtav1)":        ("libsvtav1", {}),
    "VP9 (libvpx-vp9)":       ("libvpx-vp9", {}),
    "ProRes (prores_ks)":     ("prores_ks", {}),
    "DNxHD (dnxhd)":          ("dnxhd",     {}),
    "Copy (no re-encode)":    ("copy",      {}),
}

# rough compression-efficiency factor relative to x264 (for size estimation)
CODEC_EFFICIENCY = {
    "libx264": 1.00, "libx265": 0.60, "libsvtav1": 0.50, "libvpx-vp9": 0.65,
    "prores_ks": 12.0, "dnxhd": 10.0,
    "h264_nvenc": 1.15, "hevc_nvenc": 0.70, "h264_qsv": 1.15, "hevc_qsv": 0.70,
    "h264_amf": 1.15, "hevc_amf": 0.70, "h264_videotoolbox": 1.15, "hevc_videotoolbox": 0.70,
}

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
           "medium", "slow", "slower", "veryslow"]

AUDIO_CODECS = {
    "Copy (passthrough)": "copy",
    "AAC (standard)": "aac",
    "MP3 (libmp3lame)": "libmp3lame",
    "Opus (best low bitrate)": "libopus",
    "AC3 (Dolby)": "ac3",
    "FLAC (lossless)": "flac",
    "PCM / WAV (uncompressed)": "pcm_s16le",
    "Remove audio": "none",
}

AUDIO_BITRATES = ["320k", "256k", "192k", "160k", "128k", "96k", "64k", "48k"]
AUDIO_CHANNELS = {"Original": None, "Stereo (2.0)": "2", "Mono (1.0)": "1", "5.1 Surround": "6"}
SAMPLE_RATES = {"Original": None, "44100 Hz (Music)": "44100", "48000 Hz (Video)": "48000", "96000 Hz (Hi-Res)": "96000"}

RESOLUTIONS = {
    "Original": None,
    "4K (2160p)": "3840:-2",
    "1440p": "2560:-2",
    "1080p": "1920:-2",
    "720p": "1280:-2",
    "480p": "854:-2",
    "360p": "640:-2",
}
SCALE_ALGOS = ["bicubic", "lanczos", "bilinear", "spline", "neighbor"]

ROTATIONS = {
    "No change": None,
    "Rotate 90 CW": "transpose=1",
    "Rotate 90 CCW": "transpose=2",
    "Rotate 180": "transpose=1,transpose=1",
    "Flip Horizontal": "hflip",
    "Flip Vertical": "vflip",
}

SPEEDS = {
    "Normal (1x)": None,
    "0.5x (Slow)": 0.5,
    "0.75x": 0.75,
    "1.25x": 1.25,
    "1.5x": 1.5,
    "2x (Fast)": 2.0,
}

CONTAINERS = ["mp4", "mkv", "mov", "webm", "avi", "gif"]
PIX_FMTS = {
    "Auto": None,
    "yuv420p (standard, plays everywhere)": "yuv420p",
    "yuv420p10le (10-bit HDR-ready)": "yuv420p10le",
    "yuv444p (full chroma, editing)": "yuv444p",
    "gbrp (RGB, screencasts)": "gbrp",
}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def human_size(num_bytes):
    if num_bytes is None:
        return "?"
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_duration(seconds):
    if not seconds:
        return "?"
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def parse_timecode(text):
    """HH:MM:SS(.ms) or seconds -> float seconds, or None."""
    text = text.strip()
    if not text:
        return None
    try:
        if ":" in text:
            parts = [float(p) for p in text.split(":")]
            secs = 0.0
            for p in parts:
                secs = secs * 60 + p
            return secs
        return float(text)
    except ValueError:
        return None


class ToolTip:
    """Simple hover tooltip for any widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def show(self, _event=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip, text=self.text, justify="left", bg="#111120",
                         fg=FG, relief="solid", borderwidth=1, font=FONT_SMALL,
                         wraplength=360, padx=8, pady=6)
        label.pack()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def help_badge(parent, text):
    lbl = tk.Label(parent, text="[?]", bg=parent["bg"] if "bg" in parent.keys() else BG_PANEL,
                   fg=ACCENT, font=FONT_SMALL, cursor="question_arrow")
    ToolTip(lbl, text)
    return lbl


class QueueItem:
    __slots__ = ("path", "size", "duration", "width", "height", "fps",
                 "status", "iid", "est_size")

    def __init__(self, path):
        self.path = path
        self.size = None
        self.duration = None
        self.width = None
        self.height = None
        self.fps = None
        self.status = "Probing..."
        self.est_size = None
        self.iid = None


# ----------------------------------------------------------------------------
# Main application
# ----------------------------------------------------------------------------
class UltimateCommander(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FFmpeg Ultimate Commander")
        self.geometry("1120x820")
        self.minsize(960, 700)
        self.configure(bg=BG)

        self.items = []            # list[QueueItem]
        self.items_lock = threading.Lock()
        self.worker = None
        self.current_proc = None
        self.stop_requested = False
        self.paused = False

        script_dir = os.path.dirname(os.path.abspath(__file__))
        bin_dir = os.path.join(script_dir, "bin")
        if os.path.isfile(os.path.join(script_dir, "ffmpeg.exe")) or os.path.isfile(os.path.join(script_dir, "ffmpeg")):
            os.environ["PATH"] = script_dir + os.pathsep + os.environ.get("PATH", "")
        elif os.path.isfile(os.path.join(bin_dir, "ffmpeg.exe")) or os.path.isfile(os.path.join(bin_dir, "ffmpeg")):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

        self.ffmpeg_ok = shutil.which("ffmpeg") is not None
        self.ffprobe_ok = shutil.which("ffprobe") is not None

        self._setup_style()
        self._build_ui()

        if not self.ffmpeg_ok or not self.ffprobe_ok:
            self.log("WARNING: ffmpeg/ffprobe not found on PATH. "
                     "Install FFmpeg and restart.", tag="err")

    # ------------------------------------------------------------------ style
    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=FONT)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_PANEL, foreground=FG_DIM,
                        padding=(18, 8), font=FONT_BOLD)
        style.map("TNotebook.Tab",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG_PANEL, foreground=FG)
        style.configure("Dim.TLabel", background=BG_PANEL, foreground=FG_DIM, font=FONT_SMALL)
        style.configure("Title.TLabel", background=BG_PANEL, foreground=FG, font=FONT_TITLE)
        style.configure("TButton", background=BG_INPUT, foreground=FG, borderwidth=0,
                        focusthickness=0, padding=(12, 6))
        style.map("TButton", background=[("active", ACCENT_DARK)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=FONT_BOLD, padding=(18, 10))
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", BG_INPUT)])
        style.configure("Stop.TButton", background=ERROR, foreground="#ffffff",
                        font=FONT_BOLD, padding=(18, 10))
        style.map("Stop.TButton", background=[("active", "#b84848"), ("disabled", BG_INPUT)])
        style.configure("Pause.TButton", background="#d99a3d", foreground="#ffffff",
                        font=FONT_BOLD, padding=(18, 10))
        style.map("Pause.TButton", background=[("active", "#b57f30"), ("disabled", BG_INPUT)])
        style.configure("TCheckbutton", background=BG_PANEL, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG_PANEL)])
        style.configure("TRadiobutton", background=BG_PANEL, foreground=FG)
        style.map("TRadiobutton", background=[("active", BG_PANEL)])
        style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_INPUT,
                        foreground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", BG_INPUT)])
        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG,
                        insertcolor=FG, borderwidth=0)
        style.configure("Horizontal.TScale", background=BG_PANEL, troughcolor=BG_INPUT)
        style.configure("TProgressbar", background=ACCENT, troughcolor=BG_INPUT,
                        borderwidth=0, thickness=14)
        style.configure("Treeview", background=BG_INPUT, fieldbackground=BG_INPUT,
                        foreground=FG, rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=BG_PANEL, foreground=FG,
                        font=FONT_BOLD, borderwidth=0)
        style.map("Treeview", background=[("selected", ACCENT_DARK)])
        self.option_add("*TCombobox*Listbox.background", BG_INPUT)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    # --------------------------------------------------------------------- UI
    def _build_ui(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(header, text="FFmpeg Ultimate Commander", bg=BG, fg=FG,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(header, text="batch video compression & conversion studio",
                 bg=BG, fg=FG_DIM, font=FONT_SMALL).pack(side="left", padx=12, pady=(6, 0))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=4)

        self.tab_queue = ttk.Frame(self.nb, style="Panel.TFrame", padding=12)
        self.tab_video = ttk.Frame(self.nb, style="Panel.TFrame", padding=12)
        self.tab_audio = ttk.Frame(self.nb, style="Panel.TFrame", padding=12)
        self.tab_filters = ttk.Frame(self.nb, style="Panel.TFrame", padding=12)
        self.tab_adv = ttk.Frame(self.nb, style="Panel.TFrame", padding=12)
        self.nb.add(self.tab_queue, text=" Input & Queue ")
        self.nb.add(self.tab_video, text=" Video ")
        self.nb.add(self.tab_audio, text=" Audio ")
        self.nb.add(self.tab_filters, text=" Filters ")
        self.nb.add(self.tab_adv, text=" Advanced ")

        self._build_queue_tab()
        self._build_video_tab()
        self._build_audio_tab()
        self._build_filters_tab()
        self._build_advanced_tab()
        self._build_bottom_bar()

        # re-estimate whenever the user returns to the queue tab
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.update_estimates())

    # ------------------------------------------------------------ Tab 1: queue
    def _build_queue_tab(self):
        t = self.tab_queue

        btns = tk.Frame(t, bg=BG_PANEL)
        btns.pack(fill="x")
        ttk.Button(btns, text="+ Add Files", command=self.add_files).pack(side="left")
        ttk.Button(btns, text="+ Add Folder (Recursive)", command=self.add_folder).pack(side="left", padx=6)
        ttk.Button(btns, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Clear Queue", command=self.clear_queue).pack(side="left")
        ttk.Button(btns, text="Refresh Estimates", command=self.update_estimates).pack(side="right")

        cols = ("file", "res", "dur", "size", "est", "status")
        self.tree = ttk.Treeview(t, columns=cols, show="headings", selectmode="extended")
        headings = {"file": "Filename", "res": "Resolution", "dur": "Duration",
                    "size": "Size", "est": "Est. Size", "status": "Status"}
        widths = {"file": 360, "res": 100, "dur": 90, "size": 90, "est": 100, "status": 140}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="w" if c == "file" else "center")
        vsb = ttk.Scrollbar(t, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="top", fill="both", expand=True, pady=(10, 4))
        vsb.place(relx=1.0, rely=0.5, relheight=0.7, anchor="e")

        out = tk.Frame(t, bg=BG_PANEL)
        out.pack(fill="x", pady=(8, 0))
        self.var_same_folder = tk.BooleanVar(value=True)
        ttk.Checkbutton(out, text="Save in source folder (adds _compressed suffix)",
                        variable=self.var_same_folder,
                        command=self._toggle_outdir).pack(side="left")
        tk.Label(out, text="   Output Folder:", bg=BG_PANEL, fg=FG, font=FONT).pack(side="left")
        self.var_outdir = tk.StringVar()
        self.ent_outdir = ttk.Entry(out, textvariable=self.var_outdir, width=42, state="disabled")
        self.ent_outdir.pack(side="left", padx=6)
        self.btn_browse_out = ttk.Button(out, text="Browse", command=self.pick_outdir, state="disabled")
        self.btn_browse_out.pack(side="left")

    def _toggle_outdir(self):
        state = "disabled" if self.var_same_folder.get() else "normal"
        self.ent_outdir.configure(state=state)
        self.btn_browse_out.configure(state=state)

    def pick_outdir(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.var_outdir.set(d)

    # ------------------------------------------------------------ Tab 2: video
    def _build_video_tab(self):
        t = self.tab_video
        left = tk.Frame(t, bg=BG_PANEL)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = tk.Frame(t, bg=BG_PANEL)
        right.pack(side="left", fill="both", expand=True)

        # --- Encoder
        row = tk.Frame(left, bg=BG_PANEL); row.pack(fill="x", pady=4)
        tk.Label(row, text="Video Encoder", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "libx264 = compatibility. libx265 = max compression. "
                        "AV1 = best compression, slower. VP9 = YouTube standard. "
                        "ProRes/DNxHD = editing/broadcast (huge files). "
                        "Copy = remux without re-encoding.").pack(side="left", padx=6)
        self.var_encoder = tk.StringVar(value="H.265 / HEVC (libx265)")
        cb = ttk.Combobox(left, textvariable=self.var_encoder, state="readonly",
                          values=list(VIDEO_ENCODERS.keys()), width=32)
        cb.pack(anchor="w", pady=(0, 8))
        cb.bind("<<ComboboxSelected>>", lambda e: self.update_estimates())

        # --- Hardware accel
        row = tk.Frame(left, bg=BG_PANEL); row.pack(fill="x", pady=(6, 2))
        tk.Label(row, text="Hardware Acceleration", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "GPU encoding is much faster but slightly lower quality per bitrate. "
                        "NVENC = NVIDIA, QSV = Intel, AMF = AMD, VideoToolbox = Apple Silicon. "
                        "Only applies to H.264/H.265.").pack(side="left", padx=6)
        self.var_hw = tk.StringVar(value="CPU")
        hwf = tk.Frame(left, bg=BG_PANEL); hwf.pack(anchor="w")
        for lbl in ("CPU", "NVIDIA", "Intel", "AMD", "Apple"):
            ttk.Radiobutton(hwf, text=lbl, value=lbl, variable=self.var_hw,
                            command=self.update_estimates).pack(side="left", padx=(0, 10))

        # --- Preset
        row = tk.Frame(left, bg=BG_PANEL); row.pack(fill="x", pady=(12, 2))
        tk.Label(row, text="Preset (speed vs. compression)", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "Slower presets compress better (smaller files at same quality) "
                        "but take longer. 'medium' is a good default.").pack(side="left", padx=6)
        self.var_preset_idx = tk.IntVar(value=5)
        self.lbl_preset = tk.Label(left, text="medium", bg=BG_PANEL, fg=ACCENT, font=FONT_BOLD)
        self.lbl_preset.pack(anchor="w")
        sc = ttk.Scale(left, from_=0, to=len(PRESETS) - 1, orient="horizontal",
                       variable=self.var_preset_idx, command=self._preset_changed)
        sc.pack(fill="x", pady=(0, 8))

        # --- Rate control
        row = tk.Frame(right, bg=BG_PANEL); row.pack(fill="x", pady=4)
        tk.Label(row, text="Rate Control Mode", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "CRF: constant quality (recommended). "
                        "Target Size: hit an exact output file size. "
                        "VBR: target average bitrate, allow peaks. "
                        "CBR: flat bitrate (streaming). "
                        "CQP: constant quantizer (archival).").pack(side="left", padx=6)
        self.var_rc = tk.StringVar(value="CRF")
        rcf = tk.Frame(right, bg=BG_PANEL); rcf.pack(anchor="w")
        for lbl in ("CRF", "Target Size", "VBR", "CBR", "CQP"):
            ttk.Radiobutton(rcf, text=lbl, value=lbl, variable=self.var_rc,
                            command=self._rc_changed).pack(side="left", padx=(0, 8))

        # CRF slider
        self.frm_crf = tk.Frame(right, bg=BG_PANEL)
        self.frm_crf.pack(fill="x", pady=(10, 0))
        crow = tk.Frame(self.frm_crf, bg=BG_PANEL); crow.pack(fill="x")
        tk.Label(crow, text="CRF / Quality", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(crow, "Lower = better quality, bigger file. 0 = lossless, 51 = worst. "
                         "Sane range: 18-28 for x264, 22-30 for x265/AV1.").pack(side="left", padx=6)
        self.var_crf = tk.IntVar(value=24)
        self.lbl_crf = tk.Label(self.frm_crf, text="24", bg=BG_PANEL, fg=ACCENT, font=FONT_BOLD)
        self.lbl_crf.pack(anchor="w")
        ttk.Scale(self.frm_crf, from_=0, to=51, orient="horizontal", variable=self.var_crf,
                  command=self._crf_changed).pack(fill="x")

        # Target size entry
        self.frm_target = tk.Frame(right, bg=BG_PANEL)
        trow = tk.Frame(self.frm_target, bg=BG_PANEL); trow.pack(fill="x")
        tk.Label(trow, text="Target File Size (MB per file)", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(trow, "Video bitrate is auto-calculated per file: "
                         "(Size_MB * 8192 / duration_seconds) minus audio bitrate. "
                         "Uses two-pass style single-pass -b:v with maxrate/bufsize.").pack(side="left", padx=6)
        self.var_target_mb = tk.StringVar(value="100")
        e = ttk.Entry(self.frm_target, textvariable=self.var_target_mb, width=10)
        e.pack(anchor="w", pady=4)
        e.bind("<KeyRelease>", lambda ev: self.update_estimates())

        # Bitrate entry (VBR/CBR)
        self.frm_bitrate = tk.Frame(right, bg=BG_PANEL)
        brow = tk.Frame(self.frm_bitrate, bg=BG_PANEL); brow.pack(fill="x")
        tk.Label(brow, text="Video Bitrate (e.g. 4000k or 4M)", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(brow, "VBR: -b:v target with peaks allowed. "
                         "CBR: adds -maxrate/-minrate/-bufsize for a flat rate.").pack(side="left", padx=6)
        self.var_bitrate = tk.StringVar(value="4000k")
        e2 = ttk.Entry(self.frm_bitrate, textvariable=self.var_bitrate, width=12)
        e2.pack(anchor="w", pady=4)
        e2.bind("<KeyRelease>", lambda ev: self.update_estimates())

        # CQP entry
        self.frm_cqp = tk.Frame(right, bg=BG_PANEL)
        qrow = tk.Frame(self.frm_cqp, bg=BG_PANEL); qrow.pack(fill="x")
        tk.Label(qrow, text="QP value (0-51)", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(qrow, "Constant quantizer. Every frame gets the same quantization "
                         "(-qp). Mostly for archives/tests.").pack(side="left", padx=6)
        self.var_qp = tk.StringVar(value="23")
        ttk.Entry(self.frm_cqp, textvariable=self.var_qp, width=8).pack(anchor="w", pady=4)

        self._rc_changed()

    def _preset_changed(self, _v=None):
        self.lbl_preset.config(text=PRESETS[int(self.var_preset_idx.get())])
        self.update_estimates()

    def _crf_changed(self, _v=None):
        self.lbl_crf.config(text=str(int(self.var_crf.get())))
        self.update_estimates()

    def _rc_changed(self):
        for f in (self.frm_crf, self.frm_target, self.frm_bitrate, self.frm_cqp):
            f.pack_forget()
        rc = self.var_rc.get()
        if rc == "CRF":
            self.frm_crf.pack(fill="x", pady=(10, 0))
        elif rc == "Target Size":
            self.frm_target.pack(fill="x", pady=(10, 0))
        elif rc in ("VBR", "CBR"):
            self.frm_bitrate.pack(fill="x", pady=(10, 0))
        elif rc == "CQP":
            self.frm_cqp.pack(fill="x", pady=(10, 0))
        self.update_estimates()

    # ------------------------------------------------------------ Tab 3: audio
    def _build_audio_tab(self):
        t = self.tab_audio
        grid = tk.Frame(t, bg=BG_PANEL)
        grid.pack(anchor="nw", fill="x")

        def labeled(row_i, text, tip):
            f = tk.Frame(grid, bg=BG_PANEL)
            f.grid(row=row_i, column=0, sticky="w", pady=(8, 2))
            tk.Label(f, text=text, bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
            help_badge(f, tip).pack(side="left", padx=6)

        labeled(0, "Audio Codec", "AAC = standard. Opus = best at low bitrates. "
                                  "FLAC/WAV = lossless (big). AC3 = Dolby surround. "
                                  "Copy = keep original untouched.")
        self.var_acodec = tk.StringVar(value="AAC (standard)")
        cb = ttk.Combobox(grid, textvariable=self.var_acodec, state="readonly",
                          values=list(AUDIO_CODECS.keys()), width=30)
        cb.grid(row=1, column=0, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self.update_estimates())

        labeled(2, "Audio Bitrate", "Higher = better sound quality, bigger file. "
                                    "128-192k AAC is transparent for most content. "
                                    "Ignored for lossless codecs.")
        self.var_abitrate = tk.StringVar(value="128k")
        cb2 = ttk.Combobox(grid, textvariable=self.var_abitrate, state="readonly",
                           values=AUDIO_BITRATES, width=10)
        cb2.grid(row=3, column=0, sticky="w")
        cb2.bind("<<ComboboxSelected>>", lambda e: self.update_estimates())

        labeled(4, "Channels", "Stereo downmix (-ac 2) shrinks 5.1 audio. "
                               "Mono (-ac 1) halves audio size again.")
        self.var_channels = tk.StringVar(value="Original")
        ttk.Combobox(grid, textvariable=self.var_channels, state="readonly",
                     values=list(AUDIO_CHANNELS.keys()), width=18).grid(row=5, column=0, sticky="w")

        labeled(6, "Sample Rate", "48 kHz is the video standard, 44.1 kHz for music. "
                                  "Leave Original unless you have a reason.")
        self.var_srate = tk.StringVar(value="Original")
        ttk.Combobox(grid, textvariable=self.var_srate, state="readonly",
                     values=list(SAMPLE_RATES.keys()), width=22).grid(row=7, column=0, sticky="w")

        labeled(8, "Volume", "100% = unchanged. 200% doubles loudness "
                             "(-filter:a volume=2.0). Applied before normalization.")
        self.var_volume = tk.IntVar(value=100)
        self.lbl_vol = tk.Label(grid, text="100%", bg=BG_PANEL, fg=ACCENT, font=FONT_BOLD)
        self.lbl_vol.grid(row=9, column=0, sticky="w")
        ttk.Scale(grid, from_=10, to=300, orient="horizontal", variable=self.var_volume,
                  length=300, command=lambda v: self.lbl_vol.config(
                      text=f"{int(self.var_volume.get())}%")).grid(row=10, column=0, sticky="w")

        nf = tk.Frame(grid, bg=BG_PANEL)
        nf.grid(row=11, column=0, sticky="w", pady=(14, 0))
        self.var_normalize = tk.BooleanVar(value=False)
        ttk.Checkbutton(nf, text="Normalize Loudness (EBU R128 / loudnorm)",
                        variable=self.var_normalize).pack(side="left")
        help_badge(nf, "Applies the loudnorm filter to hit -14 LUFS (streaming standard). "
                       "Fixes 'this video is way too quiet/loud' problems.").pack(side="left", padx=6)

    # ---------------------------------------------------------- Tab 4: filters
    def _build_filters_tab(self):
        t = self.tab_filters
        left = tk.Frame(t, bg=BG_PANEL); left.pack(side="left", fill="both", expand=True, padx=(0, 12))
        right = tk.Frame(t, bg=BG_PANEL); right.pack(side="left", fill="both", expand=True)

        def section(parent, text, tip):
            f = tk.Frame(parent, bg=BG_PANEL); f.pack(fill="x", pady=(10, 2), anchor="w")
            tk.Label(f, text=text, bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
            help_badge(f, tip).pack(side="left", padx=6)

        # Resolution
        section(left, "Resolution / Scale", "Downscaling is the single biggest file-size win. "
                                            "-2 keeps aspect ratio and even dimensions.")
        rf = tk.Frame(left, bg=BG_PANEL); rf.pack(anchor="w")
        self.var_res = tk.StringVar(value="Original")
        cb = ttk.Combobox(rf, textvariable=self.var_res, state="readonly",
                          values=list(RESOLUTIONS.keys()), width=14)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.update_estimates())
        tk.Label(rf, text="  Algo:", bg=BG_PANEL, fg=FG_DIM).pack(side="left")
        self.var_scale_algo = tk.StringVar(value="lanczos")
        ttk.Combobox(rf, textvariable=self.var_scale_algo, state="readonly",
                     values=SCALE_ALGOS, width=10).pack(side="left", padx=4)

        # Crop
        section(left, "Crop (w:h:x:y)", "Cut edges: width:height:x_offset:y_offset. "
                                        "Example 1920:800:0:140 removes letterbox bars. Leave empty to skip.")
        self.var_crop = tk.StringVar()
        ttk.Entry(left, textvariable=self.var_crop, width=24).pack(anchor="w")

        # Rotate
        section(left, "Orientation", "Rotate or flip the video using the transpose/hflip/vflip filters.")
        self.var_rotate = tk.StringVar(value="No change")
        ttk.Combobox(left, textvariable=self.var_rotate, state="readonly",
                     values=list(ROTATIONS.keys()), width=18).pack(anchor="w")

        # Trim
        section(left, "Trim (Start / End time)", "Cut a segment. Format HH:MM:SS or seconds. "
                                                 "Start uses -ss, End uses -to. Leave empty for full video.")
        tf = tk.Frame(left, bg=BG_PANEL); tf.pack(anchor="w")
        self.var_trim_start = tk.StringVar()
        self.var_trim_end = tk.StringVar()
        tk.Label(tf, text="Start:", bg=BG_PANEL, fg=FG_DIM).pack(side="left")
        es = ttk.Entry(tf, textvariable=self.var_trim_start, width=10); es.pack(side="left", padx=4)
        tk.Label(tf, text="End:", bg=BG_PANEL, fg=FG_DIM).pack(side="left")
        ee = ttk.Entry(tf, textvariable=self.var_trim_end, width=10); ee.pack(side="left", padx=4)
        es.bind("<KeyRelease>", lambda ev: self.update_estimates())
        ee.bind("<KeyRelease>", lambda ev: self.update_estimates())

        # Speed
        section(right, "Playback Speed", "Changes speed via setpts (video) + atempo (audio). "
                                         "2x halves duration; 0.5x doubles it.")
        self.var_speed = tk.StringVar(value="Normal (1x)")
        cbs = ttk.Combobox(right, textvariable=self.var_speed, state="readonly",
                           values=list(SPEEDS.keys()), width=14)
        cbs.pack(anchor="w")
        cbs.bind("<<ComboboxSelected>>", lambda e: self.update_estimates())

        # Enhancement checkboxes
        section(right, "Enhancement", "Denoise (hqdn3d) removes grain and improves compression. "
                                      "Sharpen (unsharp) enhances edges. "
                                      "Deinterlace (yadif) fixes comb lines on old TV footage.")
        self.var_denoise = tk.BooleanVar()
        self.var_sharpen = tk.BooleanVar()
        self.var_deint = tk.BooleanVar()
        ttk.Checkbutton(right, text="Denoise (hqdn3d)", variable=self.var_denoise).pack(anchor="w")
        ttk.Checkbutton(right, text="Sharpen (unsharp)", variable=self.var_sharpen).pack(anchor="w")
        ttk.Checkbutton(right, text="Deinterlace (yadif)", variable=self.var_deint).pack(anchor="w")

        # Color eq
        section(right, "Color Adjust (eq filter)", "Brightness -1.0..1.0 (0 = unchanged), "
                                                   "Contrast 0..3 (1 = unchanged), "
                                                   "Saturation 0..3 (1 = unchanged).")
        eqf = tk.Frame(right, bg=BG_PANEL); eqf.pack(anchor="w")
        self.var_bright = tk.StringVar(value="0")
        self.var_contrast = tk.StringVar(value="1")
        self.var_sat = tk.StringVar(value="1")
        for lbl, var in (("Bright", self.var_bright), ("Contrast", self.var_contrast), ("Sat", self.var_sat)):
            tk.Label(eqf, text=f"{lbl}:", bg=BG_PANEL, fg=FG_DIM).pack(side="left")
            ttk.Entry(eqf, textvariable=var, width=6).pack(side="left", padx=(2, 8))

    # --------------------------------------------------------- Tab 5: advanced
    def _build_advanced_tab(self):
        t = self.tab_adv

        row = tk.Frame(t, bg=BG_PANEL); row.pack(fill="x", pady=(4, 2), anchor="w")
        tk.Label(row, text="Output Container", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "MP4 = universal. MKV = holds anything. WEBM = VP9/AV1+Opus only. "
                        "MOV = Apple/editing. GIF = animation (video only, huge).").pack(side="left", padx=6)
        self.var_container = tk.StringVar(value="mp4")
        cb = ttk.Combobox(t, textvariable=self.var_container, state="readonly",
                          values=CONTAINERS, width=10)
        cb.pack(anchor="w")

        row = tk.Frame(t, bg=BG_PANEL); row.pack(fill="x", pady=(12, 2), anchor="w")
        tk.Label(row, text="Pixel Format", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "yuv420p plays everywhere (required for most players). "
                        "yuv444p keeps full chroma for editing. 10-bit reduces banding.").pack(side="left", padx=6)
        self.var_pixfmt = tk.StringVar(value="Auto")
        ttk.Combobox(t, textvariable=self.var_pixfmt, state="readonly",
                     values=list(PIX_FMTS.keys()), width=38).pack(anchor="w")

        fsf = tk.Frame(t, bg=BG_PANEL); fsf.pack(anchor="w", pady=(14, 0))
        self.var_faststart = tk.BooleanVar(value=True)
        ttk.Checkbutton(fsf, text="Web Optimize / FastStart (-movflags +faststart)",
                        variable=self.var_faststart).pack(side="left")
        help_badge(fsf, "Moves the MP4/MOV index (moov atom) to the front so playback "
                        "starts instantly when streamed over the web.").pack(side="left", padx=6)

        row = tk.Frame(t, bg=BG_PANEL); row.pack(fill="x", pady=(14, 2), anchor="w")
        tk.Label(row, text="Metadata", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "Written into the output container via -metadata. "
                        "Leave fields empty to keep original metadata.").pack(side="left", padx=6)
        mf = tk.Frame(t, bg=BG_PANEL); mf.pack(anchor="w")
        self.var_meta_title = tk.StringVar()
        self.var_meta_author = tk.StringVar()
        self.var_meta_copyright = tk.StringVar()
        for i, (lbl, var) in enumerate((("Title", self.var_meta_title),
                                        ("Author", self.var_meta_author),
                                        ("Copyright", self.var_meta_copyright))):
            tk.Label(mf, text=f"{lbl}:", bg=BG_PANEL, fg=FG_DIM).grid(row=i, column=0, sticky="e", pady=2)
            ttk.Entry(mf, textvariable=var, width=44).grid(row=i, column=1, sticky="w", padx=6, pady=2)

        row = tk.Frame(t, bg=BG_PANEL); row.pack(fill="x", pady=(14, 2), anchor="w")
        tk.Label(row, text="Inject Custom FFmpeg Flags", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        help_badge(row, "Raw flags appended before the output path. Examples: "
                        "-tune animation | -profile:v high10 | -g 48 | -map 0 "
                        "| -x265-params aq-mode=3. Power users only.").pack(side="left", padx=6)
        self.txt_custom = tk.Text(t, height=4, bg=BG_INPUT, fg=FG, insertbackground=FG,
                                  relief="flat", font=("Consolas", 10))
        self.txt_custom.pack(fill="x", pady=(2, 0))

    # ------------------------------------------------------------- Bottom bar
    def _build_bottom_bar(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=14, pady=(4, 4))

        self.btn_start = ttk.Button(bar, text="START BATCH", style="Accent.TButton",
                                    command=self.start_batch)
        self.btn_start.pack(side="left")
        self.btn_pause = ttk.Button(bar, text="PAUSE", style="Pause.TButton",
                                    command=self.toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=8)
        self.btn_stop = ttk.Button(bar, text="STOP", style="Stop.TButton",
                                   command=self.stop_batch, state="disabled")
        self.btn_stop.pack(side="left")

        prog = tk.Frame(bar, bg=BG)
        prog.pack(side="left", fill="x", expand=True, padx=(16, 0))
        self.lbl_file_prog = tk.Label(prog, text="Current file: idle", bg=BG, fg=FG_DIM, font=FONT_SMALL, anchor="w")
        self.lbl_file_prog.pack(fill="x")
        self.pb_file = ttk.Progressbar(prog, maximum=100)
        self.pb_file.pack(fill="x")
        self.lbl_total_prog = tk.Label(prog, text="Overall: 0 / 0", bg=BG, fg=FG_DIM, font=FONT_SMALL, anchor="w")
        self.lbl_total_prog.pack(fill="x", pady=(4, 0))
        self.pb_total = ttk.Progressbar(prog, maximum=100)
        self.pb_total.pack(fill="x")

        logf = tk.Frame(self, bg=BG)
        logf.pack(fill="x", padx=14, pady=(2, 12))
        tk.Label(logf, text="FFmpeg Log", bg=BG, fg=FG_DIM, font=FONT_SMALL, anchor="w").pack(fill="x")
        self.txt_log = tk.Text(logf, height=7, bg="#14141f", fg=FG_DIM, insertbackground=FG,
                               relief="flat", font=("Consolas", 9), state="disabled", wrap="none")
        self.txt_log.pack(fill="x")
        self.txt_log.tag_configure("err", foreground=ERROR)
        self.txt_log.tag_configure("ok", foreground=SUCCESS)
        self.txt_log.tag_configure("info", foreground=ACCENT)

    # ------------------------------------------------------------------ Logging
    def log(self, msg, tag=None):
        def _do():
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", msg + "\n", tag or ())
            self.txt_log.see("end")
            # keep log bounded
            lines = int(self.txt_log.index("end-1c").split(".")[0])
            if lines > 800:
                self.txt_log.delete("1.0", f"{lines - 800}.0")
            self.txt_log.configure(state="disabled")
        self.after(0, _do)

    # ----------------------------------------------------------- Queue actions
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Choose video files",
            filetypes=[("Video files", " ".join("*" + e for e in sorted(VIDEO_EXTS))),
                       ("All files", "*.*")])
        self._enqueue(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title="Choose folder (scanned recursively)")
        if not d:
            return
        found = []
        for root, _dirs, files in os.walk(d):
            for f in files:
                if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
                    found.append(os.path.join(root, f))
        if not found:
            messagebox.showinfo("No videos", "No video files found in that folder.")
            return
        self._enqueue(found)

    def _enqueue(self, paths):
        existing = {it.path for it in self.items}
        new_items = []
        for p in paths:
            if p and p not in existing:
                item = QueueItem(p)
                item.iid = self.tree.insert("", "end", values=(
                    os.path.basename(p), "?", "?", "?", "?", "Probing..."))
                self.items.append(item)
                new_items.append(item)
        if new_items:
            threading.Thread(target=self._probe_items, args=(new_items,), daemon=True).start()

    def _probe_items(self, items):
        for item in items:
            try:
                item.size = os.path.getsize(item.path)
            except OSError:
                item.size = None
            if self.ffprobe_ok:
                try:
                    out = subprocess.run(
                        ["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height,avg_frame_rate",
                         "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1", item.path],
                        capture_output=True, text=True, timeout=30)
                    for line in out.stdout.splitlines():
                        if line.startswith("width="):
                            item.width = int(float(line.split("=", 1)[1]))
                        elif line.startswith("height="):
                            item.height = int(float(line.split("=", 1)[1]))
                        elif line.startswith("avg_frame_rate="):
                            fr = line.split("=", 1)[1]
                            if "/" in fr:
                                n, d = fr.split("/")
                                if float(d) > 0:
                                    item.fps = float(n) / float(d)
                        elif line.startswith("duration="):
                            try:
                                item.duration = float(line.split("=", 1)[1])
                            except ValueError:
                                pass
                    item.status = "Ready"
                except Exception as exc:
                    item.status = "Probe failed"
                    self.log(f"ffprobe failed for {item.path}: {exc}", tag="err")
            else:
                item.status = "Ready (no probe)"
            self.after(0, self._refresh_row, item)
        self.after(0, self.update_estimates)

    def _refresh_row(self, item):
        if not self.tree.exists(item.iid):
            return
        res = f"{item.width}x{item.height}" if item.width else "?"
        self.tree.item(item.iid, values=(
            os.path.basename(item.path), res, fmt_duration(item.duration),
            human_size(item.size), human_size(item.est_size) if item.est_size else "?",
            item.status))

    def remove_selected(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Busy", "Stop the batch before editing the queue.")
            return
        sel = self.tree.selection()
        if not sel:
            return
        keep = []
        for item in self.items:
            if item.iid in sel:
                self.tree.delete(item.iid)
            else:
                keep.append(item)
        self.items = keep

    def clear_queue(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Busy", "Stop the batch before editing the queue.")
            return
        for item in self.items:
            self.tree.delete(item.iid)
        self.items = []

    # ------------------------------------------------------------- Estimation
    def _effective_duration(self, item):
        dur = item.duration or 0
        ts = parse_timecode(self.var_trim_start.get())
        te = parse_timecode(self.var_trim_end.get())
        if te is not None:
            dur = min(dur, te) if dur else te
        if ts is not None:
            dur = max(0, dur - ts)
        speed = SPEEDS.get(self.var_speed.get())
        if speed:
            dur = dur / speed
        return dur

    def _audio_bps(self):
        codec = AUDIO_CODECS[self.var_acodec.get()]
        if codec == "none":
            return 0
        if codec == "copy":
            return 128_000  # assumption
        if codec == "flac":
            return 700_000
        if codec == "pcm_s16le":
            return 1_536_000
        try:
            return int(self.var_abitrate.get().rstrip("k")) * 1000
        except ValueError:
            return 128_000

    def _video_encoder_name(self):
        label = self.var_encoder.get()
        sw, hw_map = VIDEO_ENCODERS[label]
        hw = self.var_hw.get()
        if hw != "CPU" and hw in hw_map:
            return hw_map[hw]
        return sw

    def _estimate_item(self, item):
        """Return estimated output bytes for a queue item under current settings."""
        dur = self._effective_duration(item)
        if not dur:
            return None
        rc = self.var_rc.get()
        abps = self._audio_bps()

        if rc == "Target Size":
            try:
                return float(self.var_target_mb.get()) * 1024 * 1024
            except ValueError:
                return None

        if rc in ("VBR", "CBR"):
            vbps = self._parse_bitrate(self.var_bitrate.get())
            if vbps is None:
                return None
            return (vbps + abps) * dur / 8

        # CRF / CQP heuristic estimate
        enc = self._video_encoder_name()
        if enc == "copy":
            return item.size
        eff = CODEC_EFFICIENCY.get(enc, 1.0)
        w, h = item.width or 1920, item.height or 1080
        scale = RESOLUTIONS.get(self.var_res.get())
        if scale:
            tw = int(scale.split(":")[0])
            if w > 0:
                h = int(h * tw / w)
                w = tw
        fps = item.fps or 30
        q = int(self.var_crf.get()) if rc == "CRF" else int(float(self.var_qp.get() or 23))
        # bits-per-pixel heuristic: bpp halves roughly every +6 CRF; 0.10 bpp @ CRF 23 for x264
        bpp = 0.10 * (2 ** ((23 - q) / 6.0)) * eff
        vbps = w * h * fps * bpp
        return (vbps + abps) * dur / 8

    @staticmethod
    def _parse_bitrate(text):
        text = text.strip().lower()
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", text)
        if not m:
            return None
        val = float(m.group(1))
        return int(val * (1_000_000 if m.group(2) == "m" else 1_000 if m.group(2) == "k" else 1))

    def update_estimates(self):
        for item in self.items:
            try:
                item.est_size = self._estimate_item(item)
            except Exception:
                item.est_size = None
            self._refresh_row(item)

    # --------------------------------------------------------- Command builder
    def _build_filters(self):
        vf, af = [], []
        if self.var_deint.get():
            vf.append("yadif")
        crop = self.var_crop.get().strip()
        if crop:
            vf.append(f"crop={crop}")
        rot = ROTATIONS.get(self.var_rotate.get())
        if rot:
            vf.append(rot)
        scale = RESOLUTIONS.get(self.var_res.get())
        if scale:
            vf.append(f"scale={scale}:flags={self.var_scale_algo.get()}")
        if self.var_denoise.get():
            vf.append("hqdn3d=4:3:6:4")
        if self.var_sharpen.get():
            vf.append("unsharp=5:5:0.8:5:5:0.4")
        try:
            b = float(self.var_bright.get() or 0)
            c = float(self.var_contrast.get() or 1)
            s = float(self.var_sat.get() or 1)
            if b != 0 or c != 1 or s != 1:
                vf.append(f"eq=brightness={b}:contrast={c}:saturation={s}")
        except ValueError:
            pass
        speed = SPEEDS.get(self.var_speed.get())
        if speed:
            vf.append(f"setpts={1.0 / speed}*PTS")
            # atempo supports 0.5-2.0 per instance
            t = speed
            while t > 2.0:
                af.append("atempo=2.0"); t /= 2.0
            while t < 0.5:
                af.append("atempo=0.5"); t /= 0.5
            af.append(f"atempo={t:.4f}")
        vol = int(self.var_volume.get())
        if vol != 100:
            af.append(f"volume={vol / 100:.2f}")
        if self.var_normalize.get():
            af.append("loudnorm=I=-14:TP=-1.5:LRA=11")
        return vf, af

    def _build_command(self, item, out_path):
        cmd = ["ffmpeg", "-hide_banner", "-y"]
        ts = self.var_trim_start.get().strip()
        te = self.var_trim_end.get().strip()
        if ts:
            cmd += ["-ss", ts]
        cmd += ["-i", item.path]
        if te:
            cmd += ["-to", te]

        vf, af = self._build_filters()
        enc = self._video_encoder_name()
        rc = self.var_rc.get()

        # ----- video
        if enc == "copy":
            if vf:
                raise ValueError("Filters cannot be used with 'Copy (no re-encode)'.")
            cmd += ["-c:v", "copy"]
        else:
            cmd += ["-c:v", enc]
            preset = PRESETS[int(self.var_preset_idx.get())]
            if enc in ("libx264", "libx265"):
                cmd += ["-preset", preset]
            elif enc == "libsvtav1":
                # map preset slider to SVT-AV1 preset 0-12 (higher = faster)
                cmd += ["-preset", str(12 - int(self.var_preset_idx.get() * 12 / (len(PRESETS) - 1)))]
            elif enc.endswith(("_nvenc", "_qsv", "_amf")):
                cmd += ["-preset", "slow" if int(self.var_preset_idx.get()) >= 5 else "fast"]

            dur = self._effective_duration(item)
            if rc == "CRF":
                crf = str(int(self.var_crf.get()))
                if enc == "libvpx-vp9":
                    cmd += ["-crf", crf, "-b:v", "0"]
                elif enc.endswith("_nvenc"):
                    cmd += ["-rc", "vbr", "-cq", crf, "-b:v", "0"]
                elif enc.endswith(("_qsv", "_amf", "_videotoolbox")):
                    cmd += ["-q:v", crf]
                elif enc in ("prores_ks", "dnxhd"):
                    pass  # quality driven by profile/bitrate defaults
                else:
                    cmd += ["-crf", crf]
            elif rc == "Target Size":
                if not dur:
                    raise ValueError("Duration unknown; cannot compute target bitrate.")
                target_mb = float(self.var_target_mb.get())
                total_kbps = target_mb * 8192 / dur
                audio_kbps = self._audio_bps() / 1000
                vkbps = max(100, int(total_kbps - audio_kbps))
                cmd += ["-b:v", f"{vkbps}k", "-maxrate", f"{int(vkbps * 1.4)}k",
                        "-bufsize", f"{int(vkbps * 2)}k"]
            elif rc == "VBR":
                br = self.var_bitrate.get().strip()
                cmd += ["-b:v", br]
                vbps = self._parse_bitrate(br)
                if vbps:  # allow peaks up to 1.5x average
                    cmd += ["-maxrate", f"{int(vbps * 1.5 / 1000)}k",
                            "-bufsize", f"{int(vbps * 3 / 1000)}k"]
            elif rc == "CBR":
                br = self.var_bitrate.get().strip()
                cmd += ["-b:v", br, "-minrate", br, "-maxrate", br]
                vbps = self._parse_bitrate(br)
                if vbps:
                    cmd += ["-bufsize", f"{int(vbps * 2 / 1000)}k"]
            elif rc == "CQP":
                cmd += ["-qp", str(int(float(self.var_qp.get() or 23)))]

            if vf:
                cmd += ["-vf", ",".join(vf)]
            pix = PIX_FMTS.get(self.var_pixfmt.get())
            if pix:
                cmd += ["-pix_fmt", pix]

        # ----- audio
        acodec = AUDIO_CODECS[self.var_acodec.get()]
        if acodec == "none":
            cmd += ["-an"]
        elif acodec == "copy" and not af:
            cmd += ["-c:a", "copy"]
        else:
            real = "aac" if acodec == "copy" else acodec  # filters force re-encode
            cmd += ["-c:a", real]
            if real not in ("flac", "pcm_s16le"):
                cmd += ["-b:a", self.var_abitrate.get()]
            ch = AUDIO_CHANNELS.get(self.var_channels.get())
            if ch:
                cmd += ["-ac", ch]
            sr = SAMPLE_RATES.get(self.var_srate.get())
            if sr:
                cmd += ["-ar", sr]
            if af:
                cmd += ["-filter:a", ",".join(af)]

        # ----- container / metadata
        if self.var_faststart.get() and self.var_container.get() in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]
        for key, var in (("title", self.var_meta_title), ("artist", self.var_meta_author),
                         ("copyright", self.var_meta_copyright)):
            if var.get().strip():
                cmd += ["-metadata", f"{key}={var.get().strip()}"]

        # ----- custom flags
        custom = self.txt_custom.get("1.0", "end").strip()
        if custom:
            try:
                cmd += shlex.split(custom)
            except ValueError as exc:
                raise ValueError(f"Bad custom flags: {exc}")

        cmd += ["-progress", "pipe:1", "-nostats", out_path]
        return cmd

    def _output_path(self, item):
        ext = "." + self.var_container.get()
        base = os.path.splitext(os.path.basename(item.path))[0]
        if self.var_same_folder.get():
            folder = os.path.dirname(item.path)
            name = f"{base}_compressed{ext}"
        else:
            folder = self.var_outdir.get().strip()
            if not folder:
                raise ValueError("Choose an output folder or enable 'Save in source folder'.")
            name = f"{base}{ext}"
        out = os.path.join(folder, name)
        if os.path.abspath(out) == os.path.abspath(item.path):
            out = os.path.join(folder, f"{base}_compressed{ext}")
        return out

    # --------------------------------------------------------- Batch execution
    def start_batch(self):
        if not self.ffmpeg_ok:
            messagebox.showerror("FFmpeg missing", "ffmpeg was not found on PATH.")
            return
        pending = [it for it in self.items if it.status not in ("Done",)]
        if not pending:
            messagebox.showinfo("Queue empty", "Add some video files first.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.stop_requested = False
        self.paused = False
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="PAUSE")
        self.btn_stop.configure(state="normal")
        self.update_estimates()
        self.worker = threading.Thread(target=self._run_batch, args=(pending,), daemon=True)
        self.worker.start()

    def toggle_pause(self):
        proc = self.current_proc
        if not proc or proc.poll() is not None:
            return
        try:
            if not self.paused:
                if IS_WINDOWS:
                    if psutil is None:
                        messagebox.showwarning(
                            "Pause unavailable",
                            "Install psutil (pip install psutil) to enable Pause on Windows.")
                        return
                    psutil.Process(proc.pid).suspend()
                else:
                    proc.send_signal(signal.SIGSTOP)
                self.paused = True
                self.btn_pause.configure(text="RESUME")
                self.log("Batch paused.", tag="info")
            else:
                if IS_WINDOWS:
                    psutil.Process(proc.pid).resume()
                else:
                    proc.send_signal(signal.SIGCONT)
                self.paused = False
                self.btn_pause.configure(text="PAUSE")
                self.log("Batch resumed.", tag="info")
        except Exception as exc:
            self.log(f"Pause/resume failed: {exc}", tag="err")

    def stop_batch(self):
        self.stop_requested = True
        proc = self.current_proc
        if proc and proc.poll() is None:
            if self.paused:
                self.toggle_pause()  # resume before kill so it can exit
            try:
                proc.terminate()
            except Exception:
                pass
        self.log("Stop requested...", tag="info")

    def _set_status(self, item, status):
        item.status = status
        self.after(0, self._refresh_row, item)

    def _run_batch(self, pending):
        total = len(pending)
        done = 0
        self.after(0, lambda: (self.pb_total.configure(value=0),
                               self.lbl_total_prog.configure(text=f"Overall: 0 / {total}")))
        for item in pending:
            if self.stop_requested:
                self._set_status(item, "Stopped")
                continue
            try:
                out_path = self._output_path(item)
                cmd = self._build_command(item, out_path)
            except ValueError as exc:
                self._set_status(item, "Error")
                self.log(f"ERROR ({os.path.basename(item.path)}): {exc}", tag="err")
                continue

            self._set_status(item, "Processing...")
            self.log("$ " + " ".join(cmd), tag="info")
            dur = self._effective_duration(item) or 0
            fname = os.path.basename(item.path)
            self.after(0, lambda f=fname: (self.pb_file.configure(value=0),
                                           self.lbl_file_prog.configure(text=f"Current file: {f} (0%)")))
            try:
                flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, creationflags=flags)
            except OSError as exc:
                self._set_status(item, "Error")
                self.log(f"Failed to launch ffmpeg: {exc}", tag="err")
                continue
            self.current_proc = proc

            err_thread = threading.Thread(target=self._pump_stderr, args=(proc,), daemon=True)
            err_thread.start()

            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_ms=") and dur > 0:
                    try:
                        secs = int(line.split("=", 1)[1]) / 1_000_000
                        pct = min(100.0, secs / dur * 100)
                        self.after(0, lambda p=pct, f=fname: (
                            self.pb_file.configure(value=p),
                            self.lbl_file_prog.configure(text=f"Current file: {f} ({p:.0f}%)")))
                    except ValueError:
                        pass
            proc.wait()
            err_thread.join(timeout=2)
            self.current_proc = None

            if self.stop_requested and proc.returncode != 0:
                self._set_status(item, "Stopped")
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)  # remove partial file
                except OSError:
                    pass
            elif proc.returncode == 0:
                done += 1
                try:
                    actual = os.path.getsize(out_path)
                    item.est_size = actual
                except OSError:
                    actual = None
                self._set_status(item, "Done")
                self.after(0, lambda: self.pb_file.configure(value=100))
                self.log(f"DONE: {fname} -> {human_size(actual)}", tag="ok")
            else:
                self._set_status(item, "Error")
                self.log(f"FAILED (exit {proc.returncode}): {fname}", tag="err")

            finished = pending.index(item) + 1
            self.after(0, lambda f=finished: (
                self.pb_total.configure(value=f / total * 100),
                self.lbl_total_prog.configure(text=f"Overall: {f} / {total}")))

        self.after(0, self._batch_finished, done, total)

    def _pump_stderr(self, proc):
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                self.log(line)

    def _batch_finished(self, done, total):
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="PAUSE")
        self.btn_stop.configure(state="disabled")
        self.lbl_file_prog.configure(text="Current file: idle")
        self.paused = False
        if self.stop_requested:
            self.log(f"Batch stopped. {done}/{total} completed.", tag="info")
        else:
            self.log(f"Batch complete. {done}/{total} succeeded.", tag="ok")
            messagebox.showinfo("Batch complete", f"{done} of {total} files processed successfully.")


def main():
    app = UltimateCommander()
    app.mainloop()


if __name__ == "__main__":
    main()
