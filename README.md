# Bones Caption Studio

Auto-captions for your videos: transcribe speech with OpenAI Whisper, style animated word-highlight captions, and export them as a transparent overlay, a burned-in video, or subtitle files.

**Status: beta.** Windows 10/11 (64-bit). Portable: no installer needed.

## Download

Grab the latest release from **[Releases](../../releases)**, extract it, and run `BonesCaptionStudio.exe`:

- **CPU edition** (`…_Windows_x64_CPU.zip`): works on every PC, smallest download.
- **GPU edition** (`…_Windows_x64_GPU-NVIDIA`): much faster on NVIDIA graphics cards, and falls back to the CPU elsewhere. If it's split into parts, download them all and run the included `JOIN_….bat`, or open the `.001` file with 7-Zip/WinRAR.

The Whisper *Base* model is included, so it works offline out of the box.

> Windows may say "Windows protected your PC" because the app isn't code-signed yet. Click **More info → Run anyway**.

## Features

- Whisper transcription with word-level timing, GPU-accelerated on NVIDIA cards (Tiny → Medium/Turbo models, language picker)
- Caption modes: **Sentence**, **Auto** (new caption at pauses), **Word**
- **Voices**: automatic speaker detection (small built-in model, offline), per-voice colours and name tags, hide a whole voice in one click
- Transcript editor: hide/restore lines or words, undo/redo, search, voice shortcuts (1-9)
- Word highlight, drop shadow (angle, distance, softness, strength), text/highlight/outline colours, background box, text size, top/center/bottom alignment, line wrapping
- Live preview with sound, seek bar, and a clickable transcript you can edit
- Exports:
  - transparent **ProRes 4444 .mov** overlay for any video editor
  - **MP4** with captions burned in (optional 1080×1920 vertical for TikTok/Shorts/Reels)
  - **SRT / VTT** subtitles
- Style presets, save/open projects, any installed font with favourites
- Red-green colour-blind friendly theme option

## Reporting bugs

Click **📂 Logs & Settings** in the app and attach `debug_log.txt` to a new [issue](../../issues), with the version from the title bar.

## Building from source

Needs Windows and Python 3.10+. Put `ffmpeg.exe` and `ffprobe.exe` next to `bones_caption_studio.py`, then:

```
setup_build_tools.bat    # one time: private CPU + GPU build environments (your normal Python isn't touched)
run_from_source.bat      # run the app from source
release.bat              # build both portable editions into %USERPROFILE%\BonesCaptionStudio_Releases
```

## Credits

Made by Bones_84. Built on OpenAI Whisper, PyTorch, Qt for Python and FFmpeg; see `THIRD_PARTY_NOTICES.txt`.
