# Bones Caption Studio – Changelog

## 6.7.0
**Projects & menus**
- New **menu bar**: File (New, Open, Open Recent, Save, Save As, Import Video, Export, Exit),
  Edit (Undo, Redo, Find, Hide/Show, Set Voice) and Help (Keyboard Shortcuts, Logs folder,
  Check for Updates, About).
- The title bar shows the project name and a ● when there are unsaved changes.
- Projects now save as **.bcsproj** files (older .bcs.json projects still open).
- **Open Recent** remembers your last 10 projects.
- **Autosave & crash recovery**: unsaved work is saved every 90 seconds and offered back if the app
  closes unexpectedly.
- Open a project by dropping it on the window or double-clicking it in File Explorer
  (installer, or Help › "Open .bcsproj files with Bones Caption Studio" for the portable version).
- The window opens at the size and position you left it (never off-screen).

**Captions & export**
- **Timing offset** (−5 to +5 s) moves all captions earlier or later.
- **Caption height** fine-tunes how high or low captions sit.
- **Crop** slider for vertical (1080×1920) exports: choose which part of the picture to keep.
- **Progress bars** for model downloads and transcription, and a **Cancel** button.
- Checks free disk space before exporting and warns about very large overlay files.
- Clear message if FFmpeg is missing.
- Help › **Reset settings to defaults** (keeps your fonts, presets, voices and recent projects).
- Help › **Check for Updates**.

**Releases**
- No longer a beta. Each release has a portable zip **and a Windows installer** (per-user, no
  admin rights, Start menu shortcut, optional desktop shortcut).

## 6.6.0 (beta)
**Voices**
- New **Voices** panel: give each person their own name and colour (Voice 1, Voice 2... rename to Bones, Vyper...).
- **Detect Voices** works out who is talking automatically with a small built-in voice model
  (2.6 MB, no account, works offline). Set **Number of voices** for the best results. Optional
  "Detect voices after transcribing".
