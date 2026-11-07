BONES CAPTION STUDIO - BETA
===========================

Turns speech in your videos into styled, animated captions.
Portable: nothing to install. Windows 10/11, 64-bit.

GETTING STARTED
1. Extract the whole zip first (right-click > Extract All). Don't run it from inside the zip.
2. Double-click BonesCaptionStudio.exe.
   If Windows says "Windows protected your PC", click More info > Run anyway
   (the app isn't code-signed yet).
3. Drag a video onto the app (or click Import Video).
4. Click Generate Captions. The first run can take a while on slower PCs.
5. Style the captions, check them in the preview, then export.

EXPORT OPTIONS
- Caption Overlay Only (.mov): transparent captions to drop on top of your video
  in your editor (Premiere, DaVinci Resolve, CapCut, OBS...).
- Complete Video + Audio (.mp4): your video with the captions burned in.
  Tick "Vertical Format" for TikTok / Shorts / Reels (1080x1920).
- Export Subtitles (.srt / .vtt): plain subtitle files for YouTube or your editor.

TIPS
- Mode button: Sentence / Auto (pauses) / Word. Auto starts a new caption when
  the speaker pauses.
- Click a word in the transcript to jump to it, double-click to fix it,
  press Delete to remove it.
- Save Project (Ctrl+S) keeps your edits so you can come back later.
- Whisper models: Base is included and works offline. Small / Medium are more
  accurate but slower, and download once the first time you pick them.
- GPU edition: NVIDIA cards transcribe much faster. The Transcription panel shows
  "GPU ready" when it finds one. Without an NVIDIA card it simply uses the CPU.
- CPU edition: works on every PC. Longer videos take a few minutes.

THIS FOLDER
- portable.txt : keeps settings, logs and models inside this folder.
- data\        : your settings, presets and debug_log.txt (created on first run).
- models\      : Whisper speech models.
- _internal\   : the app's own files. Don't move or delete anything in here.

FOUND A BUG?
Click "Logs & Settings" at the top of the app and send debug_log.txt,
along with the version number from the title bar and what you were doing.
