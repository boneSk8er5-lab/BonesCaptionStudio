# =====================================================================
# BONES CAPTION STUDIO
# VERSION: 6.7.0
#   - 6.7: menu bar, recent projects, autosave/recovery, progress + cancel, timing offset, caption height, crop position, .bcsproj
#   - 6.6: voices (manual + automatic detection) with per-voice colours/name tags; transcript editor with lines, hide/restore, search, undo
#   - 6.5: shadow angle/distance/softness, strength up to 300%; pick which audio track to caption
#   - 6.4: soft drop shadow option with adjustable strength
#   - 6.3.1: sidebar no longer cut off; draggable divider between settings and preview
#   - 6.3: GPU detection shown in the app; portable mode (portable.txt), bundled Whisper models folder, beta build number
#   - 6.2.1: number boxes get real -/+ buttons (Windows 11 arrows were unclickable)
#   - 6.2: Auto caption mode splits captions at pauses in speech
#   - 6.1: preview plays the video's sound (audio drives the clock), mute + volume
#   - Export runs on a background thread (with Cancel)
#   - SRT / VTT subtitle export
#   - Line wrapping, text outline, text size, top/center/bottom alignment
#   - Seek bar + timestamps, click a word to jump, double-click to edit
#   - Save / open projects (.bcsproj), style presets
#   - Settings + log live in %APPDATA%\BonesCaptionStudio
# =====================================================================
APP_VERSION = "6.7.0"
APP_NAME = "Bones Caption Studio"

import sys
import os

# --- Frozen windowed builds have no console: give print()/tqdm somewhere safe to write ---
class NullWriter:
    def write(self, arg): pass
    def flush(self): pass
    def isatty(self): return False

if sys.platform == "win32" and getattr(sys, "frozen", False):
    sys.stdout = NullWriter()
    sys.stderr = NullWriter()

# Common fix for "OMP: Error #15" crashes in bundled torch builds
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import bisect
import re
import copy
import json
import logging
import math
import shutil
import subprocess
import time
import tempfile
import threading
import types
import warnings
from logging.handlers import RotatingFileHandler

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QFileDialog, QLabel,
    QHBoxLayout, QVBoxLayout, QGridLayout, QComboBox, QLineEdit, QInputDialog,
    QFrame, QColorDialog, QProgressBar, QCheckBox,
    QMessageBox, QSlider, QSpinBox, QDoubleSpinBox, QScrollArea, QAbstractItemView, QSplitter,
    QTreeWidget, QTreeWidgetItem, QMenu, QHeaderView
)
from PySide6.QtCore import Qt, QTimer, QSize, Signal, QThread, QUrl, QElapsedTimer, QPoint
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    AUDIO_SUPPORTED = True
except Exception:  # Qt Multimedia missing: preview still works, just silent
    AUDIO_SUPPORTED = False
from PySide6.QtGui import (QPixmap, QImage, QFont, QIcon, QPainter, QColor, QKeySequence, QShortcut,
                           QAction, QDesktopServices)


# =====================================================================
# PATHS
# =====================================================================
def app_dir():
    """Folder the .exe (or .py) lives in."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative_path):
    """Files bundled by PyInstaller (_MEIPASS), or next to the script when running from source."""
    return os.path.join(getattr(sys, "_MEIPASS", app_dir()), relative_path)


def is_portable():
    """Portable mode: a 'portable.txt' next to the .exe keeps settings, logs and models in the app folder."""
    return os.path.exists(os.path.join(app_dir(), "portable.txt"))


def read_build_version():
    """Release builds ship a version.txt (e.g. 6.3.0-beta.2) so testers' bug reports name the exact build."""
    try:
        with open(os.path.join(app_dir(), "version.txt"), "r", encoding="utf-8") as f:
            return f.read().strip() or APP_VERSION
    except Exception:
        return APP_VERSION


APP_VERSION_FULL = read_build_version()
PORTABLE = is_portable()


def get_data_dir():
    if PORTABLE:
        folder = os.path.join(app_dir(), "data")
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, ".write_test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return folder
        except OSError:
            pass  # app folder is read-only (e.g. Program Files): fall back to AppData
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    folder = os.path.join(root, "BonesCaptionStudio")
    os.makedirs(folder, exist_ok=True)
    return folder


DATA_DIR = get_data_dir()

# Whisper models: a 'models' folder next to the app (portable/release builds) or Whisper's normal cache
_local_models = os.path.join(app_dir(), "models")
MODELS_DIR = _local_models if (PORTABLE or os.path.isdir(_local_models)) else None
MODEL_FILES = {"tiny": "tiny.pt", "base": "base.pt", "small": "small.pt",
               "medium": "medium.pt", "turbo": "large-v3-turbo.pt"}


def model_downloaded(name):
    filename = MODEL_FILES.get(name)
    if not filename:
        return False
    default_cache = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache")), "whisper")
    return any(os.path.exists(os.path.join(folder, filename)) for folder in (MODELS_DIR, default_cache) if folder)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
FONT_CACHE_FILE = os.path.join(DATA_DIR, "font_cache.json")
LOG_FILE = os.path.join(DATA_DIR, "debug_log.txt")


# =====================================================================
# LOGGING  (our own messages at DEBUG, everything else at WARNING, capped size)
# =====================================================================
log = logging.getLogger("bcs")


def setup_logging():
    handler = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(handler)
    log.setLevel(logging.DEBUG)
    for noisy in ("numba", "matplotlib", "PIL", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


setup_logging()
log.info(f"{APP_NAME} v{APP_VERSION_FULL} starting | portable={PORTABLE} | python {sys.version.split()[0]} | "
         f"data={DATA_DIR} | models={MODELS_DIR or 'default cache'}")
warnings.filterwarnings("ignore", category=UserWarning, module="whisper.timing")
warnings.filterwarnings("ignore", category=UserWarning, module="whisper.transcribe")


def log_uncaught(exc_type, exc, tb):
    log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))


sys.excepthook = log_uncaught


# =====================================================================
# FFMPEG HELPERS
# =====================================================================
# Stops a black console window flashing up for every ffmpeg call in the windowed .exe
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def get_binary_path(binary_name):
    exe_name = f"{binary_name}.exe" if sys.platform == "win32" else binary_name
    for folder in (app_dir(), getattr(sys, "_MEIPASS", None), os.path.abspath(".")):
        if folder:
            candidate = os.path.join(folder, exe_name)
            if os.path.exists(candidate):
                return candidate
    return binary_name


FFMPEG_BIN = get_binary_path("ffmpeg")
FFPROBE_BIN = get_binary_path("ffprobe")
if os.path.dirname(FFMPEG_BIN):
    os.environ["PATH"] = os.path.dirname(FFMPEG_BIN) + os.pathsep + os.environ.get("PATH", "")


def run_cmd(cmd):
    return subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)


def popen(cmd, **kwargs):
    return subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW, **kwargs)


def tail_text(raw, limit=1500):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    raw = (raw or "").strip()
    return raw[-limit:]


def parse_rate(text):
    try:
        num, den = str(text).split("/")
        num, den = float(num), float(den)
        return (num / den if den else 0.0), f"{int(num)}/{int(den)}"
    except Exception:
        try:
            value = float(text)
            return value, f"{value:.6f}"
        except Exception:
            return 0.0, "30/1"


def even(value):
    return max(2, int(value) // 2 * 2)


def cover_filter(w, h, x=0.5):
    """Scale to fill w x h and crop the overflow (works for any source shape).
    x picks which part stays: 0 = left edge, 0.5 = centre, 1 = right edge."""
    x = max(0.0, min(1.0, float(x)))
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:(in_w-{w})*{x:.3f}:(in_h-{h})/2,setsar=1")


def describe_audio_track(n, stream):
    tags = stream.get("tags", {}) or {}
    tags = {k.lower(): v for k, v in tags.items()}
    handler = (tags.get("handler_name") or "").strip()
    if handler.lower() in ("soundhandler", "core media audio", "gpac isomedia handler", "isomedia handler"):
        handler = ""  # generic filler names some muxers write
    title = (tags.get("title") or tags.get("name") or handler or "").strip()  # MKV: title, MP4: handler_name
    channels = {1: "mono", 2: "stereo"}.get(stream.get("channels"), f"{stream.get('channels', '?')} ch")
    language = (tags.get("language") or "").strip()
    extra = ", ".join(x for x in (channels, language if language not in ("", "und") else "") if x)
    return f"Track {n + 1}" + (f": {title}" if title else "") + (f" ({extra})" if extra else "")


def probe_video(path):
    result = run_cmd([FFPROBE_BIN, "-v", "error", "-show_format", "-show_streams", "-of", "json", path])
    if result.returncode != 0:
        raise RuntimeError(tail_text(result.stderr) or "FFprobe could not read this file.")
    data = json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("No video stream was found in this file.")

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = 0
    try:
        rotation = int(float(video.get("tags", {}).get("rotate", 0)))
    except Exception:
        pass
    for side_data in video.get("side_data_list", []) or []:
        if "rotation" in side_data:
            try:
                rotation = int(float(side_data["rotation"]))
            except Exception:
                pass
    if abs(rotation) % 180 == 90:  # phone videos: ffmpeg auto-rotates, so swap
        width, height = height, width

    fps, fps_str = parse_rate(video.get("avg_frame_rate", "0/0"))
    if not 1 <= fps <= 240:
        fps, fps_str = parse_rate(video.get("r_frame_rate", "0/0"))
    if not 1 <= fps <= 240:
        fps, fps_str = 30.0, "30/1"

    duration = 0.0
    for candidate in (data.get("format", {}).get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except Exception:
            pass

    return {
        "width": width or 1920, "height": height or 1080,
        "fps": fps, "fps_str": fps_str, "duration": duration,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "audio_tracks": [describe_audio_track(n, s) for n, s in
                         enumerate(s for s in streams if s.get("codec_type") == "audio")],
    }


# =====================================================================
# CAPTION DATA + RENDERING  (pure Python, safe to use from any thread)
# =====================================================================
DEFAULT_STYLE = {
    "font": None,
    "text_color": [255, 255, 255],
    "highlight_color": [255, 255, 0],
    "outline_color": [0, 0, 0],
    "background": True,
    "outline": False,
    "position": "bottom",   # bottom | center | top
    "mode": "sentence",     # sentence | auto | word
    "max_words": 8,
    "pause_split": 0.5,     # Auto mode: start a new caption after a pause this long (seconds)
    "size": 100,            # percent
    "shadow": False,        # soft drop shadow behind the text
    "shadow_strength": 70,  # 10-300 %: above 100 the soft shadow gets denser and darker
    "shadow_angle": 45,     # direction the shadow falls: 0 = right, 90 = down, 180 = left, 270 = up
    "shadow_distance": 6,   # how far the shadow sits from the text, % of the text size
    "shadow_softness": 50,  # 0 = hard edge, 100 = very soft
    "voice_colors": "highlight",  # how voices are coloured: off | highlight | line
    "voice_names": False,         # show "Name:" in front of each caption
    "timing_offset": 0.0,         # seconds: + shows captions later, - earlier
    "y_offset": 0,                # nudge captions up (-) or down (+), % of the frame height
}
HOLD_GAP = 0.5
VOICE_PALETTE = [[255, 212, 0], [0, 229, 255], [255, 79, 216], [124, 255, 79],
                 [255, 159, 28], [178, 141, 255], [255, 82, 82], [255, 255, 255]]


def default_voice(n):
    return {"name": f"Voice {n + 1}", "color": list(VOICE_PALETTE[n % len(VOICE_PALETTE)])}  # keep a caption on screen through pauses shorter than this (stops flicker)


MAX_WORD_SECONDS = 1.0  # Whisper sometimes stretches the word before a pause right through the silence


def spoken_end(word):
    return min(word["end"], word["start"] + MAX_WORD_SECONDS)


def build_groups(words, mode, max_words, pause_split=0.5):
    raw_groups, current = [], []
    for i, w in enumerate(words):
        if mode == "word":
            raw_groups.append([i])
            continue
        if current and w.get("speaker") != words[current[-1]].get("speaker"):
            raw_groups.append(current)  # a different voice: start a fresh caption
            current = []
        if mode == "auto" and current and w["start"] - spoken_end(words[current[-1]]) >= pause_split:
            raw_groups.append(current)  # the speaker paused: start a fresh caption
            current = []
        current.append(i)
        if w["word"].endswith((".", "!", "?")) or len(current) >= max(1, int(max_words)):
            raw_groups.append(current)
            current = []
    if current:
        raw_groups.append(current)

    end_of = spoken_end if mode == "auto" else (lambda w: w["end"])
    groups = [{"start": words[g[0]]["start"], "end": max(end_of(words[g[-1]]), words[g[0]]["start"]), "idx": g}
              for g in raw_groups]
    for a, b in zip(groups, groups[1:]):
        if b["start"] - a["end"] < HOLD_GAP:
            a["end"] = max(a["end"], b["start"])
        a["end"] = max(a["start"], min(a["end"], b["start"]))
    return groups


class CaptionTrack:
    def __init__(self, words, mode, max_words, pause_split=0.5):
        self.words = [w for w in words if not w.get("hidden")]  # hidden words never reach the screen
        self.groups = build_groups(self.words, mode, max_words, pause_split)
        self.starts = [g["start"] for g in self.groups]

    def group_index_at(self, t):
        i = bisect.bisect_right(self.starts, t) - 1
        if i >= 0 and t <= self.groups[i]["end"]:
            return i
        return -1

    def end_time(self):
        return self.groups[-1]["end"] if self.groups else 0.0


class CaptionRenderer:
    """Draws captions onto a transparent RGBA layer. Caches the last layer so
    identical frames (same caption, same highlighted word) cost nothing."""

    def __init__(self, style, font_info, voices=None):
        self.style = dict(style)
        self.font_info = font_info  # {"path":..., "index":...} or None
        self.voices = copy.deepcopy(voices or [])
        self._fonts = {}
        self._last_key = None
        self._last_img = None

    def font_size(self, w, h):
        return max(8, round(min(w, h) * 0.0667 * self.style.get("size", 100) / 100))

    def get_font(self, size):
        if size in self._fonts:
            return self._fonts[size]
        font = None
        if self.font_info:
            try:
                font = ImageFont.truetype(self.font_info["path"], size, index=self.font_info.get("index", 0))
            except Exception as e:
                log.warning(f"Could not open font {self.font_info}: {e}")
        if font is None:
            try:
                font = ImageFont.load_default(size=size)
            except TypeError:
                font = ImageFont.load_default()
        self._fonts[size] = font
        return font

    def overlay(self, t, w, h, track):
        """Returns an RGBA caption layer, or None when nothing is on screen."""
        if track is None:
            return None
        t = t - float(self.style.get("timing_offset", 0.0) or 0.0)
        gi = track.group_index_at(t)
        if gi < 0:
            return None
        group = track.groups[gi]
        words = [track.words[i] for i in group["idx"]]
        active = None
        for k, word in enumerate(words):
            if word["start"] <= t:
                active = k

        key = (gi, active, w, h)
        if key == self._last_key:
            return self._last_img
        img = self._draw(words, active, w, h)
        self._last_key, self._last_img = key, img
        return img

    def _draw(self, words, active, w, h):
        st = self.style
        size = self.font_size(w, h)
        font = self.get_font(size)
        stroke = max(1, round(size * 0.07)) if st.get("outline") else 0
        pad_x, pad_y = round(size * 0.45), round(size * 0.3)

        # --- colours: per-voice highlight / whole line, optional name tag ---
        text_rgb = tuple(st.get("text_color", [255, 255, 255]))
        hl_rgb = tuple(st.get("highlight_color", [255, 255, 0]))
        speaker = words[0].get("speaker") if words else None
        voice = self.voices[speaker] if isinstance(speaker, int) and 0 <= speaker < len(self.voices) else None
        voice_rgb = tuple(voice["color"]) if voice else None
        mode = st.get("voice_colors", "highlight")
        texts, colors = [], []
        if voice and st.get("voice_names") and voice.get("name"):
            texts.append(f"{voice['name']}:")
            colors.append(voice_rgb)
            active = None if active is None else active + 1
        for k, x in enumerate(words):
            texts.append(x["word"])
            colors.append(None)
        for k in range(len(texts)):
            if colors[k] is not None:
                continue
            is_active = (k == active)
            if voice_rgb and mode == "line":
                colors[k] = tuple(int(c + (255 - c) * 0.55) for c in voice_rgb) if is_active else voice_rgb
            elif voice_rgb and mode == "highlight":
                colors[k] = voice_rgb if is_active else text_rgb
            else:
                colors[k] = hl_rgb if is_active else text_rgb
        widths = [font.getlength(s) for s in texts]
        space = font.getlength(" ")

        # --- wrap into lines that fit 90% of the frame width ---
        max_line_w = w * 0.9 - 2 * pad_x - 2 * stroke
        lines, current, current_w = [], [], 0.0
        for k, word_w in enumerate(widths):
            added = word_w if not current else space + word_w
            if current and current_w + added > max_line_w:
                lines.append((current, current_w))
                current, current_w = [k], word_w
            else:
                current.append(k)
                current_w += added
        if current:
            lines.append((current, current_w))

        ascent, descent = font.getmetrics()
        line_h = ascent + descent + stroke * 2
        gap = round(size * 0.12)
        block_h = len(lines) * line_h + (len(lines) - 1) * gap

        position = st.get("position", "bottom")
        if position == "center":
            top = (h - block_h) // 2
        elif position == "top":
            top = round(h * 0.08) + pad_y
        else:
            top = round(h * 0.90) - block_h - pad_y
        top += round(h * int(st.get("y_offset", 0) or 0) / 100)   # fine-tune height
        top = max(pad_y, min(h - block_h - pad_y, top))           # never off the frame

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        if st.get("background", True):
            block_w = max(lw for _, lw in lines) + stroke * 2
            left = (w - block_w) / 2
            d.rounded_rectangle(
                [left - pad_x, top - pad_y, left + block_w + pad_x, top + block_h + pad_y],
                radius=round(size * 0.3), fill=(0, 0, 0, 160))

        # where every word goes
        placed = []
        y = top
        for indices, line_w in lines:
            x = (w - line_w) / 2
            baseline = y + stroke + ascent
            for k in indices:
                placed.append((x, baseline, k))
                x += widths[k] + space
            y += line_h + gap

        if st.get("shadow"):
            self._draw_shadow(img, placed, texts, font, size, stroke)

        outline_rgb = tuple(st.get("outline_color", [0, 0, 0]))
        d = ImageDraw.Draw(img)
        for x, baseline, k in placed:
            color = colors[k]
            d.text((x, baseline), texts[k], font=font, fill=color + (255,), anchor="ls",
                   stroke_width=stroke, stroke_fill=outline_rgb + (255,))
        return img

    def _draw_shadow(self, img, placed, texts, font, size, stroke):
        """Drop shadow: the text shape moved by angle/distance, blurred by softness, darkened onto the layer."""
        w, h = img.size
        st = self.style
        distance = size * max(0, min(100, int(st.get("shadow_distance", 6)))) / 100.0
        angle = math.radians(int(st.get("shadow_angle", 45)) % 360)
        dx, dy = round(math.cos(angle) * distance), round(math.sin(angle) * distance)
        blur = size * 0.14 * max(0, min(100, int(st.get("shadow_softness", 50)))) / 100.0
        strength = max(10, min(300, int(st.get("shadow_strength", 70)))) / 100.0
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        for x, baseline, k in placed:
            md.text((x + dx, baseline + dy), texts[k], font=font, fill=255, anchor="ls",
                    stroke_width=stroke, stroke_fill=255)
        bbox = mask.getbbox()
        if not bbox:
            return
        pad = int(blur * 3) + 1
        region = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad))
        alpha = mask.crop(region)
        if blur >= 0.5:  # softness 0 = crisp, hard-edged shadow
            alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
        alpha = alpha.point(lambda v: min(255, int(v * strength)))
        shadow = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
        shadow.putalpha(alpha)
        img.alpha_composite(shadow, dest=region[:2])