- **Voice colours**: Highlight (the spoken word uses the voice's colour), Whole line, or Off.
- **Name tags**: show "Name:" in front of each caption.
- A new caption starts whenever the voice changes. SRT/VTT exports include voice names.
- **Hide / Show** every line from one voice in one click (great for game characters).
- Voice names and colours are remembered for next time and saved in projects.

**Transcript editor**
- Shows caption lines with time and voice; expand a line (▸) to edit single words.
- **Hide / Show** lines or words (Delete key); hidden text stays in the project, greyed out.
- **Shift+Delete** deletes permanently. **Undo / Redo** (Ctrl+Z / Ctrl+Y) for every edit.
- Press **1-9** to give the selected lines a voice (0 = no voice), or use **Set Voice**.
- Double-click a line to fix its words; right-click menu for everything.
- **Search** the transcript (Ctrl+F).
- Draggable divider between the preview and the transcript.

## 6.5.0 (beta)
- Drop shadow controls: **Shadow angle** (any direction, in 15° steps), **Shadow distance**
  (0 = right behind the text, for a glow look), **Shadow softness** (0% = hard, crisp edge)
  and **Shadow strength** now goes up to 300% for a denser, darker shadow.
- **Caption only your voice**: if a video has more than one audio track (e.g. OBS recording
  your mic on its own track), pick which track to caption in the Transcription panel. The
  preview plays that track, track names from OBS show up, and the choice is saved in projects.
- Full-video exports keep every audio track from the original recording.

## 6.4.0 (beta)
- New **Drop Shadow** option: a soft shadow behind the caption text, sized to the text.
  Works with or without the background box and outline, and shows in the preview, the
  transparent .mov overlay and full-video exports.
- **Shadow strength** setting (10-100%). Both are saved in style presets and projects.

## 6.3.1 (beta)
- Fixed: the settings sidebar was cut off on the right (Save Project, preset Save/Delete,
  Outline, Mode and more were hidden). Dropdowns no longer stretch to their longest entry,
  and the sidebar is always wide enough for every control.
- The divider between the settings and the preview can be dragged, and its position is remembered.
- The app fits smaller screens and high display scaling (125-150%) better.

## 6.3.0 (beta)
- GPU support: a GPU (NVIDIA) edition alongside the CPU edition. The Transcription panel shows
  which GPU was found (or that it's using the CPU). The AI engine loads in the background at
  startup, so the first transcription starts sooner.
- Portable release: extract the zip and run, nothing to install. Settings, presets, logs and
  Whisper models stay inside the app folder (portable.txt).
- The Whisper Base model is included, so captions work offline from the first run.
- The model list shows which models are ready and which download on first use.
- New "Logs & Settings" button opens the folder with debug_log.txt for bug reports.
- Title bar shows the exact build (e.g. v6.3.0-beta.1).
- Much smaller download: unused libraries are no longer bundled.

## 6.2.1
- Text size, Max words and Pause boxes now have big − / + buttons (hold to keep changing).
  The tiny arrows didn't work properly on Windows 11 with the dark theme, so you couldn't
  raise Text size above 100%. Typing a value, arrow keys and the mouse wheel still work too.
- The Pause box now matches the dark theme.

## 6.2.0
- New caption mode **Auto (pauses)**: the Mode button now cycles Sentence → Auto → Word.
  Auto still splits at . ! ? and at "Max words per caption", and also starts a new caption
  whenever the speaker pauses longer than the "New caption after a pause of" setting (default 0.5 s).
- Captions disappear during long silences instead of lingering, even when Whisper stretches
  the last word's timing into the silence.
- SRT/VTT exports follow the same splits.

## 6.1.0
- Preview now plays the video's sound. The audio drives the playback clock, so captions and picture stay in sync and play at real speed.
- Mute button and volume slider next to the seek bar (remembered between launches).
- Seeking, clicking a word and Back-to-start all move the sound too.
- Videos without audio still play at the right speed, just silently.

## 6.0.0
**Fixes**
- Alignment button now shows up (it was never added to the panel). Cycles Bottom → Center → Top.
- Caption background in full-video exports is see-through again (it was coming out solid black).
- Export checks FFmpeg's result. Failures show the real error instead of "Export Finished!".
- Caption size scales with the video resolution, so the preview matches the export.
- Caption box lines up exactly with the text.
- Fonts installed "for current user only" are found (e.g. Bangers).
- Importing a video shows its first frame right away and clears the old video's captions.
- Odd-sized videos (e.g. 1279x719) no longer break full-video exports.
- Phone videos with rotation are handled; vertical crop works for any source shape.
- No more black console windows flashing during export (windowed .exe).
- Pop-up dialogs use the dark theme.
- A video with no audio gets a clear message.

**Speed / stability**
- Export runs in the background with a Cancel button; the window stays responsive.
- The Whisper model is loaded once and reused.
- Font list loads in the background and is cached, so startup is faster.
- Debug log only records the app's own messages, is capped at 2 MB, and lives in %APPDATA%\BonesCaptionStudio.
- Settings and favourites are saved in %APPDATA%\BonesCaptionStudio, whichever way the app is started (old favourites are copied over).

**New**
- Export subtitles as .srt or .vtt.
- Long captions wrap onto multiple lines. "Max words per caption" setting.
- Text outline (with outline colour) and Text size %.
- Seek bar, time display, Play/Pause (Space), back-to-start.
- Transcript shows timestamps: click to jump, double-click to edit, Delete key removes words.
- Save / Open projects (.bcs.json) with captions + style. Ctrl+S / Ctrl+O. Warns about unsaved edits.
- Style presets (Save / Delete).
- Whisper model choice (Tiny → Medium/Turbo) and language choice.
- Overlay mode preview shows the video underneath to help you position captions.
- "Open Folder" button after an export.
