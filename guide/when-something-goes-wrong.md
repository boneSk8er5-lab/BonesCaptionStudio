# When something goes wrong

## "FFmpeg not found"

The app needs `ffmpeg.exe` and `ffprobe.exe` to read and export videos. They come with the download. If they're missing, download the app again and extract the whole zip, not just the `.exe`.

## The zip won't extract

- The GPU version comes in two parts. Put both parts and the `JOIN_....bat` in one folder, then run the `.bat`. See [Install and first start](topic:get-started).
- Extract to a short path like `C:\BCS`. Very deep folders can be too long for Windows.
- Make sure the download finished. A half-downloaded zip looks "invalid".

## Transcribing is slow

- Use a smaller model (**Base** or **Small**).
- With an NVIDIA card, use the GPU version and leave the hardware box on **Auto-Select Hardware**.
- Long videos take a while on a CPU. The progress bar shows how far along it is.

## The words are wrong

- Try a bigger model: **Small**, **Medium** or **Turbo**.
- Pick the right **language** instead of **Auto-detect**.
- With game sound in the background, record your mic on its own track. See [Audio tracks](topic:audio-tracks).
- Fix the rest by hand. See [Fix the transcript](topic:transcript-editor).

## Captions are a little early or late

Change **Timing offset** in **Caption Styling**. See [Make the captions look good](topic:caption-style).

## Voices got mixed up

Set **Number of voices** to the exact number of people and click **🎙 Detect Voices** again, or fix lines by hand with the number keys. See [Voices](topic:voices).

## Get help from someone

The app writes everything it does to a log file. It's the best thing to send when asking for help.

1. Open **Help** › **Open Logs & Settings Folder**.
2. Send `debug_log.txt`.
