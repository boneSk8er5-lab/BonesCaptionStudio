"""Takes the pictures for the guide (guide/images/*.png) from Bones Caption Studio's real window.

It runs the app hidden, with a made-up demo video, a made-up transcript and its own temporary settings,
so the pictures never show your videos, words, voices, fonts favourites or recent projects.
Run it with make_guide_pictures.bat after changing how the window looks.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "guide", "images")
TEMP = tempfile.mkdtemp(prefix="bcs_guide_pictures_")

# Own settings folder + demo Whisper, before the app is imported
os.environ["APPDATA"] = TEMP
os.environ["XDG_CONFIG_HOME"] = TEMP
sys.path.insert(0, os.path.join(HERE, "demo_whisper"))
sys.path.insert(1, ROOT)

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel  # noqa: E402

import bones_caption_studio as bcs  # noqa: E402


def say(*parts):
    print(*parts, flush=True)


def make_demo_video(path):
    """A 20-second 1920x1080 'gameplay-looking' clip: painted sky, hills and a facecam box, plus quiet audio."""
    w, h = 1920, 1080
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):                                     # dusk sky
        t = y / h
        draw.line([(0, y), (w, y)], fill=(int(40 + 140 * t), int(30 + 60 * t), int(90 + 40 * (1 - t))))
    draw.ellipse([1300, 180, 1520, 400], fill=(255, 196, 120))
    for i, (base, colour) in enumerate(((760, (52, 70, 60)), (840, (36, 52, 44)), (930, (24, 34, 30)))):
        pts = [(0, h)] + [(x, base - 90 * ((x * (i + 2)) % 700) / 700) for x in range(0, w + 1, 120)] + [(w, h)]
        draw.polygon(pts, fill=colour)
    img = img.filter(ImageFilter.GaussianBlur(2))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([60, 60, 480, 300], radius=18, fill=(34, 40, 49), outline=(0, 173, 181), width=6)
    draw.ellipse([210, 110, 330, 230], fill=(90, 98, 110))      # 'facecam' silhouette
    draw.rectangle([180, 230, 360, 300], fill=(90, 98, 110))
    still = os.path.join(TEMP, "demo.png")
    img.save(still)
    cmd = [bcs.FFMPEG_BIN, "-y", "-loglevel", "error", "-loop", "1", "-i", still,
           "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=16000:duration=20",
           "-t", "20", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    subprocess.run(cmd, check=True, **({"creationflags": 0x08000000} if sys.platform == "win32" else {}))


def pump(app, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def panel(window, title):
    for frame in window.findChildren(QFrame, "ControlPanel"):
        label = frame.findChild(QLabel, "PanelTitle")
        if label and label.text() == title:
            return frame
    raise LookupError(f"No '{title}' panel")


def save(widget, name):
    path = os.path.join(OUT, name)
    if not widget.grab().save(path):
        raise RuntimeError(f"Couldn't save {path}")
    say("  saved", name)


def save_menu(app, window, menu, name):
    menu.popup(window.mapToGlobal(QPoint(0, 0)))
    pump(app, 0.3)
    save(menu, name)
    menu.hide()


def main():
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)
    say("Making the demo video...")
    video = os.path.join(TEMP, "Demo Stream Highlights.mp4")
    make_demo_video(video)

    window = bcs.MainWindow()
    window.setAttribute(Qt.WA_DontShowOnScreen)   # drawn off-screen: nothing pops up on your desktop
    window.resize(1500, 940)
    window.show()
    pump(app, 1.0)

    say("Making the demo captions...")
    window.accel_combo.setCurrentIndex(window.accel_combo.findData("cpu"))
    window.process_dropped_video(video)
    pump(app, 0.5)
    window.generate()
    deadline = time.time() + 120
    while window.busy and time.time() < deadline:
        pump(app, 0.1)
    if not window.words:
        raise RuntimeError("The demo captions weren't made - see the log in " + TEMP)

    # Voices: two players and the game's announcer (hidden, like you would in a real video)
    import whisper  # the demo one
    speakers = [w["demo_speaker"] for w in whisper.demo_words()]
    window.voices = [{"name": "Bones", "color": [0, 173, 181]}, {"name": "Vyper", "color": [255, 170, 40]},
                     {"name": "Game", "color": [170, 120, 255]}]
    for word, sp in zip(window.words, speakers):
        word["speaker"] = sp
        if sp == 2:
            word["hidden"] = True
    window.style["mode"] = "auto"
    window.style["voice_colors"] = "highlight"
    window.sync_style_widgets()
    window.rebuild_voice_panel()
    window.after_words_edited()
    window.dirty = False
    window.caption_list.collapseAll()
    window.caption_list.setCurrentItem(window.caption_list.topLevelItem(1))
    window.caption_list.scrollToTop()
    window.preview_time = 3.0
    window.refresh_preview()
    pump(app, 1.0)

    say("Taking the pictures...")
    save(window, "main-window.png")
    for title, name in (("Transcription", "transcription-panel.png"), ("Voices", "voices-panel.png"),
                        ("Caption Styling", "styling-panel.png"), ("Export", "export-panel.png")):
        save(panel(window, title), name)
    save(window.center_splitter.widget(1), "transcript-editor.png")
    menus = {a.text().replace("&", ""): a.menu() for a in window.menuBar().actions()}
    window.fill_recent_menu()
    save_menu(app, window, menus["File"], "file-menu.png")
    save_menu(app, window, menus["Help"], "help-menu.png")

    window.dirty = False
    window.close()
    pump(app, 0.3)
    shutil.rmtree(TEMP, ignore_errors=True)
    say("Done:", OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        say("FAILED:", exc)
        raise
