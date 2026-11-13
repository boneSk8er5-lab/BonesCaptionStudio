# Make your first captions

1. Drag a video onto the window, or click **Import Video** (`Ctrl+I`).
2. In **Transcription**, pick a model. **Base** is a good start. **Small** or **Medium** make fewer mistakes but take longer.
3. Pick the **language**, or leave it on **Auto-detect**.
4. Click **Generate Captions** (`F5`).
5. Wait for the progress bar. Click **Cancel Transcription** if you change your mind.
6. Press **Play** (or `Space`) to watch the captions on the preview.

![The Transcription panel: model, language, hardware and Generate Captions](transcription-panel.png)

When it's done, every line shows up in the **Transcript Editor** under the preview. Fix any words it got wrong there. See [Fix the transcript](topic:transcript-editor).

## Which model?

- **Tiny**: fastest, least accurate. Good for a quick test.
- **Base**: fast, and comes with the app.
- **Small**: a good balance.
- **Medium**: most accurate, slow on a CPU.
- **Turbo**: accurate and fast, best with an NVIDIA card.

## CPU or GPU

The hardware box is normally on **Auto-Select Hardware**, which uses your NVIDIA card when it can. Pick **Force CPU Standard Mode** if the GPU gives you trouble.

> Supported videos: `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm` and `.m4v`.