def subtitle_timestamp(t, vtt=False):
    ms = int(round(max(0.0, t) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1000)
    sep = "." if vtt else ","
    return f"{hours:02}:{minutes:02}:{seconds:02}{sep}{ms:03}"


def build_subtitles(track, vtt=False, voices=None, offset=0.0):
    out = ["WEBVTT", ""] if vtt else []
    offset = float(offset or 0.0)
    voices = voices or []
    for n, group in enumerate(track.groups, 1):
        text = " ".join(track.words[i]["word"] for i in group["idx"])
        speaker = track.words[group["idx"][0]].get("speaker")
        if isinstance(speaker, int) and 0 <= speaker < len(voices) and voices[speaker].get("name"):
            name = voices[speaker]["name"]
            text = f"<v {name}>{text}" if vtt else f"[{name}] {text}"
        end = max(group["end"], group["start"] + 0.2)
        if not vtt:
            out.append(str(n))
        out.append(f"{subtitle_timestamp(group['start'] + offset, vtt)} --> {subtitle_timestamp(end + offset, vtt)}")
        out.append(text)
        out.append("")
    return "\n".join(out)


def fmt_clock(t, decimals=False):
    t = max(0.0, t)
    minutes = int(t // 60)
    return f"{minutes}:{t % 60:04.1f}" if decimals else f"{minutes}:{int(t % 60):02}"


# =====================================================================
# FONT SCANNER  (background thread, cached between launches)
# =====================================================================
def font_dirs():
    if sys.platform == "win32":
        dirs = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")]
        local = os.environ.get("LOCALAPPDATA")
        if local:  # fonts installed "for current user only"
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs = ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs = ["/usr/share/fonts", "/usr/local/share/fonts",
                os.path.expanduser("~/.local/share/fonts"), os.path.expanduser("~/.fonts")]
    return [d for d in dirs if os.path.isdir(d)]


class FontScanWorker(QThread):
    done = Signal(dict)

    @staticmethod
    def read_faces(path):
        faces = []
        is_collection = path.lower().endswith(".ttc")
        for index in range(16 if is_collection else 1):
            try:
                font = ImageFont.truetype(path, 12, index=index)
            except Exception:
                break
            family, style = font.getname()
            family, style = (family or "").strip(), (style or "").strip()
            if not family:
                continue
            plain = style.lower() in ("", "regular", "normal", "book", "roman")
            faces.append([family if plain else f"{family} {style}", family, index])
        return faces

    def run(self):
        try:
            with open(FONT_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
        fonts, new_cache = {}, {}
        for folder in font_dirs():
            for root, _, files in os.walk(folder):
                for name in files:
                    if name.startswith("~$") or not name.lower().endswith((".ttf", ".otf", ".ttc")):
                        continue
                    path = os.path.join(root, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    if stat.st_size == 0:
                        continue
                    entry = cache.get(path)
                    if not entry or entry.get("m") != stat.st_mtime or entry.get("s") != stat.st_size:
                        entry = {"m": stat.st_mtime, "s": stat.st_size, "faces": self.read_faces(path)}
                    new_cache[path] = entry
                    for face_name, family, index in entry["faces"]:
                        fonts.setdefault(face_name, {"path": path, "index": index, "family": family})
        try:
            with open(FONT_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(new_cache, f)
        except Exception as e:
            log.warning(f"Could not write font cache: {e}")
        log.debug(f"Font scan found {len(fonts)} faces")
        self.done.emit(fonts)


# =====================================================================
# TRANSCRIPTION WORKER  (model is loaded once and reused)
# =====================================================================
_MODEL_CACHE = {}
_MODEL_LOCK = threading.Lock()


def load_audio_16k(path, track=0):
    """Decode one audio track ourselves (no console flash, clear errors) and hand Whisper a numpy array."""
    import numpy as np
    result = run_cmd([FFMPEG_BIN, "-nostdin", "-v", "error", "-i", path, "-vn", "-map", f"0:a:{int(track)}",
                      "-ac", "1", "-ar", "16000", "-f", "s16le", "-"])
    if result.returncode != 0:
        raise RuntimeError("Could not read the audio track:\n" + tail_text(result.stderr))
    if not result.stdout:
        raise RuntimeError("This video has no audio to transcribe.")
    return np.frombuffer(result.stdout, np.int16).flatten().astype(np.float32) / 32768.0


class HardwareProbe(QThread):
    """Loads the AI engine in the background at startup (makes the first transcription start faster)
    and reports which GPU, if any, this PC can use."""
    done = Signal(str, bool)

    def run(self):
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
                message, gpu = f"✅ GPU ready: {name} ({vram:.0f} GB)", True
            elif getattr(torch.version, "cuda", None) is None:
                message, gpu = "This is the CPU edition. NVIDIA owners can use the GPU edition for faster captions.", False
            else:
                message, gpu = "No usable NVIDIA GPU found, so captions will use the CPU.", False
            log.info(f"Hardware: torch {torch.__version__} (cuda build: {torch.version.cuda}) -> {message}")
        except Exception as e:
            log.exception("AI engine failed to load")
            message, gpu = f"⚠ The AI engine couldn't load: {e}", False
        self.done.emit(message, gpu)


class VoiceDetectWorker(QThread):
    """Works out who is speaking (Voice 1, Voice 2...) using a small built-in voice model."""
    status = Signal(str)
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, video_path, audio_track, words, n_voices):
        super().__init__()
        self.video_path = video_path
        self.audio_track = audio_track
        self.words = [{"start": w["start"], "end": w["end"]} for w in words]
        self.n_voices = n_voices

    def run(self):
        try:
            import voice_detect
            self.status.emit("Reading audio for voice detection...")
            audio = load_audio_16k(self.video_path, self.audio_track)
            encoder = voice_detect.VoiceEncoder(resource_path("voice_encoder.npz"))
            labels = voice_detect.diarize(
                encoder, audio, self.words, self.n_voices,
                progress=lambda done, total: self.status.emit(f"Detecting voices... {done * 100 // max(total, 1)}%"))
            self.succeeded.emit(list(labels))
        except Exception as e:
            log.exception("Voice detection failed")
            self.failed.emit(str(e) or e.__class__.__name__)


class TranscriptionCancelled(Exception):
    pass


class _ProgressBar:
    """Stands in for Whisper's tqdm progress bars so the app can show progress and cancel."""

    def __init__(self, callback, total=None):
        self.callback = callback
        self.total = total or 0
        self.n = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, n=1):
        self.n += n
        self.callback(self.n, self.total)

    def close(self):
        pass


class TranscriptionWorker(QThread):
    succeeded = Signal(dict, str)
    failed = Signal(str)
    fallback_warning = Signal(str)
    status = Signal(str)
    progress = Signal(int)
    cancelled = Signal()

    def __init__(self, video_path, accel, model_name, language, audio_track=0):
        super().__init__()
        self.audio_track = audio_track
        self.video_path = video_path
        self.accel = accel
        self.model_name = model_name
        self.language = language
        self._cancel = False
        self._device = "cpu"

    def cancel(self):
        self._cancel = True

    def _check_cancel(self):
        if self._cancel:
            raise TranscriptionCancelled()

    def _install_progress_hooks(self, whisper):
        """Route Whisper's download/transcribe progress into the app (and let Cancel stop it)."""
        import whisper.transcribe as whisper_transcribe

        def on_download(n, total):
            self._check_cancel()
            if total:
                self.status.emit(f"Downloading the '{self.model_name}' model (one time only)... "
                                 f"{n * 100 // total}%  ({n / 1048576:.0f} of {total / 1048576:.0f} MB)")

        def on_transcribe(n, total):
            self._check_cancel()
            if total:
                pct = min(100, n * 100 // total)
                self.progress.emit(pct)
                self.status.emit(f"Transcribing on {'GPU' if self._device == 'cuda' else 'CPU'}... {pct}%")

        whisper.tqdm = lambda *a, **kw: _ProgressBar(on_download, kw.get("total"))
        whisper_transcribe.tqdm = types.SimpleNamespace(
            tqdm=lambda *a, **kw: _ProgressBar(on_transcribe, kw.get("total")))

    def resolve_device(self):
        if self.accel == "cpu":
            return "cpu"
        if self.accel == "cuda":
            return "cuda"
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def transcribe(self, audio, device):
        import whisper
        self._device = device
        self._install_progress_hooks(whisper)
        self._check_cancel()
        key = (self.model_name, device)
        with _MODEL_LOCK:
            model = _MODEL_CACHE.get(key)
            if model is None:
                self.status.emit(f"Loading '{self.model_name}' model on {device.upper()}...")
                _MODEL_CACHE.clear()  # free the old model's memory first
                model = whisper.load_model(self.model_name, device=device, download_root=MODELS_DIR)
                _MODEL_CACHE[key] = model
        self.status.emit(f"Transcribing on {'GPU' if device == 'cuda' else 'CPU'}...")
        options = {"word_timestamps": True, "fp16": device == "cuda"}
        if self.language:
            options["language"] = self.language
        return model.transcribe(audio, **options)

    def run(self):
        try:
            self.status.emit("Reading audio...")
            audio = load_audio_16k(self.video_path, self.audio_track)
            self._check_cancel()
            device = self.resolve_device()
            try:
                result = self.transcribe(audio, device)
            except Exception as primary_error:
                if device != "cuda" or isinstance(primary_error, TranscriptionCancelled):
                    raise
                log.exception("GPU transcription failed, falling back to CPU")
                self.fallback_warning.emit(str(primary_error))
                device = "cpu"
                result = self.transcribe(audio, device)
            self.succeeded.emit(result, device)
        except TranscriptionCancelled:
            log.info("Transcription cancelled")
            self.cancelled.emit()
        except Exception as e:
            log.exception("Transcription failed")
            self.failed.emit(str(e) or e.__class__.__name__)


# =====================================================================
# EXPORT WORKER
# =====================================================================
class ExportCancelled(Exception):
    pass


class ExportWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, video_path, info, out_file, export_mode, vertical, words, style, font_info, voices=None,
                 crop_x=0.5):
        super().__init__()
        self.video_path = video_path
        self.info = info
        self.out_file = out_file
        self.export_mode = export_mode
        self.vertical = vertical
        self.words = copy.deepcopy(words)
        self.style = dict(style)
        self.font_info = font_info
        self.voices = copy.deepcopy(voices or [])
        self.crop_x = crop_x
        self._cancel = False
        self._procs = []

    def cancel(self):
        self._cancel = True

    def _check_cancel(self):
        if self._cancel:
            raise ExportCancelled()

    def run(self):
        err_file = tempfile.TemporaryFile()
        try:
            self._run(err_file)
            self.succeeded.emit(self.out_file)
        except ExportCancelled:
            self._cleanup(remove_output=True)
            self.cancelled.emit()
        except Exception as e:
            log.exception("Export failed")
            self._cleanup(remove_output=True)
            detail = ""
            try:
                err_file.seek(0)
                detail = tail_text(err_file.read())
            except Exception:
                pass
            message = str(e) or e.__class__.__name__
            self.failed.emit(message + (f"\n\nFFmpeg said:\n{detail}" if detail and detail not in message else ""))
        finally:
            err_file.close()

    def _cleanup(self, remove_output):
        for proc in self._procs:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        if remove_output:
            try:
                if os.path.exists(self.out_file):
                    os.remove(self.out_file)
            except Exception:
                pass

    def _finish(self, proc, label):
        if proc.stdin:
            proc.stdin.close()
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"{label} failed (FFmpeg exit code {rc}).")

    def _run(self, err_file):
        info = self.info
        fps, fps_str = info["fps"], info["fps_str"]
        track = CaptionTrack(self.words, self.style["mode"], self.style["max_words"],
                             self.style.get("pause_split", 0.5))
        renderer = CaptionRenderer(self.style, self.font_info, self.voices)
        if self.vertical:
            out_w, out_h = 1080, 1920
            vf = f"fps={fps_str},{cover_filter(out_w, out_h, self.crop_x)}"
        else:
            out_w, out_h = even(info["width"]), even(info["height"])
            vf = f"fps={fps_str},scale={out_w}:{out_h},setsar=1"
        total = max(1, math.ceil(info["duration"] * fps))

        if self.export_mode == "overlay":
            cmd = [FFMPEG_BIN, "-nostdin", "-y", "-v", "error",
                   "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{out_w}x{out_h}", "-r", fps_str, "-i", "-",
                   "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", "-an", self.out_file]
            writer = popen(cmd, stdin=subprocess.PIPE, stderr=err_file)
            self._procs.append(writer)
            blank = bytes(out_w * out_h * 4)
            last_img, last_bytes = None, None
            try:
                for i in range(total):
                    self._check_cancel()
                    layer = renderer.overlay(i / fps, out_w, out_h, track)
                    if layer is None:
                        data = blank
                    else:
                        if layer is not last_img:
                            last_img, last_bytes = layer, layer.tobytes()
                        data = last_bytes
                    writer.stdin.write(data)
                    if i % 15 == 0:
                        pct = int(i * 100 / total)
                        self.progress.emit(pct, f"Exporting overlay: {pct}%")
            except (BrokenPipeError, OSError):
                writer.wait()
                raise RuntimeError("FFmpeg stopped while writing the overlay.")
            self._finish(writer, "Overlay encode")

        else:
            read_cmd = [FFMPEG_BIN, "-nostdin", "-v", "error", "-i", self.video_path, "-vf", vf,
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            write_cmd = [FFMPEG_BIN, "-nostdin", "-y", "-v", "error",
                         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}", "-r", fps_str, "-i", "-",
                         "-i", self.video_path, "-map", "0:v:0", "-map", "1:a?",
                         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", self.out_file]
            frame_size = out_w * out_h * 3
            reader = popen(read_cmd, stdout=subprocess.PIPE, stderr=err_file, bufsize=frame_size * 2)
            self._procs.append(reader)
            writer = popen(write_cmd, stdin=subprocess.PIPE, stderr=err_file, bufsize=frame_size * 2)
            self._procs.append(writer)
            i = 0
            try:
                while True:
                    self._check_cancel()
                    raw = reader.stdout.read(frame_size)
                    if len(raw) < frame_size:
                        break
                    layer = renderer.overlay(i / fps, out_w, out_h, track)
                    if layer is not None:
                        frame = Image.frombytes("RGB", (out_w, out_h), raw).convert("RGBA")
                        raw = Image.alpha_composite(frame, layer).convert("RGB").tobytes()
                    writer.stdin.write(raw)
                    i += 1
                    if i % 15 == 0:
                        pct = min(99, int(i * 100 / total))
                        self.progress.emit(pct, f"Rendering full video: {pct}%")
            except (BrokenPipeError, OSError):
                writer.wait()
                raise RuntimeError("FFmpeg stopped while encoding the video.")
            reader.stdout.close()
            if reader.wait() != 0 and i == 0:
                raise RuntimeError("FFmpeg could not decode the source video.")
            if i == 0:
                raise RuntimeError("No video frames were read from the source file.")
            self._finish(writer, "Video encode")

        self.progress.emit(100, "Export finished!")


# =====================================================================
# DRAG-AND-DROP ZONE
# =====================================================================
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")


class DropZone(QFrame):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setAcceptDrops(True)
        self.setObjectName("DropZoneWorkspace")
        self.setMinimumHeight(65)
        layout = QVBoxLayout(self)
        self.label = QLabel("📥 Drag & Drop a Video or Project Here")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self.set_accent("#00ADB5", "#00FFF5")

    def set_accent(self, primary, hover):
        self.setStyleSheet(f"""
            QFrame#DropZoneWorkspace {{ background-color: #1E1E1E; border: 2px dashed {primary}; border-radius: 8px; }}
            QFrame#DropZoneWorkspace:hover {{ background-color: #252525; border-color: {hover}; }}
        """)
        self.label.setStyleSheet(f"color: {primary}; font-weight: bold; font-size: 12px; background: transparent; border: none;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if not files:
            return
        if files[0].lower().endswith(VIDEO_EXTS + PROJECT_EXTS):
            self.callback(files[0])
        else:
            log.warning(f"DropZone rejected file: {files[0]}")
            self.label.setText("⚠ Drop a video or a caption project")
            QTimer.singleShot(2500, lambda: self.label.setText("📥 Drag & Drop a Video or Project Here"))


# =====================================================================
# PREVIEW FRAME READER  (keeps one ffmpeg stream open for smooth playback)
# =====================================================================
class VideoFrameReader:
    def __init__(self, video_path, info):
        self.video_path = video_path
        self.info = info
        self.fps = info["fps"]
        self.duration = info["duration"]
        self.process = None
        self.stream_time = -1.0
        self.size = None
        self.last_frame = None

    def close_active_stream(self):
        if self.process:
            try:
                self.process.stdout.close()
                self.process.terminate()
                self.process.wait(timeout=0.5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.stream_time = -1.0

    def frame_at(self, t, w, h, crop_x=0.5):
        t = max(0.0, min(t, max(0.0, self.duration - 1.0 / self.fps)))
        frame_size = w * h * 3

        if self.process and self.size == (w, h, crop_x) and self.stream_time >= 0:
            delta = t - self.stream_time
            steps = round(delta * self.fps)
            if steps == 0 and self.last_frame is not None and delta > -0.5 / self.fps:
                return self.last_frame
            if 1 <= steps <= 30:  # close enough: read forward instead of re-seeking
                try:
                    raw = b""
                    for _ in range(steps):
                        raw = self.process.stdout.read(frame_size)
                        if len(raw) != frame_size:
                            raise EOFError
                    self.stream_time += steps / self.fps
                    self.last_frame = Image.frombytes("RGB", (w, h), raw)
                    return self.last_frame
                except Exception:
                    pass

        self.close_active_stream()
        self.size = (w, h, crop_x)
        cmd = [FFMPEG_BIN, "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", self.video_path,
               "-vf", cover_filter(w, h, crop_x), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        try:
            self.process = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_size * 4)
            raw = self.process.stdout.read(frame_size)
            if len(raw) == frame_size:
                self.stream_time = t
                self.last_frame = Image.frombytes("RGB", (w, h), raw)
                return self.last_frame
        except Exception as e:
            log.error(f"Preview stream failed: {e}")
        return self.last_frame


# =====================================================================
# SETTINGS
# =====================================================================
def load_settings():
    settings = {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning(f"Settings file unreadable, starting fresh: {e}")
    if "favorites" not in settings:  # carry over favorites from older versions
        favorites = set()
        for old in (os.path.join(app_dir(), "font_favorites.json"), os.path.abspath("font_favorites.json")):
            try:
                with open(old, "r", encoding="utf-8") as f:
                    favorites |= set(json.load(f))
            except Exception:
                pass
        settings["favorites"] = sorted(favorites)
    settings.setdefault("presets", {})
    settings.setdefault("style", {})
    settings.setdefault("ui", {})
    return settings


def save_settings(settings):
    try:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception as e:
        log.error(f"Failed to save settings: {e}")


# =====================================================================
# MAIN WINDOW
# =====================================================================
WHISPER_MODELS = [
    ("tiny", "Tiny – fastest, least accurate"),
    ("base", "Base – fast"),
    ("small", "Small – good balance"),
    ("medium", "Medium – most accurate, slow on CPU"),
    ("turbo", "Turbo – accurate + fast (GPU, newer Whisper)"),
]
LANGUAGES = [("", "Auto-detect"), ("en", "English"), ("es", "Spanish"), ("fr", "French"),
             ("de", "German"), ("pt", "Portuguese"), ("it", "Italian"), ("ja", "Japanese")]
PROJECT_EXT = ".bcsproj"
PROJECT_EXTS = (".bcsproj", ".bcs.json")
PROJECT_FILTER = "Caption Projects (*.bcsproj *.bcs.json);;All files (*.*)"
AUTOSAVE_FILE = os.path.join(DATA_DIR, "autosave.bcsproj")
GITHUB_REPO = "boneSk8er5-lab/BonesCaptionStudio"
OVERLAY_BYTES_PER_PIXEL = 0.09   # measured: ProRes 4444 caption overlays ~0.077 bytes per pixel per frame


def version_key(text):
    """'6.7.0-beta.2' -> (6, 7, 0, 0, 2); a full release sorts after its betas."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-.]?beta\.?(\d+))?", str(text).strip(), re.I)
    if not m:
        return (0, 0, 0, 0, 0)
    major, minor, patch, beta = (int(x) if x else 0 for x in m.groups())
    return (major, minor, patch, 0 if m.group(4) else 1, beta)


class UpdateCheckWorker(QThread):
    done = Signal(dict)

    def run(self):
        import urllib.request
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=20",
                                         headers={"User-Agent": f"BonesCaptionStudio/{APP_VERSION}",
                                                  "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                releases = json.loads(r.read().decode("utf-8"))
            self.done.emit({"ok": True, "releases": releases})
        except Exception as e:
            self.done.emit({"ok": False, "error": str(e)})


class MainWindow(QMainWindow):
    @property
    def dirty(self):
        return getattr(self, "_dirty", False)

    @dirty.setter
    def dirty(self, value):
        self._dirty = bool(value)
        self.update_title()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self.busy is None:
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files and self.busy is None:
            self.open_any_file(files[0])

    def update_title(self):
        project = getattr(self, "project_path", None)
        video = getattr(self, "video_path", None)
        if project:
            name = os.path.basename(project)
        elif video:
            name = os.path.basename(video) + " (not saved)"
        else:
            name = "New Project"
        mark = "● " if getattr(self, "_dirty", False) else ""
        self.setWindowTitle(f"{mark}{name} — {APP_NAME} v{APP_VERSION_FULL}" + (" (Portable)" if PORTABLE else ""))

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.resize(1400, 880)
        icon_path = resource_path("BCS.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.settings = load_settings()
        self.favorites = set(self.settings["favorites"])
        self.style = dict(DEFAULT_STYLE)
        self.style.update({k: v for k, v in self.settings["style"].items() if k in DEFAULT_STYLE})
        ui = dict(self.settings["ui"])

        self.video_path = None
        self.video_info = None
        self.frame_reader = None
        self.words = []
        self.voices = []          # [{"name": "Voice 1", "color": [r, g, b]}, ...] - index = word["speaker"]
        self._undo, self._redo = [], []
        self._editor_lines = []
        self._line_of_word = []
        self._word_index = {}
        self.voice_worker = None
        self.track = None
        self.renderer = None
        self.font_map = {}
        self.dirty = False
        self.project_path = None
        self.busy = None  # None | "transcribe" | "export"
        self.transcription_worker = None
        self.export_worker = None
        self.export_mode = ui.get("export_mode", "overlay")
        self._loading = True

        self.preview_time = 0.0
        self.preview_running = False
        self._updating_slider = False
        self._last_list_row = -1
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.on_preview_tick)
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.timeout.connect(self.refresh_preview)

        # Preview audio: the audio position is the master clock while playing
        self.audio_player = None
        self.audio_output = None
        self.audio_ok = False
        self._play_clock = QElapsedTimer()
        self._play_base = 0.0
        self._audio_clock = QElapsedTimer()
        self._last_audio_pos = -1
        if AUDIO_SUPPORTED:
            try:
                self.audio_output = QAudioOutput(self)
                self.audio_player = QMediaPlayer(self)
                self.audio_player.setAudioOutput(self.audio_output)
                self.audio_player.errorOccurred.connect(self.on_audio_error)
                self.audio_player.tracksChanged.connect(lambda: self.apply_preview_track())
            except Exception as e:
                log.warning(f"Preview audio unavailable: {e}")
                self.audio_player = None
                self.audio_output = None

        self.build_ui()
        self.apply_stylesheet(colorblind_mode=ui.get("colorblind", False))
        self.cb_toggle.setChecked(ui.get("colorblind", False))
        self.restore_combo(self.accel_combo, ui.get("accel", "auto"))
        self.restore_combo(self.model_combo, ui.get("model", "base"))
        self.restore_combo(self.lang_combo, ui.get("language", ""))
        self.vertical_checkbox.setChecked(bool(ui.get("vertical", False)))
        self.crop_slider.setValue(int(ui.get("crop", 50)))
        self.volume_slider.setValue(int(ui.get("volume", 80)))
        self.set_muted(bool(ui.get("muted", False)))
        self.apply_export_mode_labels()
        self.handle_accel_change()
        self.refresh_presets()
        self.sync_style_widgets()
        self._loading = False
        self.save_ui_settings()
        self.update_controls()
        self.refresh_preview()

        self.font_worker = FontScanWorker()
        self.font_worker.done.connect(self.on_fonts_loaded)
        self.font_worker.start()

        self.hw_info = "Checking for a GPU..."
        self.handle_accel_change()
        self.hw_probe = HardwareProbe()
        self.hw_probe.done.connect(self.on_hardware_probed)
        self.hw_probe.start()

        self.build_menus()
        self.restore_window_geometry()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start(90 * 1000)  # every 90 seconds while there are unsaved edits
        self.update_title()

        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence.Delete, self.caption_list, activated=self.toggle_hidden_selected)
        QShortcut(QKeySequence("Shift+Delete"), self.caption_list, activated=self.delete_selected_words)
        for n in range(10):  # 1-9 = set voice, 0 = no voice
            QShortcut(QKeySequence(str(n)), self.caption_list,
                      activated=lambda n=n: self.assign_voice_selected(None if n == 0 else n - 1))

    # ------------------------------------------------------------------ styling
    def apply_stylesheet(self, colorblind_mode=False):
        primary = "#1565C0" if colorblind_mode else "#00ADB5"
        primary_hover = "#1976D2" if colorblind_mode else "#00FFF5"
        text_accent = "#FFFFFF" if colorblind_mode else "#121212"
        self.accent_color, self.accent_text = primary, text_accent   # used by the guide window
        danger_hover = "#D32F2F" if colorblind_mode else "#3A1E1E"
        danger_text = "#FFFFFF" if colorblind_mode else "#FF5A5A"

        qss = f"""
            QMainWindow, QDialog, QMessageBox, QInputDialog, QColorDialog {{ background-color: #121212; }}
            QWidget {{ color: #E0E0E0; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QFrame#ControlPanel {{ background-color: #1E1E1E; border-radius: 8px; border: 1px solid #2D2D2D; }}
            QLabel#StatusLabel {{ font-weight: bold; color: {primary}; font-size: 14px; padding: 5px; }}
            QLabel#HintLabel {{ color: #888888; font-size: 11px; }}
            QLabel#PanelTitle {{ font-weight: bold; }}
            QPushButton {{ background-color: #2D2D2D; border: 1px solid #3D3D3D; border-radius: 5px; padding: 7px 12px; font-weight: 600; min-height: 18px; }}
            QPushButton:hover {{ background-color: #3D3D3D; border-color: {primary}; }}
            QPushButton:pressed {{ background-color: #222831; }}
            QPushButton:disabled {{ background-color: #151515; color: #555555; border-color: #222222; }}
            QPushButton#ExportBtn {{ background-color: {primary}; color: #EEEEEE; border: none; }}
            QPushButton#ExportBtn:hover {{ background-color: {primary_hover}; color: {text_accent}; }}
            QPushButton#ExportBtn:disabled {{ background-color: #1A3A3A; color: #666666; }}
            QPushButton#StepBtn {{ padding: 2px 0px; font-size: 16px; font-weight: bold; min-height: 22px; }}
            QPushButton#ExitBtn, QPushButton#CancelBtn {{ background-color: #252525; color: {danger_text}; border: 1px solid #3D3D3D; }}
            QPushButton#ExitBtn:hover, QPushButton#CancelBtn:hover {{ background-color: {danger_hover}; border-color: #FF5A5A; color: #FFFFFF; }}
            QLineEdit {{ background-color: #151515; border: 1px solid #2D2D2D; border-radius: 5px; padding: 5px; color: #E0E0E0; }}
            QSpinBox, QDoubleSpinBox {{ background-color: #151515; border: 1px solid #2D2D2D; border-radius: 5px; padding: 3px 2px; color: #E0E0E0; }}
            QSpinBox[stepper="true"]::up-button, QSpinBox[stepper="true"]::down-button,
            QDoubleSpinBox[stepper="true"]::up-button, QDoubleSpinBox[stepper="true"]::down-button {{ width: 0px; border: none; }}
            QSpinBox[stepper="true"]::up-arrow, QSpinBox[stepper="true"]::down-arrow,
            QDoubleSpinBox[stepper="true"]::up-arrow, QDoubleSpinBox[stepper="true"]::down-arrow {{ width: 0px; height: 0px; }}
            QSpinBox:disabled, QDoubleSpinBox:disabled {{ background-color: #121212; color: #555555; border-color: #222222; }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {primary}; }}
            QComboBox {{ background-color: #151515; border: 1px solid #2D2D2D; border-radius: 5px; padding: 5px; color: #E0E0E0; }}
            QComboBox:on {{ border-color: {primary}; }}
            QComboBox QAbstractItemView {{ background-color: #151515; color: #E0E0E0; selection-background-color: {primary}; selection-color: {text_accent}; }}
            QTreeWidget {{ background-color: #151515; border: 1px solid #2D2D2D; border-radius: 6px; padding: 4px; }}
            QTreeWidget::item {{ padding: 3px 2px; }}
            QTreeWidget::item:selected {{ background-color: {primary}; color: {text_accent}; }}
            QHeaderView::section {{ background-color: #1E1E1E; color: #9A9A9A; border: none; padding: 4px 6px; font-weight: bold; }}
            QMenuBar {{ background-color: #121212; color: #E0E0E0; padding: 2px 6px; }}
            QMenuBar::item {{ padding: 5px 10px; border-radius: 4px; background: transparent; }}
            QMenuBar::item:selected {{ background-color: #2D2D2D; }}
            QMenu {{ background-color: #1E1E1E; border: 1px solid #2D2D2D; padding: 4px; }}
            QMenu::item {{ padding: 6px 22px 6px 22px; }}
            QMenu::item:selected {{ background-color: {primary}; color: {text_accent}; }}
            QMenu::separator {{ height: 1px; background: #2D2D2D; margin: 4px 8px; }}
            QProgressBar {{ background-color: #151515; border: 1px solid #2D2D2D; border-radius: 4px; text-align: center; color: #EEEEEE; font-weight: bold; height: 20px; }}
            QProgressBar::chunk {{ background-color: {primary}; border-radius: 3px; }}
            QCheckBox {{ spacing: 8px; padding-top: 4px; padding-bottom: 4px; font-weight: bold; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; background-color: #151515; border: 1px solid #2D2D2D; border-radius: 3px; }}
            QCheckBox::indicator:checked {{ background-color: {primary}; border-color: {primary}; }}
            QSlider::groove:horizontal {{ height: 6px; background: #2D2D2D; border-radius: 3px; }}
            QSlider::sub-page:horizontal {{ background: {primary}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: #E0E0E0; width: 14px; margin: -5px 0; border-radius: 7px; }}
            QScrollBar:vertical {{ background: #151515; width: 10px; margin: 0; border-radius: 5px; }}
            QScrollBar::handle:vertical {{ background: #3D3D3D; min-height: 30px; border-radius: 5px; }}
            QScrollBar::handle:vertical:hover {{ background: {primary}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
            QSplitter::handle {{ background: transparent; }}
            QSplitter::handle:vertical {{ height: 10px; }}
            QSplitter::handle:hover {{ background: {primary}; border-radius: 3px; }}
            QToolTip {{ background-color: #1E1E1E; color: #E0E0E0; border: 1px solid {primary}; }}
        """
        # Set on the whole app so pop-up dialogs get the dark theme too (no light-grey boxes)
        QApplication.instance().setStyleSheet(qss)
        self.drop_zone.set_accent(primary, primary_hover)

    def change_ui_theme(self, state):
        on = self.cb_toggle.isChecked()
        self.apply_stylesheet(colorblind_mode=on)
        self.settings["ui"]["colorblind"] = on
        save_settings(self.settings)

    # ------------------------------------------------------------------ UI build
    def make_panel(self, title):
        panel = QFrame()
        panel.setObjectName("ControlPanel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(7)
        if title:
            label = QLabel(title)
            label.setObjectName("PanelTitle")
            layout.addWidget(label)
        return panel, layout

    @staticmethod
    def stepper(spin):
        """[-] [value] [+] — big buttons instead of the tiny spin arrows (which Windows 11 mangles when themed)."""
        spin.setProperty("stepper", True)  # theme hides the tiny arrows (NoButtons blanks the text when themed)
        spin.setAlignment(Qt.AlignCenter)
        spin.setMinimumWidth(72)
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        minus, plus = QPushButton("−"), QPushButton("+")
        for button, action in ((minus, spin.stepDown), (plus, spin.stepUp)):
            button.setObjectName("StepBtn")
            button.setFixedWidth(30)
            button.setAutoRepeat(True)  # hold to keep changing
            button.setAutoRepeatDelay(400)
            button.setAutoRepeatInterval(80)
            button.clicked.connect(action)
        layout.addWidget(minus)
        layout.addWidget(spin, 1)
        layout.addWidget(plus)
        spin.stepper_box = box
        return box

    @staticmethod
    def compact_combo(combo):
        """Stop a dropdown from stretching to its longest entry (that pushed the sidebar off-screen)."""
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.view().setTextElideMode(Qt.ElideNone)

    def fit_sidebar(self):
        """Make sure the sidebar is always wide enough to show every control, then restore the user's divider."""
        content = self.sidebar_scroll.widget()
        needed = content.minimumSizeHint().width() + self.sidebar_scroll.verticalScrollBar().sizeHint().width() + 6
        self.sidebar_scroll.setMinimumWidth(needed)
        saved = self.settings["ui"].get("sidebar_width")
        width = max(needed, int(saved) if saved else needed + 20)
        total = max(self.splitter.width(), width + 420)
        self.splitter.setSizes([width, total - width])

    @staticmethod
    def hint(text):
        label = QLabel(text)
        label.setObjectName("HintLabel")
        label.setWordWrap(True)
        return label

    def build_ui(self):
        window_wrapper = QVBoxLayout()
        window_wrapper.setContentsMargins(15, 10, 15, 15)
        window_wrapper.setSpacing(10)

        header = QHBoxLayout()
        version_label = QLabel(f"v{APP_VERSION_FULL}" + ("  ·  Portable" if PORTABLE else ""))
        version_label.setObjectName("HintLabel")
        header.addWidget(version_label)
        self.data_btn = QPushButton("📂 Logs && Settings")
        self.data_btn.setToolTip(f"Open the folder with the log file and settings (send debug_log.txt with bug reports)\n{DATA_DIR}")
        self.data_btn.clicked.connect(lambda: self.open_folder(DATA_DIR, is_dir=True))
        header.addWidget(self.data_btn)
        header.addStretch()
        self.cb_toggle = QCheckBox("Deuteranopia (Red-Green) Vision Assist")
        self.cb_toggle.stateChanged.connect(self.change_ui_theme)
        header.addWidget(self.cb_toggle)
        window_wrapper.addLayout(header)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)

        # ---------------- sidebar (scrolls on smaller screens)
        sidebar_widget = QWidget()
        sidebar = QVBoxLayout(sidebar_widget)
        sidebar.setContentsMargins(0, 0, 6, 0)
        sidebar.setSpacing(10)

        self.drop_zone = DropZone(self.open_any_file)
        sidebar.addWidget(self.drop_zone)

        # Project
        panel, lay = self.make_panel(None)
        self.label = QLabel("Ready")
        self.label.setObjectName("StatusLabel")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)
        grid = QGridLayout()
        self.import_btn = QPushButton("Import Video")
        self.import_btn.clicked.connect(self.load_video)
        self.open_proj_btn = QPushButton("Open Project")
        self.open_proj_btn.clicked.connect(self.open_project)
        self.save_proj_btn = QPushButton("Save Project")
        self.save_proj_btn.clicked.connect(self.save_project)
        grid.addWidget(self.import_btn, 0, 0, 1, 2)
        grid.addWidget(self.open_proj_btn, 1, 0)
        grid.addWidget(self.save_proj_btn, 1, 1)
        lay.addLayout(grid)
        sidebar.addWidget(panel)

        # Transcription
        panel, lay = self.make_panel("Transcription")
        self.model_combo = QComboBox()
        self.compact_combo(self.model_combo)
        for key, text in WHISPER_MODELS:
            self.model_combo.addItem(text, userData=key)
        self.refresh_model_labels()
        self.model_combo.currentIndexChanged.connect(self.save_ui_settings)
        self.lang_combo = QComboBox()
        self.compact_combo(self.lang_combo)
        for key, text in LANGUAGES:
            self.lang_combo.addItem(text, userData=key)
        self.lang_combo.currentIndexChanged.connect(self.save_ui_settings)
        self.accel_combo = QComboBox()
        self.compact_combo(self.accel_combo)
        self.accel_combo.addItem("🔄 Auto-Select Hardware", userData="auto")
        self.accel_combo.addItem("🚀 Force GPU (NVIDIA CUDA)", userData="cuda")
        self.accel_combo.addItem("🐌 Force CPU Standard Mode", userData="cpu")
        self.accel_combo.currentIndexChanged.connect(self.handle_accel_change)
        self.hardware_status_lbl = self.hint("")
        self.gen_btn = QPushButton("Generate Captions")
        self.gen_btn.clicked.connect(self.generate)
        lay.addWidget(self.model_combo)
        lay.addWidget(self.hint("Models marked 'downloads on first use' need internet once (75 MB – 1.5 GB)."))
        self.track_label = self.hint("Audio track to caption. If you record your mic on its own track "
                                     "(OBS: Settings › Output › Recording › Audio Track), pick it here "
                                     "to caption only your voice and not the game.")
        self.track_combo = QComboBox()
        self.compact_combo(self.track_combo)
        self.track_combo.currentIndexChanged.connect(self.on_track_changed)
        lay.addWidget(self.track_combo)
        lay.addWidget(self.track_label)
        self.track_combo.hide()
        self.track_label.hide()
        lay.addWidget(self.lang_combo)
        lay.addWidget(self.accel_combo)
        lay.addWidget(self.hardware_status_lbl)
        lay.addWidget(self.gen_btn)
        sidebar.addWidget(panel)

        # Voices
        panel, lay = self.make_panel("Voices")
        row = QHBoxLayout()
        row.addWidget(QLabel("Number of voices"))
        self.voice_count_combo = QComboBox()
        self.voice_count_combo.addItem("Auto", userData=None)
        for n in range(1, 9):
            self.voice_count_combo.addItem(str(n), userData=n)
        self.voice_count_combo.setToolTip("How many different people talk in this video. Setting it gives the best results.")
        row.addWidget(self.voice_count_combo, 1)
        lay.addLayout(row)
        self.detect_btn = QPushButton("🎙 Detect Voices")
        self.detect_btn.setToolTip("Find who is talking and give each voice its own colour")
        self.detect_btn.clicked.connect(lambda: self.detect_voices())
        lay.addWidget(self.detect_btn)
        self.auto_detect_cb = QCheckBox("Detect voices after transcribing")
        lay.addWidget(self.auto_detect_cb)
        lay.addWidget(self.hint("Groups lines by who is speaking. Set the number of people for the best results, "
                                "then rename the voices and fix mistakes in the transcript (select lines, press 1-9). "
                                "Game characters usually get their own voice, so you can hide them all at once."))
        self.voices_container = QWidget()
        self.voices_box = QVBoxLayout(self.voices_container)
        self.voices_box.setContentsMargins(0, 0, 0, 0)
        self.voices_box.setSpacing(4)
        lay.addWidget(self.voices_container)
        self.add_voice_btn = QPushButton("+ Add Voice")
        self.add_voice_btn.clicked.connect(lambda: self.add_voice())
        lay.addWidget(self.add_voice_btn)
        grid = QGridLayout()
        self.voice_colors_btn = QPushButton()
        self.voice_colors_btn.setToolTip("Off: normal highlight colour · Highlight: the spoken word uses the voice colour · "
                                         "Whole line: the whole caption uses the voice colour")
        self.voice_colors_btn.clicked.connect(self.toggle_voice_colors)
        self.voice_names_btn = QPushButton()
        self.voice_names_btn.setToolTip("Show the voice's name in front of each caption, e.g. \"Vyper: let's go\"")
        self.voice_names_btn.clicked.connect(self.toggle_voice_names)
        grid.addWidget(self.voice_colors_btn, 0, 0)
        grid.addWidget(self.voice_names_btn, 0, 1)
        lay.addLayout(grid)
        sidebar.addWidget(panel)

        # Fonts
        panel, lay = self.make_panel("Font")
        self.font_search = QLineEdit()
        self.font_search.setPlaceholderText("🔍 Search fonts...")
        self.font_search.textChanged.connect(self.refresh_fonts)
        self.font_combo = QComboBox()
        self.compact_combo(self.font_combo)
        self.font_combo.addItem("Loading fonts...")
        self.font_combo.currentIndexChanged.connect(self.select_font)
        self.fav_btn = QPushButton("⭐ Favorite Font")
        self.fav_btn.clicked.connect(self.toggle_favorite)
        lay.addWidget(self.font_search)
        lay.addWidget(self.font_combo)
        lay.addWidget(self.fav_btn)
        sidebar.addWidget(panel)

        # Caption style
        panel, lay = self.make_panel("Caption Styling")
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.compact_combo(self.preset_combo)
        self.preset_combo.activated.connect(self.apply_preset)
        self.preset_save_btn = QPushButton("Save")
        self.preset_save_btn.setToolTip("Save the current look as a preset")
        self.preset_save_btn.clicked.connect(self.save_preset)
        self.preset_del_btn = QPushButton("Delete")
        self.preset_del_btn.clicked.connect(self.delete_preset)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.preset_save_btn)
        preset_row.addWidget(self.preset_del_btn)
        lay.addLayout(preset_row)

        grid = QGridLayout()
        self.text_btn = QPushButton("Text")
        self.text_btn.clicked.connect(lambda: self.pick_color("text_color"))
        self.hl_btn = QPushButton("Highlight")
        self.hl_btn.clicked.connect(lambda: self.pick_color("highlight_color"))
        self.outline_color_btn = QPushButton("Outline")
        self.outline_color_btn.clicked.connect(lambda: self.pick_color("outline_color"))
        grid.addWidget(self.text_btn, 0, 0)
        grid.addWidget(self.hl_btn, 0, 1)
        grid.addWidget(self.outline_color_btn, 0, 2)
        lay.addLayout(grid)

        grid = QGridLayout()
        self.bg_btn = QPushButton()
        self.bg_btn.clicked.connect(self.toggle_background)
        self.outline_btn = QPushButton()
        self.outline_btn.clicked.connect(self.toggle_outline)
        self.pos_btn = QPushButton()
        self.pos_btn.clicked.connect(self.toggle_position)
        self.mode_btn = QPushButton()
        self.mode_btn.setToolTip("Sentence: split at . ! ?   Auto: also split when the speaker pauses   Word: one word at a time")
        self.mode_btn.clicked.connect(self.toggle_mode)
        grid.addWidget(self.bg_btn, 0, 0)
        grid.addWidget(self.outline_btn, 0, 1)
        grid.addWidget(self.pos_btn, 1, 0)
        grid.addWidget(self.mode_btn, 1, 1)
        self.shadow_btn = QPushButton()
        self.shadow_btn.setToolTip("Soft drop shadow behind the text (works with or without the background box)")
        self.shadow_btn.clicked.connect(self.toggle_shadow)
        grid.addWidget(self.shadow_btn, 2, 0, 1, 2)
        lay.addLayout(grid)

        grid = QGridLayout()
        grid.addWidget(QLabel("Max words per caption"), 0, 0)
        self.max_words_spin = QSpinBox()
        self.max_words_spin.setRange(1, 30)
        self.max_words_spin.valueChanged.connect(self.on_max_words_changed)
        grid.addWidget(self.stepper(self.max_words_spin), 0, 1)
        self.pause_label = QLabel("Pause before new caption")
        grid.addWidget(self.pause_label, 2, 0)
        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.2, 3.0)
        self.pause_spin.setSingleStep(0.1)
        self.pause_spin.setDecimals(1)
        self.pause_spin.setSuffix(" s")
        self.pause_spin.setToolTip("Auto mode: when nobody speaks for this long, the next words start a new caption")
        self.pause_spin.valueChanged.connect(self.on_pause_split_changed)
        grid.addWidget(self.stepper(self.pause_spin), 2, 1)
        # Drop shadow settings (active when Drop Shadow is ON)
        self.shadow_controls = []
        for row, (key, label, lo, hi, step, suffix, wrap, tip) in enumerate((
                ("shadow_strength", "Shadow strength", 10, 300, 10, " %", False,
                 "How dark the shadow is. Over 100% makes a soft shadow denser and darker."),
                ("shadow_angle", "Shadow angle", 0, 345, 15, "°", True,
                 "Direction the shadow falls: 0° right, 45° down-right, 90° down, 180° left, 270° up."),
                ("shadow_distance", "Shadow distance", 0, 30, 1, "", False,
                 "How far the shadow sits from the text (scales with the text size). 0 = right behind it."),
                ("shadow_softness", "Shadow softness", 0, 100, 10, " %", False,
                 "0% = hard, crisp edge. Higher = softer, more blurred shadow."),
        ), start=5):
            caption = QLabel(label)
            caption.setToolTip(tip)
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setSuffix(suffix)
            spin.setWrapping(wrap)
            spin.setToolTip(tip)
            spin.valueChanged.connect(lambda value, k=key: self.on_style_number(k, value))
            grid.addWidget(caption, row, 0)
            grid.addWidget(self.stepper(spin), row, 1)
            self.shadow_controls.append((key, caption, spin))
        self.shadow_spin = self.shadow_controls[0][2]
        grid.addWidget(QLabel("Text size"), 1, 0)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(40, 250)
        self.size_spin.setSingleStep(5)
        self.size_spin.setSuffix(" %")
        self.size_spin.valueChanged.connect(self.on_size_changed)
        grid.addWidget(self.stepper(self.size_spin), 1, 1)
        height_label = QLabel("Caption height")
        height_tip = "Nudge the captions up (-) or down (+), on top of the Bottom / Center / Top setting."
        height_label.setToolTip(height_tip)
        self.y_offset_spin = QSpinBox()
        self.y_offset_spin.setRange(-40, 40)
        self.y_offset_spin.setSuffix(" %")
        self.y_offset_spin.setToolTip(height_tip)
        self.y_offset_spin.valueChanged.connect(lambda v: self.on_style_number("y_offset", v))
        grid.addWidget(height_label, 3, 0)
        grid.addWidget(self.stepper(self.y_offset_spin), 3, 1)
        timing_label = QLabel("Timing offset")
        timing_tip = ("Shift every caption earlier (-) or later (+) if they feel out of sync with the voice. "
                      "Also applies to exports and SRT/VTT.")
        timing_label.setToolTip(timing_tip)
        self.timing_spin = QDoubleSpinBox()
        self.timing_spin.setRange(-5.0, 5.0)
        self.timing_spin.setSingleStep(0.05)
        self.timing_spin.setDecimals(2)
        self.timing_spin.setSuffix(" s")
        self.timing_spin.setToolTip(timing_tip)
        self.timing_spin.valueChanged.connect(lambda v: self.on_style_number("timing_offset", round(v, 2)))
        grid.addWidget(timing_label, 4, 0)
        grid.addWidget(self.stepper(self.timing_spin), 4, 1)
        lay.addLayout(grid)
        sidebar.addWidget(panel)

        # Export
        panel, lay = self.make_panel("Export")
        self.export_mode_btn = QPushButton()
        self.export_mode_btn.clicked.connect(self.toggle_export_mode)
        self.vertical_checkbox = QCheckBox("Vertical Format (1080x1920)")
        self.vertical_checkbox.stateChanged.connect(self.handle_checkbox_toggle)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.export_btn = QPushButton("Export Overlay")
        self.export_btn.setObjectName("ExportBtn")
        self.export_btn.clicked.connect(self.export)
        self.cancel_btn = QPushButton("Cancel Export")
        self.cancel_btn.setObjectName("CancelBtn")
        self.cancel_btn.clicked.connect(self.cancel_current)
        self.cancel_btn.hide()
        self.subs_btn = QPushButton("Export Subtitles (.srt / .vtt)")
        self.subs_btn.clicked.connect(self.export_subtitles)
        lay.addWidget(self.export_mode_btn)
        lay.addWidget(self.vertical_checkbox)
        crop_row = QHBoxLayout()
        self.crop_label = QLabel("Crop: Left")
        self.crop_slider = QSlider(Qt.Horizontal)
        self.crop_slider.setRange(0, 100)
        self.crop_slider.setValue(50)
        self.crop_slider.setToolTip("Which part of a wide video stays in the 9:16 frame - keep your facecam or the action in view")
        self.crop_slider.valueChanged.connect(self.on_crop_changed)
        crop_row.addWidget(self.crop_label)
        crop_row.addWidget(self.crop_slider, 1)
        crop_right = QLabel("Right")
        crop_row.addWidget(crop_right)
        self.crop_widgets = (self.crop_label, self.crop_slider, crop_right)
        lay.addLayout(crop_row)
        lay.addWidget(self.progress_bar)
        lay.addWidget(self.export_btn)
        lay.addWidget(self.cancel_btn)
        lay.addWidget(self.subs_btn)
        sidebar.addWidget(panel)

        sidebar.addStretch()
        self.exit_btn = QPushButton("❌ Close App")
        self.exit_btn.setObjectName("ExitBtn")
        self.exit_btn.clicked.connect(self.close)
        sidebar.addWidget(self.exit_btn)

        scroll = QScrollArea()
        scroll.setWidget(sidebar_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll = scroll

        # ---------------- center: preview + transport + transcript
        center = QVBoxLayout()
        center.setSpacing(8)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(320, 180)
        self.preview.setStyleSheet("background-color: #0A0A0A; border: 2px solid #1E1E1E; border-radius: 8px;")

        transport = QHBoxLayout()
        self.rewind_btn = QPushButton("⏮")
        self.rewind_btn.setToolTip("Back to start")
        self.rewind_btn.clicked.connect(self.rewind_preview)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.valueChanged.connect(self.on_slider_changed)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setMinimumWidth(90)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        transport.addWidget(self.rewind_btn)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.seek_slider, 1)
        transport.addWidget(self.time_label)
        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setToolTip("Mute / unmute preview sound")
        self.mute_btn.setFixedWidth(46)
        self.mute_btn.clicked.connect(lambda: self.set_muted(not self.is_muted()))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setToolTip("Preview volume")
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        self.volume_slider.sliderReleased.connect(self.save_ui_settings)
        if self.audio_player is None:
            for widget in (self.mute_btn, self.volume_slider):
                widget.setEnabled(False)
                widget.setToolTip("Preview sound isn't available on this PC (Qt Multimedia missing)")
        transport.addWidget(self.mute_btn)
        transport.addWidget(self.volume_slider)

        self.preview_hint = self.hint("")
        self.preview_hint.setAlignment(Qt.AlignCenter)

        editor_bar = QHBoxLayout()
        editor_title = QLabel("<b>Transcript Editor</b>")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search transcript (Ctrl+F)")
        self.search_box.textChanged.connect(self.apply_search)
        self.hide_btn = QPushButton("Hide / Show")
        self.hide_btn.setToolTip("Hide the selected lines or words from the captions, or bring hidden ones back (Delete key)")
        self.hide_btn.clicked.connect(self.toggle_hidden_selected)
        self.voice_btn = QPushButton("Set Voice ▾")
        self.voice_btn.setToolTip("Give the selected lines a voice (or press 1-9; 0 = no voice)")
        self.voice_btn.clicked.connect(lambda: self.voice_menu().exec(self.voice_btn.mapToGlobal(self.voice_btn.rect().bottomLeft())))
        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("Undo (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("Redo (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo)
        editor_bar.addWidget(editor_title)
        editor_bar.addWidget(self.search_box, 1)
        for b in (self.hide_btn, self.voice_btn, self.undo_btn, self.redo_btn):
            editor_bar.addWidget(b)
        editor_hint = self.hint("Click a line to jump there · Double-click to edit · Del hides/shows · Shift+Del deletes · "
                                "1-9 sets the voice · ▸ shows single words · Right-click for more")
        self.caption_list = QTreeWidget()
        self.caption_list.setColumnCount(3)
        self.caption_list.setHeaderLabels(["Time", "Voice", "Caption"])
        self.caption_list.header().setStretchLastSection(True)
        self.caption_list.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.caption_list.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.caption_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.caption_list.setUniformRowHeights(True)
        self.caption_list.itemClicked.connect(self.seek_to_item)
        self.caption_list.itemDoubleClicked.connect(self.edit_caption)
        self.caption_list.itemExpanded.connect(self.populate_line_children)
        self.caption_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.caption_list.customContextMenuRequested.connect(self.show_editor_menu)

        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.addWidget(self.preview, 1)
        top_lay.addLayout(transport)
        top_lay.addWidget(self.preview_hint)
        bottom = QWidget()
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 4, 0, 0)
        bottom_lay.addLayout(editor_bar)
        bottom_lay.addWidget(editor_hint)
        bottom_lay.addWidget(self.caption_list, 1)
        # Draggable divider between the preview and the transcript editor
        self.center_splitter = QSplitter(Qt.Vertical)
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.setHandleWidth(10)
        self.center_splitter.addWidget(top)
        self.center_splitter.addWidget(bottom)
        self.center_splitter.setStretchFactor(0, 3)
        self.center_splitter.setStretchFactor(1, 2)
        saved_split = self.settings["ui"].get("center_split")
        if saved_split:
            QTimer.singleShot(0, lambda: self.center_splitter.setSizes(saved_split))
        self.center_splitter.splitterMoved.connect(lambda *_: self.save_ui_settings())
        center.addWidget(self.center_splitter, 1)

        center_widget = QWidget()
        center_widget.setLayout(center)
        center.setContentsMargins(0, 0, 0, 0)
        # Draggable divider between the settings sidebar and the preview
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.splitter.addWidget(scroll)
        self.splitter.addWidget(center_widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(lambda *_: self.save_ui_settings())
        main_layout.addWidget(self.splitter)
        window_wrapper.addLayout(main_layout)
        QTimer.singleShot(0, self.fit_sidebar)

        container = QWidget()
        container.setLayout(window_wrapper)
        self.setCentralWidget(container)

        self._lockables = [
            self.import_btn, self.open_proj_btn, self.model_combo, self.lang_combo, self.accel_combo,
            self.font_search, self.preset_combo, self.preset_save_btn, self.preset_del_btn,
            self.text_btn, self.hl_btn, self.outline_color_btn, self.bg_btn, self.outline_btn, self.shadow_btn,
            self.pos_btn, self.mode_btn, self.size_spin.stepper_box, self.export_mode_btn, self.caption_list,
            self.y_offset_spin.stepper_box, self.timing_spin.stepper_box,
            self.hide_btn, self.voice_btn, self.voice_count_combo, self.auto_detect_cb, self.voices_container,
            self.add_voice_btn, self.voice_colors_btn, self.voice_names_btn,
        ]

    # ------------------------------------------------------------------ control state
    def update_controls(self):
        idle = self.busy is None
        has_video = self.video_path is not None
        has_words = bool(self.words)
        for widget in self._lockables:
            widget.setEnabled(idle)
        fonts_ready = bool(self.font_map)
        self.font_combo.setEnabled(idle and fonts_ready)
        self.fav_btn.setEnabled(idle and fonts_ready)
        self.gen_btn.setEnabled(idle and has_video)
        self.detect_btn.setEnabled(idle and has_video and has_words)
        self.undo_btn.setEnabled(idle and bool(self._undo))
        self.redo_btn.setEnabled(idle and bool(self._redo))
        self.save_proj_btn.setEnabled(idle and (has_video or has_words))
        self.export_btn.setEnabled(idle and has_video and has_words)
        self.subs_btn.setEnabled(idle and has_words)
        self.vertical_checkbox.setEnabled(idle and self.export_mode == "merge")
        self.max_words_spin.stepper_box.setEnabled(idle and self.style["mode"] in ("sentence", "auto"))
        self.pause_spin.stepper_box.setEnabled(idle and self.style["mode"] == "auto")
        shadow_on = idle and bool(self.style.get("shadow"))
        for _key, caption, spin in self.shadow_controls:
            spin.stepper_box.setEnabled(shadow_on)
            caption.setEnabled(shadow_on)
        self.track_combo.setEnabled(idle)
        self.pause_label.setEnabled(idle and self.style["mode"] == "auto")
        vertical_on = idle and self.export_mode == "merge" and self.vertical_checkbox.isChecked()
        for widget in self.crop_widgets:
            widget.setEnabled(vertical_on)
        self.cancel_btn.setVisible(self.busy in ("export", "transcribe"))
        self.cancel_btn.setText("Cancel Transcription" if self.busy == "transcribe" else "Cancel Export")
        if hasattr(self, "menu_actions"):
            self.update_menu_state()
        self.drop_zone.setAcceptDrops(idle)

    def set_busy(self, reason):
        self.busy = reason
        self.update_controls()

    @staticmethod
    def restore_combo(combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def save_ui_settings(self, *_):
        if getattr(self, "_loading", False):
            return
        ui = self.settings["ui"]
        ui["accel"] = self.accel_combo.currentData()
        ui["model"] = self.model_combo.currentData()
        ui["language"] = self.lang_combo.currentData()
        ui["export_mode"] = self.export_mode
        ui["vertical"] = self.vertical_checkbox.isChecked()
        if hasattr(self, "crop_slider"):
            ui["crop"] = self.crop_slider.value()
        if hasattr(self, "splitter") and self.splitter.sizes()[0] > 0:
            ui["sidebar_width"] = self.splitter.sizes()[0]
        if hasattr(self, "center_splitter") and min(self.center_splitter.sizes()) > 0:
            ui["center_split"] = self.center_splitter.sizes()
        if hasattr(self, "volume_slider"):
            ui["volume"] = self.volume_slider.value()
            ui["muted"] = self.is_muted()
        save_settings(self.settings)

    # ------------------------------------------------------------------ style state
    def sync_style_widgets(self):
        st = self.style
        self.bg_btn.setText("Background: ON" if st["background"] else "Background: OFF")
        self.outline_btn.setText("Outline: ON" if st["outline"] else "Outline: OFF")
        self.shadow_btn.setText("Drop Shadow: ON" if st.get("shadow") else "Drop Shadow: OFF")
        self.voice_colors_btn.setText({"off": "Voice colours: Off", "highlight": "Voice colours: Highlight",
                                       "line": "Voice colours: Whole line"}.get(st.get("voice_colors", "highlight")))
        self.voice_names_btn.setText("Name tags: ON" if st.get("voice_names") else "Name tags: OFF")
        self.pos_btn.setText(f"Align: {st['position'].title()}")
        self.mode_btn.setText({"sentence": "Mode: Sentence", "auto": "Mode: Auto (pauses)",
                               "word": "Mode: Word"}.get(st["mode"], "Mode: Sentence"))
        for spin, value in ((self.max_words_spin, int(st["max_words"])), (self.size_spin, int(st["size"])),
                            (self.pause_spin, float(st.get("pause_split", 0.5))),
                            (self.y_offset_spin, int(st.get("y_offset", 0) or 0)),
                            (self.timing_spin, float(st.get("timing_offset", 0.0) or 0.0))) + tuple(
                (spin, int(st.get(key, DEFAULT_STYLE[key]))) for key, _c, spin in self.shadow_controls):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.update_button_color(self.text_btn, st["text_color"])
        self.update_button_color(self.hl_btn, st["highlight_color"])
        self.update_button_color(self.outline_color_btn, st["outline_color"])
        if self.font_map and st.get("font"):
            index = self.font_combo.findData(st["font"])
            if index >= 0 and index != self.font_combo.currentIndex():
                self.font_combo.blockSignals(True)
                self.font_combo.setCurrentIndex(index)
                self.font_combo.blockSignals(False)
        self.update_controls()

    def on_style_changed(self, rebuild_track=False):
        self.renderer = None
        if rebuild_track:
            self.rebuild_track()
            if self.words:
                self.rebuild_caption_list()
        self.settings["style"] = dict(self.style)
        save_settings(self.settings)
        if not self.preview_running:
            self.refresh_preview()

    def get_renderer(self):
        if self.renderer is None:
            self.renderer = CaptionRenderer(self.style, self.font_map.get(self.style.get("font")), self.voices)
        return self.renderer

    def rebuild_track(self):
        self._word_index = {id(w): i for i, w in enumerate(self.words)}
        self.track = CaptionTrack(self.words, self.style["mode"], self.style["max_words"],
                             self.style.get("pause_split", 0.5)) if self.words else None
        self.renderer = None

    def toggle_background(self):
        self.style["background"] = not self.style["background"]
        self.sync_style_widgets()
        self.on_style_changed()

    def toggle_shadow(self):
        self.style["shadow"] = not self.style.get("shadow", False)
        self.sync_style_widgets()
        self.on_style_changed()

    def on_style_number(self, key, value):
        self.style[key] = value
        self.on_style_changed()

    def toggle_outline(self):
        self.style["outline"] = not self.style["outline"]
        self.sync_style_widgets()
        self.on_style_changed()

    def toggle_position(self):
        order = ["bottom", "center", "top"]
        current = self.style.get("position", "bottom")
        self.style["position"] = order[(order.index(current) + 1) % 3 if current in order else 0]
        self.sync_style_widgets()
        self.on_style_changed()

    def toggle_mode(self):
        order = ["sentence", "auto", "word"]
        current = self.style.get("mode", "sentence")
        self.style["mode"] = order[(order.index(current) + 1) % 3] if current in order else "sentence"
        self.sync_style_widgets()
        self.on_style_changed(rebuild_track=True)

    def on_max_words_changed(self, value):
        self.style["max_words"] = value
        self.on_style_changed(rebuild_track=True)

    def on_pause_split_changed(self, value):
        self.style["pause_split"] = round(value, 2)
        self.on_style_changed(rebuild_track=True)

    def on_size_changed(self, value):
        self.style["size"] = value
        self.on_style_changed()

    def pick_color(self, key):
        current = QColor(*self.style[key])
        color = QColorDialog.getColor(current, self, "Pick a colour")
        if color.isValid():
            self.style[key] = list(color.getRgb()[:3])
            self.sync_style_widgets()
            self.on_style_changed()

    def update_button_color(self, button, rgb):
        r, g, b = rgb
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(r, g, b))
        painter = QPainter(pixmap)
        painter.setPen(QColor(60, 60, 60))
        painter.drawRect(0, 0, 15, 15)
        painter.end()
        button.setIcon(QIcon(pixmap))
        button.setIconSize(QSize(16, 16))

    # ------------------------------------------------------------------ presets
    def refresh_presets(self, select=None):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("— Style presets —", userData=None)
        for name in sorted(self.settings["presets"], key=str.lower):
            self.preset_combo.addItem(name, userData=name)
        if select:
            self.restore_combo(self.preset_combo, select)
        self.preset_combo.blockSignals(False)

    def apply_preset(self, index):
        name = self.preset_combo.itemData(index)
        if not name or name not in self.settings["presets"]:
            return
        preset = self.settings["presets"][name]
        self.style.update({k: copy.deepcopy(v) for k, v in preset.items() if k in DEFAULT_STYLE})
        if self.style.get("font") and self.font_map and self.style["font"] not in self.font_map:
            self.label.setText(f"Preset font '{self.style['font']}' isn't installed")
        self.font_search.blockSignals(True)
        self.font_search.clear()
        self.font_search.blockSignals(False)
        self.refresh_fonts(keep_style_font=True)
        self.sync_style_widgets()
        self.on_style_changed(rebuild_track=True)

    def save_preset(self):
        current = self.preset_combo.currentData() or ""
        name, ok = QInputDialog.getText(self, "Save Style Preset", "Preset name:", text=current)
        name = name.strip()
        if not ok or not name:
            return
        if name in self.settings["presets"] and name != current:
            if QMessageBox.question(self, "Replace preset?", f"A preset named '{name}' already exists. Replace it?") != QMessageBox.Yes:
                return
        self.settings["presets"][name] = copy.deepcopy(self.style)
        save_settings(self.settings)
        self.refresh_presets(select=name)
        self.label.setText(f"Saved preset '{name}'")

    def delete_preset(self):
        name = self.preset_combo.currentData()
        if not name:
            return
        if QMessageBox.question(self, "Delete preset?", f"Delete the preset '{name}'?") != QMessageBox.Yes:
            return
        self.settings["presets"].pop(name, None)
        save_settings(self.settings)
        self.refresh_presets()

    # ------------------------------------------------------------------ fonts
    def on_fonts_loaded(self, fonts):
        self.font_map = fonts
        self.renderer = None
        self.refresh_fonts(keep_style_font=True)
        self.update_controls()
        if not self.preview_running:
            self.refresh_preview()

    def refresh_fonts(self, *_, keep_style_font=False):
        if not self.font_map:
            return
        wanted = self.style.get("font")
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        filter_text = self.font_search.text().lower().strip()
        names = sorted(self.font_map, key=lambda x: (x not in self.favorites, x.lower()))
        for name in names:
            if filter_text and filter_text not in name.lower():
                continue
            self.font_combo.addItem(f"⭐ {name}" if name in self.favorites else name, userData=name)
            self.font_combo.setItemData(self.font_combo.count() - 1,
                                        QFont(self.font_map[name]["family"], 12), Qt.FontRole)
        self.font_combo.blockSignals(False)
        if self.font_combo.count() == 0:
            return
        index = self.font_combo.findData(wanted) if wanted else -1
        if index >= 0:
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentIndex(index)
            self.font_combo.blockSignals(False)
        elif not keep_style_font or not wanted:
            self.font_combo.setCurrentIndex(0)
            self.select_font(0)

    def select_font(self, index):
        name = self.font_combo.itemData(index)
        if not name or name == self.style.get("font"):
            return
        self.style["font"] = name
        self.on_style_changed()

    def toggle_favorite(self):
        name = self.font_combo.currentData()
        if not name:
            return
        if name in self.favorites:
            self.favorites.remove(name)
        else:
            self.favorites.add(name)
        self.settings["favorites"] = sorted(self.favorites)
        save_settings(self.settings)
        self.refresh_fonts(keep_style_font=True)

    # ------------------------------------------------------------------ video loading
    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved captions",
            "You have captions that aren't saved in a project.\nSave them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Save:
            return self.save_project()
        return answer == QMessageBox.Discard

    def load_video(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import Video", "", "Videos (*.mp4 *.mov *.avi *.mkv *.webm *.m4v)")
        if path:
            self.process_dropped_video(path)

    def process_dropped_video(self, video_path):
        if self.busy or not self.confirm_discard():
            return
        if self.open_video(video_path):
            self.words = []
            self.voices = []
            self.reset_history()
            self.rebuild_voice_panel()
            self.rebuild_track()
            self.rebuild_caption_list()
            self.project_path = None
            self.dirty = False
            self.clear_autosave()
            self.progress_bar.setValue(0)
            self.update_controls()
            self.refresh_preview()

    def open_video(self, video_path):
        log.debug(f"Opening video: {video_path}")
        self.pause_preview()
        try:
            info = probe_video(video_path)
        except Exception as e:
            log.error(f"Could not open video {video_path}: {e}")
            self.label.setText("Couldn't open that video")
            QMessageBox.critical(self, "Couldn't open video", str(e))
            return False
        if self.frame_reader:
            self.frame_reader.close_active_stream()
        self.video_path = video_path
        self.video_info = info
        self.frame_reader = VideoFrameReader(video_path, info)
        self.preview_time = 0.0
        self.load_preview_audio(video_path, info["has_audio"])
        self.populate_tracks(info.get("audio_tracks", []))
        self.label.setText(f"Loaded: {os.path.basename(video_path)}")
        self.update_slider_range()
        if not info["has_audio"]:
            self.label.setText("Loaded (warning: this video has no audio)")
        return True

    # ------------------------------------------------------------------ transcription
    def handle_accel_change(self, *_):
        mode = self.accel_combo.currentData()
        text = {
            "auto": "Uses your NVIDIA GPU if one is available, otherwise the CPU.",
            "cuda": "Always tries the NVIDIA GPU (falls back to CPU if it fails).",
            "cpu": "CPU only: slower, but works on any PC.",
        }.get(mode, "")
        self.hardware_status_lbl.setText(text + (f"\n{self.hw_info}" if getattr(self, "hw_info", "") else ""))
        self.save_ui_settings()

    def on_hardware_probed(self, message, gpu_ok):
        self.hw_info = message
        self.handle_accel_change()

    def generate(self):
        if not self.video_path or self.busy:
            return
        if self.video_info and not self.video_info["has_audio"]:
            QMessageBox.warning(self, "No audio", "This video has no audio track, so there's nothing to transcribe.")
            return
        if self.words and QMessageBox.question(
                self, "Replace captions?", "This replaces the current transcript and any edits. Continue?") != QMessageBox.Yes:
            return
        self.pause_preview()
        self.label.setText("Starting transcription...")
        self.progress_bar.setRange(0, 0)
        self.set_busy("transcribe")
        self.transcription_worker = TranscriptionWorker(
            self.video_path, self.accel_combo.currentData(),
            self.model_combo.currentData(), self.lang_combo.currentData(), self.selected_track())
        self.transcription_worker.succeeded.connect(self.on_transcription_success)
        self.transcription_worker.failed.connect(self.on_transcription_failure)
        self.transcription_worker.fallback_warning.connect(self.show_fallback_dialog)
        self.transcription_worker.status.connect(self.label.setText)
        self.transcription_worker.progress.connect(self.on_transcription_progress)
        self.transcription_worker.cancelled.connect(self.on_transcription_cancelled)
        self.transcription_worker.start()

    def show_fallback_dialog(self, error_msg):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Hardware Redirection")
        msg.setText("GPU acceleration failed!")
        msg.setInformativeText("Your graphics driver setup couldn't start the GPU, so Bones Caption Studio "
                               "switched this transcription to your CPU instead. It will take longer.")
        msg.setDetailedText(error_msg)
        msg.show()

    def on_transcription_success(self, result, device):
        self.refresh_model_labels()
        words = []
        for segment in result.get("segments", []):
            for w in segment.get("words", []) or []:
                text = str(w.get("word", "")).strip()
                if not text:
                    continue
                start, end = float(w.get("start", 0.0)), float(w.get("end", 0.0))
                words.append({"word": text, "start": start, "end": max(start, end)})
        words.sort(key=lambda x: x["start"])
        self.words = words
        self.reset_history()
        self.rebuild_track()
        self.rebuild_caption_list()
        self.rebuild_voice_panel()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if words else 0)
        self.set_busy(None)
        if words:
            self.dirty = True
            self.label.setText(f"{len(words)} words transcribed ({'GPU' if device == 'cuda' else 'CPU'}). Ready to export")
        else:
            self.label.setText("No speech was detected")
        self.preview_time = 0.0
        self.refresh_preview()
        if words and self.auto_detect_cb.isChecked():
            QTimer.singleShot(0, lambda: self.detect_voices(ask=False))

    def on_transcription_failure(self, error_message):
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.set_busy(None)
        self.label.setText("Transcription failed")
        QMessageBox.critical(self, "Transcription failed", error_message)

    # ------------------------------------------------------------------ transcript editor
    # ------------------------------------------------------------------ transcript editor
    GREY = QColor(110, 110, 110)

    def voice_icon(self, speaker):
        pixmap = QPixmap(12, 12)
        if isinstance(speaker, int) and 0 <= speaker < len(self.voices):
            pixmap.fill(QColor(*self.voices[speaker]["color"]))
        else:
            pixmap.fill(Qt.transparent)
        return QIcon(pixmap)

    def voice_name(self, speaker):
        if isinstance(speaker, int) and 0 <= speaker < len(self.voices):
            return self.voices[speaker]["name"]
        return ""

    @staticmethod
    def strike(item, on):
        for col in range(3):
            font = item.font(col)
            font.setStrikeOut(on)
            item.setFont(col, font)
            item.setForeground(col, MainWindow.GREY if on else QColor(224, 224, 224))

    def rebuild_caption_list(self):
        """Transcript as caption lines (expand a line to edit single words)."""
        tree = self.caption_list
        expanded = set()
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.isExpanded():
                data = item.data(0, Qt.UserRole)
                if data and data[1] < len(self._editor_lines) and self._editor_lines[data[1]]:
                    first = self._editor_lines[data[1]][0]
                    if first < len(self.words):
                        expanded.add(id(self.words[first]))
        scroll = tree.verticalScrollBar().value()
        tree.blockSignals(True)
        tree.clear()
        groups = build_groups(self.words, self.style["mode"], self.style["max_words"],
                              self.style.get("pause_split", 0.5)) if self.words else []
        self._editor_lines = [g["idx"] for g in groups]
        self._line_of_word = [0] * len(self.words)
        items = []
        for li, idxs in enumerate(self._editor_lines):
            for i in idxs:
                self._line_of_word[i] = li
            item = QTreeWidgetItem()
            item.setData(0, Qt.UserRole, ("line", li))
            self.fill_line_item(item, idxs)
            if len(idxs) > 1:
                item.addChild(QTreeWidgetItem(["", "", "…"]))  # filled in when expanded
            items.append(item)
        tree.addTopLevelItems(items)
        for item, idxs in zip(items, self._editor_lines):
            if id(self.words[idxs[0]]) in expanded:
                item.setExpanded(True)
                self.populate_line_children(item)
        tree.blockSignals(False)
        tree.verticalScrollBar().setValue(scroll)
        self.apply_search()
        self._last_list_row = -1

    def fill_line_item(self, item, idxs):
        visible = [i for i in idxs if not self.words[i].get("hidden")]
        hidden = len(idxs) - len(visible)
        if visible:
            text = " ".join(self.words[i]["word"] for i in visible)
            if hidden:
                text += f"    ({hidden} hidden)"
        else:
            text = " ".join(self.words[i]["word"] for i in idxs)
        speaker = self.words[idxs[0]].get("speaker")
        item.setText(0, fmt_clock(self.words[idxs[0]]["start"], True))
        item.setText(1, self.voice_name(speaker))
        item.setIcon(1, self.voice_icon(speaker))
        item.setText(2, text)
        self.strike(item, not visible)

    def populate_line_children(self, item):
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != "line" or data[1] >= len(self._editor_lines):
            return
        if item.childCount() and item.child(0).data(0, Qt.UserRole):
            return  # already filled
        self.caption_list.blockSignals(True)
        item.takeChildren()
        for i in self._editor_lines[data[1]]:
            w = self.words[i]
            child = QTreeWidgetItem([fmt_clock(w["start"], True), self.voice_name(w.get("speaker")), w["word"]])
            child.setIcon(1, self.voice_icon(w.get("speaker")))
            child.setData(0, Qt.UserRole, ("word", i))
            self.strike(child, bool(w.get("hidden")))
            item.addChild(child)
        self.caption_list.blockSignals(False)

    def selected_word_indices(self):
        chosen = set()
        for item in self.caption_list.selectedItems():
            data = item.data(0, Qt.UserRole)
            if not data:
                continue
            if data[0] == "line" and data[1] < len(self._editor_lines):
                chosen.update(self._editor_lines[data[1]])
            elif data[0] == "word" and data[1] < len(self.words):
                chosen.add(data[1])
        return sorted(chosen)

    def apply_search(self, *_):
        needle = self.search_box.text().lower().strip()
        for li in range(self.caption_list.topLevelItemCount()):
            item = self.caption_list.topLevelItem(li)
            if not needle:
                item.setHidden(False)
                continue
            text = " ".join(self.words[i]["word"] for i in self._editor_lines[li]).lower()
            item.setHidden(needle not in text and needle not in item.text(1).lower())

    def seek_to_item(self, item, *_):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        if data[0] == "line" and data[1] < len(self._editor_lines):
            idxs = self._editor_lines[data[1]]
            visible = [i for i in idxs if not self.words[i].get("hidden")] or idxs
            t = self.words[visible[0]]["start"]
        elif data[0] == "word" and data[1] < len(self.words):
            t = self.words[data[1]]["start"]
        else:
            return
        self.preview_time = t + 0.01
        self.sync_play_position()
        self.refresh_preview()

    # ---- undo / redo
    def push_undo(self):
        self._undo.append((copy.deepcopy(self.words), copy.deepcopy(self.voices)))
        del self._undo[:-60]
        self._redo.clear()

    def _restore(self, snapshot):
        self.words, self.voices = snapshot
        self.renderer = None
        self.rebuild_voice_panel()
        self.after_words_edited()

    def undo(self):
        if self.busy or not self._undo:
            return
        self._redo.append((copy.deepcopy(self.words), copy.deepcopy(self.voices)))
        self._restore(self._undo.pop())
        self.label.setText("Undone")

    def redo(self):
        if self.busy or not self._redo:
            return
        self._undo.append((copy.deepcopy(self.words), copy.deepcopy(self.voices)))
        self._restore(self._redo.pop())
        self.label.setText("Redone")

    def reset_history(self):
        self._undo.clear()
        self._redo.clear()

    # ---- editing actions
    def toggle_hidden_selected(self):
        idxs = self.selected_word_indices()
        if self.busy or not idxs:
            return
        self.push_undo()
        hide = not all(self.words[i].get("hidden") for i in idxs)
        for i in idxs:
            if hide:
                self.words[i]["hidden"] = True
            else:
                self.words[i].pop("hidden", None)
        self.after_words_edited()
        self.label.setText(f"{'Hid' if hide else 'Restored'} {len(idxs)} word(s)")

    def delete_selected_words(self):
        idxs = self.selected_word_indices()
        if self.busy or not idxs:
            return
        if QMessageBox.question(self, "Delete permanently?",
                                f"Delete {len(idxs)} word(s) from the transcript?\n"
                                "(Hide keeps them so you can bring them back. Undo also works.)") != QMessageBox.Yes:
            return
        self.push_undo()
        for i in reversed(idxs):
            del self.words[i]
        self.after_words_edited()

    def edit_caption(self, item, *_):
        data = item.data(0, Qt.UserRole)
        if self.busy or not data:
            return
        if data[0] == "word":
            i = data[1]
            new, ok = QInputDialog.getText(self, "Edit Word", "Text (leave empty to delete the word):",
                                           text=self.words[i]["word"])
            if not ok:
                return
            self.push_undo()
            new = new.strip()
            if new:
                self.words[i]["word"] = new
            else:
                del self.words[i]
            self.after_words_edited()
            return
        idxs = self._editor_lines[data[1]]
        visible = [i for i in idxs if not self.words[i].get("hidden")]
        if not visible:
            return
        old = " ".join(self.words[i]["word"] for i in visible)
        new, ok = QInputDialog.getText(self, "Edit Line", "Fix the words in this line:", text=old)
        if not ok or new.strip() == old:
            return
        self.push_undo()
        new_words = new.split()
        if len(new_words) == len(visible):
            for i, text in zip(visible, new_words):
                self.words[i]["word"] = text
        else:  # different word count: spread the new words evenly over the line's time
            start, end = self.words[visible[0]]["start"], self.words[visible[-1]]["end"]
            speaker = self.words[visible[0]].get("speaker")
            for i in reversed(visible):
                del self.words[i]
            step = (end - start) / max(len(new_words), 1)
            for n, text in enumerate(new_words):
                w = {"word": text, "start": start + n * step, "end": start + (n + 1) * step}
                if speaker is not None:
                    w["speaker"] = speaker
                self.words.append(w)
            self.words.sort(key=lambda w: w["start"])
        self.after_words_edited()

    # ---- voices
    def voice_template(self, n):
        saved = self.settings.get("voices", [])
        if n < len(saved) and saved[n].get("name"):
            return {"name": saved[n]["name"], "color": list(saved[n].get("color", VOICE_PALETTE[n % 8]))}
        return default_voice(n)

    def remember_voices(self):
        saved = self.settings.setdefault("voices", [])
        for n, v in enumerate(self.voices):
            if n < len(saved):
                saved[n] = copy.deepcopy(v)
            else:
                saved.append(copy.deepcopy(v))
        save_settings(self.settings)

    def ensure_voices(self, count):
        while len(self.voices) < count:
            self.voices.append(self.voice_template(len(self.voices)))

    def voice_menu(self):
        menu = QMenu(self)
        none = menu.addAction("No voice  (0)")
        none.triggered.connect(lambda: self.assign_voice_selected(None))
        for n, v in enumerate(self.voices):
            act = menu.addAction(self.voice_icon(n), f"{v['name']}  ({n + 1})" if n < 9 else v["name"])
            act.triggered.connect(lambda _=False, n=n: self.assign_voice_selected(n))
        menu.addSeparator()
        new = menu.addAction("+ New voice")
        new.triggered.connect(lambda: self.assign_voice_selected(len(self.voices)))
        return menu

    def assign_voice_selected(self, voice):
        idxs = self.selected_word_indices()
        if self.busy or not idxs:
            return
        self.push_undo()
        if voice is not None:
            self.ensure_voices(voice + 1)
        for i in idxs:
            if voice is None:
                self.words[i].pop("speaker", None)
            else:
                self.words[i]["speaker"] = voice
        self.renderer = None
        self.rebuild_voice_panel()
        self.after_words_edited()
        self.label.setText(f"{len(idxs)} word(s) set to {self.voice_name(voice) or 'no voice'}")

    def show_editor_menu(self, pos):
        item = self.caption_list.itemAt(pos)
        if self.busy or item is None:
            return
        if not item.isSelected():
            self.caption_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Hide / Show  (Del)").triggered.connect(self.toggle_hidden_selected)
        menu.addAction("Delete permanently  (Shift+Del)").triggered.connect(self.delete_selected_words)
        voice_sub = self.voice_menu()
        voice_sub.setTitle("Set voice")
        menu.addMenu(voice_sub)
        menu.addAction("Edit...").triggered.connect(lambda: self.edit_caption(item))
        idxs = self.selected_word_indices()
        speakers = {self.words[i].get("speaker") for i in idxs} - {None}
        if len(speakers) == 1:
            v = speakers.pop()
            menu.addSeparator()
            menu.addAction(f"Hide every line from {self.voice_name(v)}").triggered.connect(lambda: self.set_voice_hidden(v, True))
            menu.addAction(f"Show every line from {self.voice_name(v)}").triggered.connect(lambda: self.set_voice_hidden(v, False))
        menu.addSeparator()
        menu.addAction("Expand all").triggered.connect(self.caption_list.expandAll)
        menu.addAction("Collapse all").triggered.connect(self.caption_list.collapseAll)
        menu.exec(self.caption_list.viewport().mapToGlobal(pos))

    def set_voice_hidden(self, voice, hide):
        idxs = [i for i, w in enumerate(self.words) if w.get("speaker") == voice]
        if self.busy or not idxs:
            return
        self.push_undo()
        for i in idxs:
            if hide:
                self.words[i]["hidden"] = True
            else:
                self.words[i].pop("hidden", None)
        self.rebuild_voice_panel()
        self.after_words_edited()
        self.label.setText(f"{'Hid' if hide else 'Showed'} every line from {self.voice_name(voice)}")

    def add_voice(self):
        if self.busy:
            return
        self.push_undo()
        self.ensure_voices(len(self.voices) + 1)
        self.rebuild_voice_panel()
        self.after_words_edited(rebuild_list=False)

    def remove_voice(self, n):
        if self.busy or not 0 <= n < len(self.voices):
            return
        self.push_undo()
        for w in self.words:
            sp = w.get("speaker")
            if sp == n:
                w.pop("speaker", None)
            elif isinstance(sp, int) and sp > n:
                w["speaker"] = sp - 1
        del self.voices[n]
        self.renderer = None
        self.rebuild_voice_panel()
        self.after_words_edited()

    def rename_voice(self, n, edit):
        name = edit.text().strip() or f"Voice {n + 1}"
        if n < len(self.voices) and self.voices[n]["name"] != name:
            self.push_undo()
            self.voices[n]["name"] = name
            self.remember_voices()
            self.renderer = None
            self.after_words_edited()

    def pick_voice_color(self, n):
        if self.busy or n >= len(self.voices):
            return
        color = QColorDialog.getColor(QColor(*self.voices[n]["color"]), self, f"Colour for {self.voices[n]['name']}")
        if color.isValid():
            self.push_undo()
            self.voices[n]["color"] = list(color.getRgb()[:3])
            self.remember_voices()
            self.renderer = None
            self.rebuild_voice_panel()
            self.after_words_edited()

    def rebuild_voice_panel(self):
        while self.voices_box.count():
            widget = self.voices_box.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        counts = {}
        hidden_all = {}
        for w in self.words:
            sp = w.get("speaker")
            if isinstance(sp, int):
                counts[sp] = counts.get(sp, 0) + 1
                hidden_all[sp] = hidden_all.get(sp, True) and bool(w.get("hidden"))
        for n, v in enumerate(self.voices):
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            color_btn = QPushButton()
            color_btn.setFixedWidth(34)
            self.update_button_color(color_btn, v["color"])
            color_btn.setToolTip("Change this voice's colour")
            color_btn.clicked.connect(lambda _=False, n=n: self.pick_voice_color(n))
            name = QLineEdit(v["name"])
            name.setToolTip(f"Name for voice {n + 1} (press {n + 1} in the transcript to give lines this voice)")
            name.editingFinished.connect(lambda n=n, e=name: self.rename_voice(n, e))
            count = QLabel(str(counts.get(n, 0)))
            count.setObjectName("HintLabel")
            count.setToolTip("Words with this voice")
            is_hidden = hidden_all.get(n, False) and counts.get(n, 0) > 0
            eye = QPushButton("Show" if is_hidden else "Hide")
            eye.setToolTip("Hide or show every line from this voice (e.g. game characters)")
            eye.clicked.connect(lambda _=False, n=n, h=is_hidden: self.set_voice_hidden(n, not h))
            remove = QPushButton("✕")
            remove.setFixedWidth(30)
            remove.setToolTip("Remove this voice (its lines keep their text, just no voice)")
            remove.clicked.connect(lambda _=False, n=n: self.remove_voice(n))
            for wdg in (color_btn, name, count, eye, remove):
                lay.addWidget(wdg)
            lay.setStretch(1, 1)
            self.voices_box.addWidget(row)

    def toggle_voice_colors(self):
        order = ["off", "highlight", "line"]
        cur = self.style.get("voice_colors", "highlight")
        self.style["voice_colors"] = order[(order.index(cur) + 1) % 3] if cur in order else "highlight"
        self.sync_style_widgets()
        self.on_style_changed()

    def toggle_voice_names(self):
        self.style["voice_names"] = not self.style.get("voice_names", False)
        self.sync_style_widgets()
        self.on_style_changed()

    def detect_voices(self, ask=True):
        if self.busy or not self.words or not self.video_path:
            return
        if ask and any("speaker" in w for w in self.words) and QMessageBox.question(
                self, "Detect voices again?", "This replaces the voices given to every line. Continue?") != QMessageBox.Yes:
            return
        self.pause_preview()
        self.progress_bar.setRange(0, 0)
        self.set_busy("voices")
        self.voice_worker = VoiceDetectWorker(self.video_path, self.selected_track(), self.words,
                                              self.voice_count_combo.currentData())
        self.voice_worker.status.connect(self.label.setText)
        self.voice_worker.succeeded.connect(self.on_voices_detected)
        self.voice_worker.failed.connect(self.on_voice_detect_failed)
        self.voice_worker.start()

    def on_voices_detected(self, labels):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.set_busy(None)
        if len(labels) != len(self.words):
            self.label.setText("Voice detection result didn't match the transcript - try again")
            return
        self.push_undo()
        for w, sp in zip(self.words, labels):
            w["speaker"] = int(sp)
        count = (max(labels) + 1) if labels else 0
        self.ensure_voices(count)
        if self.style.get("voice_colors") == "off":
            self.style["voice_colors"] = "highlight"
            self.sync_style_widgets()
        self.renderer = None
        self.rebuild_voice_panel()
        self.after_words_edited()
        self.label.setText(f"Found {count} voice(s). Rename them in the Voices panel and fix any mistakes "
                           f"in the transcript (select lines, press 1-9).")

    def on_voice_detect_failed(self, message):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.set_busy(None)
        self.label.setText("Voice detection failed")
        QMessageBox.critical(self, "Voice detection failed", message)

    def after_words_edited(self, rebuild_list=True):
        self.dirty = True
        self.rebuild_track()
        if rebuild_list:
            self.rebuild_caption_list()
        self.rebuild_voice_counts()
        self.update_controls()
        if not self.preview_running:
            self.refresh_preview()

    def rebuild_voice_counts(self):
        # cheap refresh of the per-voice word counts / Hide-Show labels
        if self.voices_box.count() != len(self.voices):
            self.rebuild_voice_panel()
            return
        counts, hidden_all = {}, {}
        for w in self.words:
            sp = w.get("speaker")
            if isinstance(sp, int):
                counts[sp] = counts.get(sp, 0) + 1
                hidden_all[sp] = hidden_all.get(sp, True) and bool(w.get("hidden"))
        for n in range(len(self.voices)):
            row = self.voices_box.itemAt(n).widget()
            if row is None:
                continue
            lay = row.layout()
            lay.itemAt(2).widget().setText(str(counts.get(n, 0)))
            is_hidden = hidden_all.get(n, False) and counts.get(n, 0) > 0
            eye = lay.itemAt(3).widget()
            eye.setText("Show" if is_hidden else "Hide")
            try:
                eye.clicked.disconnect()
            except Exception:
                pass
            eye.clicked.connect(lambda _=False, n=n, h=is_hidden: self.set_voice_hidden(n, not h))

    # ------------------------------------------------------------------ preview
    def duration(self):
        if self.video_info and self.video_info["duration"] > 0:
            return self.video_info["duration"]
        return self.track.end_time() if self.track else 0.0

    def preview_size(self):
        if self.vertical_checkbox.isChecked() and self.export_mode == "merge":
            return 432, 768
        if self.video_info:
            sw, sh = self.video_info["width"], self.video_info["height"]
            scale = min(960 / sw, 540 / sh)
            return even(sw * scale), even(sh * scale)
        return 960, 540

    def update_slider_range(self):
        self._updating_slider = True
        self.seek_slider.setRange(0, int(self.duration() * 1000))
        self._updating_slider = False

    def on_slider_changed(self, value):
        if self._updating_slider:
            return
        self.preview_time = value / 1000.0
        if self.preview_running:
            self.sync_play_position()
        else:
            self.seek_timer.start(40)  # small delay so dragging doesn't spawn an ffmpeg per pixel

    def toggle_play(self):
        if self.preview_running:
            self.pause_preview()
        else:
            self.play_preview()

    def play_preview(self):
        if self.busy or not self.frame_reader:
            return
        if self.preview_time >= self.duration() - 0.05:
            self.preview_time = 0.0
        self.preview_running = True
        self.play_btn.setText("⏸ Pause")
        self.sync_play_position()
        if self.audio_active():
            self.audio_player.play()
        self.preview_timer.start(max(1, int(1000 / self.frame_reader.fps)))

    def pause_preview(self):
        self.preview_running = False
        self.preview_timer.stop()
        self.play_btn.setText("▶ Play")
        if self.audio_player is not None:
            self.audio_player.pause()

    def rewind_preview(self):
        self.preview_time = 0.0
        self.sync_play_position()
        if self.frame_reader:
            self.frame_reader.close_active_stream()
        self.refresh_preview()

    def on_preview_tick(self):
        self.preview_time = self.current_play_time()
        if self.preview_time >= self.duration():
            self.preview_time = self.duration()
            self.pause_preview()
        self.refresh_preview()

    # ------------------------------------------------------------------ preview audio
    def load_preview_audio(self, video_path, has_audio):
        self.audio_ok = False
        if self.audio_player is None:
            return
        self.audio_player.stop()
        if has_audio:
            self.audio_player.setSource(QUrl.fromLocalFile(os.path.abspath(video_path)))
            self.audio_ok = True
        else:
            self.audio_player.setSource(QUrl())

    def populate_tracks(self, tracks, select=0):
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for i, label in enumerate(tracks):
            self.track_combo.addItem(label, userData=i)
        if 0 <= select < len(tracks):
            self.track_combo.setCurrentIndex(select)
        self.track_combo.blockSignals(False)
        many = len(tracks) > 1
        self.track_combo.setVisible(many)
        self.track_label.setVisible(many)
        self.apply_preview_track()

    def selected_track(self):
        data = self.track_combo.currentData()
        return int(data) if data is not None else 0

    def on_track_changed(self, *_):
        self.apply_preview_track()
        if self.words:
            self.label.setText(f"Audio track {self.selected_track() + 1} selected - Generate Captions to re-caption it")

    def apply_preview_track(self):
        """Let the preview play the chosen track too, so you hear what will be captioned."""
        player = self.audio_player
        if player is None or not hasattr(player, "setActiveAudioTrack"):
            return
        try:
            if len(player.audioTracks()) > self.selected_track():
                player.setActiveAudioTrack(self.selected_track())
        except Exception as e:
            log.debug(f"Couldn't switch preview audio track: {e}")

    def audio_active(self):
        return self.audio_player is not None and self.audio_ok

    def on_audio_error(self, *_):
        log.warning(f"Preview audio error: {self.audio_player.errorString()}")
        self.audio_ok = False  # keep playing silently on the wall clock

    def is_muted(self):
        return self.audio_output.isMuted() if self.audio_output else True

    def set_muted(self, muted):
        if self.audio_output is not None:
            self.audio_output.setMuted(muted)
        self.mute_btn.setText("🔇" if muted else "🔊")
        self.save_ui_settings()

    def on_volume_changed(self, value):
        if self.audio_output is not None:
            self.audio_output.setVolume(value / 100.0)
        if value > 0 and self.is_muted():
            self.set_muted(False)

    def sync_play_position(self):
        """Re-anchor the playback clocks (and the audio) to self.preview_time."""
        self._play_base = self.preview_time
        self._play_clock.restart()
        if self.audio_active():
            self.audio_player.setPosition(int(self.preview_time * 1000))
            self._last_audio_pos = -1

    def current_play_time(self):
        if self.audio_active() and self.audio_player.playbackState() == QMediaPlayer.PlayingState:
            pos = self.audio_player.position()
            if pos != self._last_audio_pos:  # smooth between the player's position updates
                self._last_audio_pos = pos
                self._audio_clock.restart()
            t = pos / 1000.0 + min(self._audio_clock.elapsed(), 250) / 1000.0
            self._play_base = t  # if the audio ends early, the wall clock carries on from here
            self._play_clock.restart()
            return t
        return self._play_base + self._play_clock.elapsed() / 1000.0

    def crop_x(self):
        return self.crop_slider.value() / 100.0

    def on_crop_changed(self, value):
        self.crop_slider.setToolTip(f"Crop position: {value}% (50 = centre)")
        self.save_ui_settings()
        if self.video_path and not self.preview_running:
            self.seek_timer.start(60)

    def handle_checkbox_toggle(self, *_):
        self.save_ui_settings()
        if not self.preview_running:
            self.refresh_preview()

    def refresh_preview(self):
        w, h = self.preview_size()
        crop = self.crop_x() if (self.vertical_checkbox.isChecked() and self.export_mode == "merge") else 0.5
        frame = self.frame_reader.frame_at(self.preview_time, w, h, crop) if self.frame_reader else None
        base = frame.convert("RGBA") if frame is not None else Image.new("RGBA", (w, h), (10, 10, 10, 255))
        layer = self.get_renderer().overlay(self.preview_time, w, h, self.track)
        if layer is not None:
            base = Image.alpha_composite(base, layer)
        pix = self.pil_to_qpixmap(base)
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(self.preview.size() - QSize(8, 8), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        total = self.duration()
        self.time_label.setText(f"{fmt_clock(self.preview_time)} / {fmt_clock(total)}")
        self._updating_slider = True
        self.seek_slider.setValue(int(self.preview_time * 1000))
        self._updating_slider = False

        if self.preview_running and self.track:  # follow along in the transcript
            gi = self.track.group_index_at(self.preview_time)
            if gi >= 0:
                first = self.track.words[self.track.groups[gi]["idx"][0]]
                wi = self._word_index.get(id(first))
                if wi is not None and wi < len(self._line_of_word):
                    line = self._line_of_word[wi]
                    if line != self._last_list_row and line < self.caption_list.topLevelItemCount():
                        self._last_list_row = line
                        item = self.caption_list.topLevelItem(line)
                        self.caption_list.blockSignals(True)
                        self.caption_list.setCurrentItem(item)
                        self.caption_list.scrollToItem(item)
                        self.caption_list.blockSignals(False)

    @staticmethod
    def pil_to_qpixmap(img):
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.size[0], img.size[1], img.size[0] * 4, QImage.Format_RGBA8888).copy()
        return QPixmap.fromImage(qimg)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.preview_running and hasattr(self, "preview"):
            self.seek_timer.start(60)

    # ------------------------------------------------------------------ export
    def apply_export_mode_labels(self):
        if self.export_mode == "merge":
            self.export_mode_btn.setText("Target: Complete Video + Audio (.mp4)")
            self.export_btn.setText("Render Full Video")
            self.preview_hint.setText("")
        else:
            self.export_mode_btn.setText("Target: Caption Overlay Only (.mov)")
            self.export_btn.setText("Export Overlay")
            self.preview_hint.setText("Overlay mode: the video is shown only to help you line things up. "
                                      "The exported .mov is transparent captions only.")

    def toggle_export_mode(self):
        self.export_mode = "merge" if self.export_mode == "overlay" else "overlay"
        if self.export_mode == "overlay":
            self.vertical_checkbox.blockSignals(True)
            self.vertical_checkbox.setChecked(False)
            self.vertical_checkbox.blockSignals(False)
        self.apply_export_mode_labels()
        self.update_controls()
        self.save_ui_settings()
        if not self.preview_running:
            self.refresh_preview()

    def export(self):
        if not self.video_path or not self.words or self.busy:
            return
        self.pause_preview()
        vertical = self.vertical_checkbox.isChecked() and self.export_mode == "merge"
        base = os.path.splitext(self.video_path)[0]
        if self.export_mode == "overlay":
            default, file_filter = base + "_CAPTIONS.mov", "ProRes 4444 with transparency (*.mov)"
        else:
            default, file_filter = base + ("_VERTICAL.mp4" if vertical else "_FULL.mp4"), "MP4 video (*.mp4)"
        out_file, _ = QFileDialog.getSaveFileName(self, "Export To", default, file_filter)
        if not out_file:
            return
        if os.path.abspath(out_file) == os.path.abspath(self.video_path):
            QMessageBox.warning(self, "Pick another name", "You can't export over the original video.")
            return
        if not self.check_export_space(out_file, vertical):
            return

        log.debug(f"Export starting: mode={self.export_mode} vertical={vertical} -> {out_file}")
        self.progress_bar.setValue(0)
        self.label.setText("Starting export...")
        self.set_busy("export")
        self.export_worker = ExportWorker(
            self.video_path, self.video_info, out_file, self.export_mode, vertical,
            self.words, self.style, self.font_map.get(self.style.get("font")), self.voices, self.crop_x())
        self.export_worker.progress.connect(self.on_export_progress)
        self.export_worker.succeeded.connect(self.on_export_success)
        self.export_worker.failed.connect(self.on_export_failure)
        self.export_worker.cancelled.connect(self.on_export_cancelled)
        self.export_worker.start()

    def estimate_export_size(self, vertical):
        info = self.video_info or {}
        duration, fps = info.get("duration", 0) or 0, info.get("fps", 30) or 30
        if self.export_mode == "overlay":
            w, h = even(info.get("width", 1920)), even(info.get("height", 1080))
            return int(OVERLAY_BYTES_PER_PIXEL * w * h * fps * duration)
        try:
            source = os.path.getsize(self.video_path)
        except OSError:
            source = 0
        return int(max(source * 1.5, duration * 2.5e6))  # re-encode at high quality ~ up to 20 Mbps

    def check_export_space(self, out_file, vertical):
        estimate = self.estimate_export_size(vertical)
        try:
            free = shutil.disk_usage(os.path.dirname(os.path.abspath(out_file))).free
        except OSError:
            free = None
        gb = lambda n: f"{n / 1e9:.1f} GB"
        if free is not None and estimate > free * 0.95:
            return QMessageBox.warning(
                self, "Not enough disk space",
                f"This export needs about {gb(estimate)}, but that drive only has {gb(free)} free.\n\n"
                "Free up space or pick another drive. Export anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
        if self.export_mode == "overlay" and estimate > 5e9:
            return QMessageBox.question(
                self, "Large overlay file",
                f"A transparent caption overlay for this video will be about {gb(estimate)}.\n\n"
                "For long videos, Export Subtitles (.srt) or Complete Video (.mp4) make far smaller files. "
                "Continue with the overlay?") == QMessageBox.Yes
        return True

    def cancel_current(self):
        if self.busy == "export":
            self.cancel_export()
        elif self.busy == "transcribe" and self.transcription_worker and self.transcription_worker.isRunning():
            self.label.setText("Cancelling... (stops after the current few seconds of audio)")
            self.cancel_btn.setEnabled(False)
            self.transcription_worker.cancel()

    def on_transcription_progress(self, pct):
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(pct)

    def on_transcription_cancelled(self):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.set_busy(None)
        self.label.setText("Transcription cancelled")

    def cancel_export(self):
        if self.export_worker and self.export_worker.isRunning():
            self.label.setText("Cancelling...")
            self.cancel_btn.setEnabled(False)
            self.export_worker.cancel()

    def on_export_progress(self, pct, message):
        self.progress_bar.setValue(pct)
        self.label.setText(message)

    def on_export_success(self, out_file):
        log.debug(f"Export finished: {out_file}")
        self.set_busy(None)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.label.setText("Export finished!")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Export finished")
        box.setText(f"Saved:\n{out_file}")
        open_btn = box.addButton("Open Folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() == open_btn:
            self.open_folder(out_file)

    def on_export_failure(self, message):
        self.set_busy(None)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.label.setText("Export failed")
        QMessageBox.critical(self, "Export failed", message)

    def on_export_cancelled(self):
        self.set_busy(None)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.label.setText("Export cancelled")

    def refresh_model_labels(self):
        for i, (key, text) in enumerate(WHISPER_MODELS):
            self.model_combo.setItemText(i, text + ("   ✓ ready" if model_downloaded(key) else "   (downloads on first use)"))

    @staticmethod
    def open_folder(path, is_dir=False):
        folder = os.path.abspath(path) if is_dir else os.path.dirname(os.path.abspath(path))
        try:
            if sys.platform == "win32" and is_dir:
                os.startfile(folder)
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            log.warning(f"Could not open folder: {e}")

    def export_subtitles(self):
        if not self.track:
            return
        base = os.path.splitext(self.video_path)[0] if self.video_path else "captions"
        out_file, chosen = QFileDialog.getSaveFileName(
            self, "Export Subtitles", base + ".srt", "SubRip (*.srt);;WebVTT (*.vtt)")
        if not out_file:
            return
        vtt = out_file.lower().endswith(".vtt") or ("vtt" in chosen.lower() and not out_file.lower().endswith(".srt"))
        if vtt and not out_file.lower().endswith(".vtt"):
            out_file += ".vtt"
        elif not vtt and not out_file.lower().endswith(".srt"):
            out_file += ".srt"
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(build_subtitles(self.track, vtt=vtt, voices=self.voices,
                                        offset=self.style.get("timing_offset", 0.0)))
            self.label.setText(f"Subtitles saved: {os.path.basename(out_file)}")
        except Exception as e:
            QMessageBox.critical(self, "Couldn't save subtitles", str(e))

    # ------------------------------------------------------------------ projects
    def project_data(self):
        return {
            "app": APP_NAME, "version": APP_VERSION,
            "video_path": self.video_path, "words": self.words, "style": self.style, "voices": self.voices,
            "export_mode": self.export_mode, "vertical": self.vertical_checkbox.isChecked(),
            "audio_track": self.selected_track(), "crop": self.crop_slider.value(),
        }

    @staticmethod
    def write_json_atomic(path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)

    def save_project(self, save_as=False):
        if self.busy or (not self.video_path and not self.words):
            return False
        path = None if save_as else self.project_path
        if not path:
            base = os.path.splitext(self.project_path or self.video_path or "captions")[0]
            if base.lower().endswith(".bcs"):
                base = base[:-4]
            path, _ = QFileDialog.getSaveFileName(self, "Save Caption Project", base + PROJECT_EXT, PROJECT_FILTER)
            if not path:
                return False
            if not path.lower().endswith(PROJECT_EXTS):
                path += PROJECT_EXT
        try:
            self.write_json_atomic(path, self.project_data())
        except Exception as e:
            QMessageBox.critical(self, "Couldn't save project", str(e))
            return False
        self.project_path = path
        self.dirty = False
        self.add_recent(path)
        self.clear_autosave()
        self.label.setText(f"Project saved: {os.path.basename(path)}")
        return True

    def save_project_as(self):
        return self.save_project(save_as=True)

    def open_project(self):
        if self.busy or not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Caption Project", "", PROJECT_FILTER)
        if path:
            self.open_project_path(path, confirmed=True)

    def open_project_path(self, path, confirmed=False, from_autosave=False):
        if self.busy:
            return False
        if not confirmed and not self.confirm_discard():
            return False
        if not os.path.exists(path):
            QMessageBox.warning(self, "Project not found", f"This project file no longer exists:\n{path}")
            self.remove_recent(path)
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            words = []
            for w in data.get("words", []):
                text = str(w.get("word", "")).strip()
                if not text:
                    continue
                item = {"word": text, "start": float(w["start"]), "end": float(w["end"])}
                if w.get("hidden"):
                    item["hidden"] = True
                if isinstance(w.get("speaker"), int):
                    item["speaker"] = w["speaker"]
                words.append(item)
            voices = [{"name": str(v.get("name") or f"Voice {n + 1}"),
                       "color": [int(c) for c in v.get("color", VOICE_PALETTE[n % 8])][:3]}
                      for n, v in enumerate(data.get("voices", []) or [])]
        except Exception as e:
            QMessageBox.critical(self, "Couldn't open project", f"That file isn't a valid caption project.\n\n{e}")
            return False

        video = data.get("video_path")
        if not video or not os.path.exists(video):
            QMessageBox.information(self, "Find the video",
                                    f"The project's video wasn't found:\n{video}\n\nPlease locate it.")
            video, _ = QFileDialog.getOpenFileName(self, "Locate Video", "", "Videos (*.mp4 *.mov *.avi *.mkv *.webm *.m4v)")
            if not video:
                return False
        if not self.open_video(video):
            return False

        self.style.update({k: v for k, v in data.get("style", {}).items() if k in DEFAULT_STYLE})
        self.export_mode = data.get("export_mode", self.export_mode)
        self.populate_tracks(self.video_info.get("audio_tracks", []), int(data.get("audio_track", 0) or 0))
        self.vertical_checkbox.blockSignals(True)
        self.vertical_checkbox.setChecked(bool(data.get("vertical", False)) and self.export_mode == "merge")
        self.vertical_checkbox.blockSignals(False)
        self.apply_export_mode_labels()
        self.words = words
        self.voices = voices
        self.ensure_voices(max((w["speaker"] for w in words if "speaker" in w), default=-1) + 1)
        self.reset_history()
        self.renderer = None
        self.rebuild_voice_panel()
        self.rebuild_track()
        self.rebuild_caption_list()
        self.refresh_fonts(keep_style_font=True)
        self.sync_style_widgets()
        if from_autosave:
            self.project_path = data.get("autosave_of") or None
        else:
            self.project_path = path
            self.add_recent(path)
        if "crop" in data:
            self.crop_slider.setValue(int(data.get("crop", 50)))
        self.dirty = from_autosave
        self.update_title()
        self.update_slider_range()
        self.update_controls()
        self.on_style_changed()
        self.label.setText("Restored your unsaved work" if from_autosave else f"Opened project: {os.path.basename(path)}")
        return True


    def open_any_file(self, path):
        """Videos start a new project; .bcsproj files open the project."""
        if path.lower().endswith(PROJECT_EXTS):
            self.open_project_path(path)
        elif path.lower().endswith(VIDEO_EXTS):
            self.process_dropped_video(path)

    def new_project(self):
        if self.busy or not self.confirm_discard():
            return
        self.pause_preview()
        if self.frame_reader:
            self.frame_reader.close_active_stream()
        if self.audio_player is not None:
            self.audio_player.stop()
            self.audio_player.setSource(QUrl())
        self.frame_reader = None
        self.video_path = None
        self.video_info = None
        self.words, self.voices = [], []
        self.reset_history()
        self.project_path = None
        self.populate_tracks([])
        self.rebuild_voice_panel()
        self.rebuild_track()
        self.rebuild_caption_list()
        self.preview_time = 0.0
        self.update_slider_range()
        self.progress_bar.setValue(0)
        self.clear_autosave()
        self.dirty = False
        self.update_controls()
        self.refresh_preview()
        self.label.setText("Ready")

    # ------------------------------------------------------------------ recent projects
    def add_recent(self, path):
        path = os.path.abspath(path)
        recent = [p for p in self.settings.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
        self.settings["recent"] = [path] + recent[:9]
        save_settings(self.settings)

    def remove_recent(self, path):
        self.settings["recent"] = [p for p in self.settings.get("recent", [])
                                   if os.path.normcase(p) != os.path.normcase(os.path.abspath(path))]
        save_settings(self.settings)

    def fill_recent_menu(self):
        menu = self.recent_menu
        menu.clear()
        recent = self.settings.get("recent", [])
        if not recent:
            menu.addAction("(No recent projects)").setEnabled(False)
            return
        for n, path in enumerate(recent, 1):
            exists = os.path.exists(path)
            act = menu.addAction(f"&{n % 10}  {os.path.basename(path)}" + ("" if exists else "  (missing)"))
            act.setToolTip(path)
            act.setStatusTip(path)
            act.setEnabled(exists and not self.busy)
            act.triggered.connect(lambda _=False, p=path: self.open_project_path(p))
        menu.addSeparator()
        menu.addAction("Clear Recent Projects").triggered.connect(self.clear_recent)

    def clear_recent(self):
        self.settings["recent"] = []
        save_settings(self.settings)

    # ------------------------------------------------------------------ autosave / recovery
    def autosave(self):
        if self.busy or not self.dirty or not (self.words or self.video_path):
            return
        try:
            data = self.project_data()
            data["autosave_of"] = self.project_path
            data["autosaved_at"] = time.strftime("%Y-%m-%d %H:%M")
            self.write_json_atomic(AUTOSAVE_FILE, data)
            log.debug("Autosaved")
        except Exception as e:
            log.warning(f"Autosave failed: {e}")

    def clear_autosave(self):
        try:
            if os.path.exists(AUTOSAVE_FILE):
                os.remove(AUTOSAVE_FILE)
        except OSError as e:
            log.warning(f"Couldn't remove autosave: {e}")

    def offer_recovery(self):
        if not os.path.exists(AUTOSAVE_FILE):
            return
        try:
            with open(AUTOSAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.clear_autosave()
            return
        name = os.path.basename(data.get("autosave_of") or data.get("video_path") or "your project")
        answer = QMessageBox.question(
            self, "Restore unsaved work?",
            f"Bones Caption Studio didn't close normally last time.\n\n"
            f"Restore your unsaved work on \"{name}\" (autosaved {data.get('autosaved_at', 'recently')})?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes and self.open_project_path(AUTOSAVE_FILE, confirmed=True, from_autosave=True):
            return
        self.clear_autosave()

    # ------------------------------------------------------------------ startup
    def startup_checks(self, args):
        self.check_ffmpeg()
        self.offer_recovery()
        for arg in args:
            if os.path.isfile(arg):
                self.open_any_file(os.path.abspath(arg))
                break

    def check_ffmpeg(self):
        missing = []
        for name, path in (("ffmpeg", FFMPEG_BIN), ("ffprobe", FFPROBE_BIN)):
            try:
                if run_cmd([path, "-version"]).returncode != 0:
                    missing.append(name)
            except Exception:
                missing.append(name)
        if missing:
            log.error(f"Missing: {missing}")
            QMessageBox.warning(
                self, "FFmpeg not found",
                f"Bones Caption Studio needs {' and '.join(m + '.exe' for m in missing)} to read and export videos, "
                f"but couldn't find {'it' if len(missing) == 1 else 'them'}.\n\n"
                f"Put ffmpeg.exe and ffprobe.exe in:\n{app_dir()}\n\nthen restart the app.")

    # ------------------------------------------------------------------ menu bar
    def build_menus(self):
        bar = self.menuBar()
        acts = {}

        def add(menu, key, text, slot, shortcut=None, tip=None):
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            if tip:
                act.setStatusTip(tip)
                act.setToolTip(tip)
            act.triggered.connect(lambda _=False: slot())
            menu.addAction(act)
            acts[key] = act
            return act

        m = bar.addMenu("&File")
        add(m, "new", "&New Project", self.new_project, "Ctrl+N")
        add(m, "open", "&Open Project...", self.open_project, "Ctrl+O")
        self.recent_menu = m.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self.fill_recent_menu)
        m.addSeparator()
        add(m, "save", "&Save Project", self.save_project, "Ctrl+S")
        add(m, "save_as", "Save Project &As...", self.save_project_as, "Ctrl+Shift+S")
        m.addSeparator()
        add(m, "import", "&Import Video...", self.load_video, "Ctrl+I")
        ex = m.addMenu("&Export")
        add(ex, "exp_overlay", "Caption &Overlay (.mov, transparent)...", lambda: self.export_as("overlay", False))
        add(ex, "exp_full", "Complete &Video (.mp4)...", lambda: self.export_as("merge", False), "Ctrl+E")
        add(ex, "exp_vertical", "&Vertical Video 9:16 (.mp4)...", lambda: self.export_as("merge", True))
        ex.addSeparator()
        add(ex, "exp_subs", "&Subtitles (.srt / .vtt)...", self.export_subtitles)
        m.addSeparator()
        add(m, "exit", "E&xit", self.close, "Ctrl+Q")

        m = bar.addMenu("&Edit")
        add(m, "undo", "&Undo", self.undo, "Ctrl+Z")
        add(m, "redo", "&Redo", self.redo, "Ctrl+Y")
        m.addSeparator()
        add(m, "find", "&Find in Transcript", lambda: self.search_box.setFocus(), "Ctrl+F")
        add(m, "hide", "&Hide / Show Selected\tDel", self.toggle_hidden_selected)
        add(m, "delete", "&Delete Selected Permanently\tShift+Del", self.delete_selected_words)
        self.voice_submenu = m.addMenu("Set &Voice")
        self.voice_submenu.aboutToShow.connect(self.fill_voice_submenu)
        m.addSeparator()
        add(m, "transcribe", "&Generate Captions", self.generate, "F5")
        add(m, "detect", "Detect &Voices", lambda: self.detect_voices(), "F6")

        m = bar.addMenu("&Help")
        add(m, "guide", "User &Guide", self.show_guide, "F1")
        add(m, "shortcuts", "&Keyboard Shortcuts", self.show_shortcuts, "Ctrl+F1")
        add(m, "logs", "Open &Logs && Settings Folder", lambda: self.open_folder(DATA_DIR, is_dir=True))
        m.addSeparator()
        assoc = add(m, "assoc", "Open .bcsproj Files with Bones Caption Studio", self.toggle_file_association,
                    tip="Double-clicking a caption project in File Explorer opens it here")
        assoc.setCheckable(True)
        m.aboutToShow.connect(lambda: acts["assoc"].setChecked(self.file_association_registered()))
        m.addSeparator()
        add(m, "updates", "Check for &Updates...", self.check_for_updates)
        add(m, "reset", "&Reset Settings...", self.reset_settings)
        m.addSeparator()
        add(m, "about", f"&About {APP_NAME}", self.show_about)
        self.menu_actions = acts
        self.update_menu_state()

    def fill_voice_submenu(self):
        self.voice_submenu.clear()
        for act in self.voice_menu().actions():
            self.voice_submenu.addAction(act)

    def update_menu_state(self):
        a = self.menu_actions
        idle = self.busy is None
        has_video, has_words = self.video_path is not None, bool(self.words)
        for key in ("new", "open", "import", "hide", "delete", "assoc", "reset"):
            a[key].setEnabled(idle)
        a["save"].setEnabled(idle and (has_video or has_words))
        a["save_as"].setEnabled(idle and (has_video or has_words))
        for key in ("exp_overlay", "exp_full", "exp_vertical"):
            a[key].setEnabled(idle and has_video and has_words)
        a["exp_subs"].setEnabled(idle and has_words)
        a["undo"].setEnabled(idle and bool(self._undo))
        a["redo"].setEnabled(idle and bool(self._redo))
        a["transcribe"].setEnabled(idle and has_video)
        a["detect"].setEnabled(idle and has_video and has_words)
        self.voice_submenu.setEnabled(idle and has_words)

    def export_as(self, mode, vertical):
        if self.busy:
            return
        if self.export_mode != mode:
            self.toggle_export_mode()
        if mode == "merge":
            self.vertical_checkbox.setChecked(vertical)
        self.export()

    # ------------------------------------------------------------------ help menu
    def show_shortcuts(self):
        rows = [("Ctrl+N / Ctrl+O / Ctrl+S", "New / Open / Save project"), ("Ctrl+Shift+S", "Save project as"),
                ("Ctrl+I", "Import video"), ("Ctrl+E", "Export complete video"), ("F5", "Generate captions"),
                ("F6", "Detect voices"), ("Space", "Play / pause the preview"), ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
                ("Ctrl+F", "Search the transcript"), ("Delete", "Hide / show selected lines or words"),
                ("Shift+Delete", "Delete selected words permanently"), ("1 - 9", "Give selected lines that voice"),
                ("0", "Remove the voice from selected lines"), ("Double-click", "Edit a line or word"),
                ("Right-click", "More transcript options"), ("F1", "User guide"), ("Ctrl+F1", "This list")]
        html = "<table cellspacing='6'>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard Shortcuts")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.exec()

    def show_guide(self, topic=None):
        import user_guide as guide
        dialog = guide.make_dialog(self, resource_path("guide"), APP_VERSION_FULL, start_topic=topic,
                                   export_dir=os.path.join(DATA_DIR, "guide"))
        dialog.exec()

    def show_about(self):
        edition = "GPU (NVIDIA)" if "GPU" in APP_VERSION_FULL else ("CPU" if "CPU" in APP_VERSION_FULL else "from source")
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setIconPixmap(self.windowIcon().pixmap(64, 64))
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version <b>{APP_VERSION_FULL}</b><br>Edition: {edition}{' · Portable' if PORTABLE else ''}</p>"
            f"<p>Made by Bones_84.</p>"
            f"<p><a href='https://github.com/{GITHUB_REPO}'>github.com/{GITHUB_REPO}</a></p>"
            "<p style='color:#9A9A9A'>Built with OpenAI Whisper, PyTorch, Qt for Python, FFmpeg and the "
            "Resemblyzer voice model. See THIRD_PARTY_NOTICES.txt for their licences.</p>")
        notices = os.path.join(app_dir(), "THIRD_PARTY_NOTICES.txt")
        licences = box.addButton("Third-Party Licences", QMessageBox.ActionRole) if os.path.exists(notices) else None
        box.addButton(QMessageBox.Ok)
        box.exec()
        if licences is not None and box.clickedButton() == licences:
            QDesktopServices.openUrl(QUrl.fromLocalFile(notices))

    def check_for_updates(self):
        if getattr(self, "update_worker", None) and self.update_worker.isRunning():
            return
        self.label.setText("Checking for updates...")
        self.update_worker = UpdateCheckWorker()
        self.update_worker.done.connect(self.on_update_result)
        self.update_worker.start()

    def on_update_result(self, result):
        self.label.setText("Ready" if self.busy is None else self.label.text())
        if not result.get("ok"):
            QMessageBox.warning(self, "Couldn't check for updates",
                                f"Couldn't reach GitHub. Check your internet connection.\n\n{result.get('error', '')}")
            return
        current = version_key(APP_VERSION_FULL)
        on_beta = "beta" in APP_VERSION_FULL.lower()
        candidates = [r for r in result.get("releases", []) if not r.get("draft") and (on_beta or not r.get("prerelease"))]
        newest = max(candidates, key=lambda r: version_key(r.get("tag_name", "")), default=None)
        if newest is None or version_key(newest.get("tag_name", "")) <= current:
            QMessageBox.information(self, "No updates", f"You have the latest version (v{APP_VERSION_FULL}).")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"A newer version is available: <b>{newest.get('name') or newest.get('tag_name')}</b><br>"
                    f"You have v{APP_VERSION_FULL}.")
        box.setTextFormat(Qt.RichText)
        get = box.addButton("Open Download Page", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == get:
            QDesktopServices.openUrl(QUrl(newest.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases"))

    def reset_settings(self):
        if self.busy:
            return
        if QMessageBox.question(
                self, "Reset settings?",
                "Reset the caption style and app settings back to their defaults?\n\n"
                "Your projects, style presets, favourite fonts, voice names and recent projects are kept.") != QMessageBox.Yes:
            return
        font = self.style.get("font")
        self.style = dict(DEFAULT_STYLE)
        self.style["font"] = font
        keep = {k: v for k, v in self.settings.get("ui", {}).items() if k in ("geometry", "window")}
        self.settings["ui"] = keep
        self._loading = True
        self.restore_combo(self.accel_combo, "auto")
        self.restore_combo(self.model_combo, "base")
        self.restore_combo(self.lang_combo, "")
        if self.export_mode != "overlay":
            self.toggle_export_mode()
        self.vertical_checkbox.setChecked(False)
        self.crop_slider.setValue(50)
        self.volume_slider.setValue(80)
        self.set_muted(False)
        self.cb_toggle.setChecked(False)
        self._loading = False
        self.sync_style_widgets()
        self.rebuild_track()
        self.rebuild_caption_list()
        self.on_style_changed(rebuild_track=True)
        self.save_ui_settings()
        self.label.setText("Settings reset to defaults")

    # ------------------------------------------------------------------ Windows file association (.bcsproj)
    ASSOC_PROGID = "BonesCaptionStudio.Project"

    @staticmethod
    def _assoc_command():
        return f'"{sys.executable}" "%1"'

    def file_association_registered(self):
        if sys.platform != "win32":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                rf"Software\Classes\{self.ASSOC_PROGID}\shell\open\command") as k:
                return winreg.QueryValue(k, None) == self._assoc_command()
        except OSError:
            return False

    def toggle_file_association(self):
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            QMessageBox.information(self, "File association",
                                    "This works in the built app (BonesCaptionStudio.exe) on Windows.")
            return
        import winreg
        import ctypes
        classes = r"Software\Classes"
        try:
            if self.file_association_registered():
                for key in (rf"{self.ASSOC_PROGID}\shell\open\command", rf"{self.ASSOC_PROGID}\shell\open",
                            rf"{self.ASSOC_PROGID}\shell", rf"{self.ASSOC_PROGID}\DefaultIcon", self.ASSOC_PROGID,
                            PROJECT_EXT):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{key}")
                    except OSError:
                        pass
                message = "Caption projects will no longer open with Bones Caption Studio by double-clicking."
            else:
                def setv(path, value):
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{path}") as k:
                        winreg.SetValue(k, None, winreg.REG_SZ, value)
                setv(PROJECT_EXT, self.ASSOC_PROGID)
                setv(self.ASSOC_PROGID, "Bones Caption Studio Project")
                setv(rf"{self.ASSOC_PROGID}\DefaultIcon", f'"{sys.executable}",0')
                setv(rf"{self.ASSOC_PROGID}\shell\open\command", self._assoc_command())
                message = ("Done! Double-clicking a .bcsproj caption project in File Explorer now opens it here.\n\n"
                           "If you move this app's folder, turn this on again.")
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # tell Explorer
            QMessageBox.information(self, "File association", message)
        except Exception as e:
            QMessageBox.warning(self, "File association", f"Couldn't change the file association:\n{e}")

    # ------------------------------------------------------------------ shutdown
    def closeEvent(self, event):
        if self.busy == "export":
            if QMessageBox.question(self, "Export running", "An export is still running. Cancel it and quit?") != QMessageBox.Yes:
                event.ignore()
                return
            self.export_worker.cancel()
            self.export_worker.wait(10000)
        elif self.busy in ("transcribe", "voices"):
            if QMessageBox.question(self, "Still working", "Captions are still being generated. Quit anyway?") != QMessageBox.Yes:
                event.ignore()
                return
            if self.busy == "transcribe" and self.transcription_worker:
                self.transcription_worker.cancel()
                self.transcription_worker.wait(8000)
            self.shutdown_cleanup()
            if (self.transcription_worker and self.transcription_worker.isRunning()) or \
                    (self.voice_worker and self.voice_worker.isRunning()):
                os._exit(0)  # still busy (e.g. loading a model) - exit hard
        elif not self.confirm_discard():
            event.ignore()
            return
        self.clear_autosave()  # the user chose to save or discard
        self.shutdown_cleanup()
        event.accept()

    def save_window_geometry(self):
        """Remember the window's normal (un-maximised) size and position."""
        try:
            g = self.normalGeometry() if self.isMaximized() else self.geometry()
            if g.width() > 100 and g.height() > 100:
                self.settings["ui"]["window"] = {
                    "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(),
                    "maximized": bool(self.isMaximized()),
                }
        except Exception:
            pass

    def restore_window_geometry(self):
        """Put the window back where it was, but never off-screen (e.g. a monitor was unplugged)."""
        info = self.settings["ui"].get("window")
        if not isinstance(info, dict):
            return
        try:
            x, y, w, h = (int(info[k]) for k in ("x", "y", "w", "h"))
        except Exception:
            return
        screen = QApplication.screenAt(QPoint(x + w // 2, y + h // 2)) or QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        w = max(self.minimumSizeHint().width(), min(w, avail.width()))
        h = max(self.minimumSizeHint().height(), min(h, avail.height()))
        x = max(avail.left(), min(x, avail.right() - w + 1))
        y = max(avail.top(), min(y, avail.bottom() - h + 1))
        self.setGeometry(x, y, w, h)
        if info.get("maximized"):
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def shutdown_cleanup(self):
        self.pause_preview()
        self.autosave_timer.stop()
        self.save_window_geometry()
        self.settings["style"] = dict(self.style)
        self.save_ui_settings()
        if self.frame_reader:
            self.frame_reader.close_active_stream()
        if self.audio_player is not None:
            self.audio_player.stop()
        if self.font_worker.isRunning():
            self.font_worker.wait(3000)
        if self.hw_probe.isRunning():
            self.hw_probe.wait(5000)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Bones.CaptionStudio")
        except Exception:
            pass
    if "--export-guide" in sys.argv:
        # build_guide.bat: save the guide as a web page, no window
        import user_guide as guide
        i = sys.argv.index("--export-guide")
        out = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(app_dir(), "docs")
        try:
            print(guide.export_html(resource_path("guide"), out, APP_VERSION_FULL))
            sys.exit(0)
        except Exception:
            log.error("Couldn't export the guide", exc_info=True)
            sys.exit(1)
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        QTimer.singleShot(300, lambda: window.startup_checks(sys.argv[1:]))
        sys.exit(app.exec())
    except Exception:
        log.critical("Fatal startup error", exc_info=True)
        raise
