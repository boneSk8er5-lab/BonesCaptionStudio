"""Stand-in for Whisper used only by make_guide_pictures.py: returns a made-up demo transcript instantly,
so the guide's pictures never show anyone's real video or words."""
tqdm = None  # the app swaps this for its progress bar
from . import transcribe  # noqa: F401

DEMO_LINES = [
    (0, "Okay chat, we finally made it to the last zone."),
    (1, "Watch the left side, I can hear footsteps!"),
    (0, "Got him. That was way too close."),
    (2, "Warning. Storm closing in sixty seconds."),
    (1, "Let's go! Grab the loot and rotate."),
    (0, "Don't forget to hit that follow button."),
]


def demo_words():
    words, t = [], 0.4
    for speaker, line in DEMO_LINES:
        for w in line.split():
            words.append({"word": " " + w, "start": round(t, 2), "end": round(t + 0.32, 2), "demo_speaker": speaker})
            t += 0.38
        t += 0.9
    return words


def load_model(name, device="cpu", download_root=None, **kw):
    class Model:
        def transcribe(self, audio, **kw):
            with transcribe.tqdm.tqdm(total=100) as bar:
                bar.update(100)
            return {"segments": [{"words": [{k: v for k, v in w.items() if k != "demo_speaker"}
                                            for w in demo_words()]}]}
    return Model()
