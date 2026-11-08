import numpy as np


def _sig(x):
    return 0.5 * (1.0 + np.tanh(0.5 * x))  # overflow-free sigmoid

class VoiceEncoder:
    """Speaker-embedding model (Resemblyzer GE2E, Apache-2.0) running in plain numpy."""
    def __init__(self, path):
        w = np.load(path)
        self.mel_basis = w["mel_basis"].astype(np.float32)
        self.layers = [(w[f"lstm.weight_ih_l{i}"].astype(np.float32).T, w[f"lstm.weight_hh_l{i}"].astype(np.float32).T,
                        (w[f"lstm.bias_ih_l{i}"] + w[f"lstm.bias_hh_l{i}"]).astype(np.float32)) for i in range(3)]
        self.lin_w = w["linear.weight"].astype(np.float32).T
        self.lin_b = w["linear.bias"].astype(np.float32)
        n = np.arange(400)
        self.window = (0.5 - 0.5 * np.cos(2 * np.pi * n / 400)).astype(np.float32)  # periodic Hann

    def mel(self, wav):
        pad = np.pad(wav.astype(np.float32), (200, 200))
        n_frames = 1 + (len(pad) - 400) // 160
        idx = np.arange(400)[None, :] + 160 * np.arange(n_frames)[:, None]
        spec = np.abs(np.fft.rfft(pad[idx] * self.window, n=400, axis=1)) ** 2
        return (spec @ self.mel_basis.T).astype(np.float32)            # (frames, 40)

    def forward(self, mels):                                           # (B, T, 40) -> (B, 256)
        x = mels
        B = x.shape[0]
        for w_ih, w_hh, b in self.layers:
            xi = x @ w_ih + b                                          # (B, T, 1024)
            h = np.zeros((B, 256), np.float32); c = np.zeros((B, 256), np.float32)
            outs = np.empty((B, x.shape[1], 256), np.float32)
            for t in range(x.shape[1]):
                g = xi[:, t] + h @ w_hh
                i, f, gg, o = g[:, :256], g[:, 256:512], g[:, 512:768], g[:, 768:]
                c = _sig(f) * c + _sig(i) * np.tanh(gg)
                h = _sig(o) * np.tanh(c)
                outs[:, t] = h
            x = outs
        e = np.maximum(h @ self.lin_w + self.lin_b, 0)
        return e / (np.linalg.norm(e, axis=1, keepdims=True) + 1e-9)

    @staticmethod
    def normalize(wav, target_dbfs=-30):
        rms = np.sqrt(np.mean(wav.astype(np.float64) ** 2)) + 1e-9
        change = target_dbfs - 20 * np.log10(rms)
        return wav * (10 ** (change / 20)) if change > 0 else wav

    def partial_mels(self, wav, rate=1.3, min_coverage=0.75):
        n_samples = len(wav)
        n_frames = int(np.ceil((n_samples + 1) / 160))
        step = int(np.round((16000 / rate) / 160))
        starts = list(range(0, max(1, n_frames - 160 + step + 1), step))
        last = starts[-1] * 160
        if (n_samples - last) / (160 * 160) < min_coverage and len(starts) > 1:
            starts = starts[:-1]
        need = (starts[-1] + 160) * 160
        if need >= n_samples:
            wav = np.pad(wav, (0, need - n_samples))
        mel = self.mel(wav)
        return [mel[s:s + 160] for s in starts]

    def embed_many(self, wavs):
        """Embeddings for many utterances, batched for speed."""
        parts, owner = [], []
        for i, wav in enumerate(wavs):
            for m in self.partial_mels(self.normalize(wav)):
                parts.append(m); owner.append(i)
        owner = np.array(owner)
        out = np.zeros((len(wavs), 256), np.float32)
        for s in range(0, len(parts), 256):
            emb = self.forward(np.stack(parts[s:s + 256]))
            np.add.at(out, owner[s:s + 256], emb)
        return out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-9)


# ----------------------------------------------------------------------------- clustering
def _kmeans_cos(E, k, rng, iters=40):
    n = len(E)
    centers = [E[rng.integers(n)]]
    for _ in range(1, k):                          # k-means++ seeding on cosine distance
        d = 1 - np.max(E @ np.array(centers).T, axis=1)
        d = np.clip(d, 0, None) ** 2
        centers.append(E[rng.choice(n, p=d / d.sum()) if d.sum() > 0 else rng.integers(n)])
    C = np.array(centers)
    for _ in range(iters):
        labels = np.argmax(E @ C.T, axis=1)
        newC = np.array([E[labels == j].sum(0) if np.any(labels == j) else C[j] for j in range(k)])
        newC /= np.linalg.norm(newC, axis=1, keepdims=True) + 1e-9
        if np.allclose(newC, C):
            break
        C = newC
    score = float(np.sum(np.max(E @ C.T, axis=1)))
    return labels, C, score


def kmeans_cos(E, k, restarts=8, seed=0):
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        res = _kmeans_cos(E, k, rng)
        if best is None or res[2] > best[2]:
            best = res
    return best[0], best[1]


def silhouette_cos(E, labels):
    D = 1 - E @ E.T
    ks = np.unique(labels)
    if len(ks) < 2:
        return -1.0
    a = np.zeros(len(E)); b = np.full(len(E), np.inf)
    for k in ks:
        m = labels == k
        mean_d = D[:, m].sum(1) / np.maximum(m.sum() - (labels == k).astype(int) * 0, 1)
        own = m
        a[own] = (D[np.ix_(own, own)].sum(1)) / np.maximum(own.sum() - 1, 1)
        b[~own] = np.minimum(b[~own], mean_d[~own])
    s = (b - a) / np.maximum(np.maximum(a, b), 1e-9)
    return float(np.mean(s))


def cluster_voices(E, n_voices=None, max_voices=8, min_silhouette=0.12):
    """Group embeddings into voices. n_voices=None picks the count automatically."""
    n = len(E)
    if n < 2:
        return np.zeros(n, int), E[:1]
    if n_voices:
        k = max(1, min(int(n_voices), n))
        return kmeans_cos(E, k) if k > 1 else (np.zeros(n, int), (E.sum(0, keepdims=True)))
    sample = E if n <= 1500 else E[np.random.default_rng(0).choice(n, 1500, replace=False)]
    best_k, best_s = 1, min_silhouette
    for k in range(2, min(max_voices, len(sample) - 1) + 1):
        labels, _ = kmeans_cos(sample, k, restarts=4)
        s = silhouette_cos(sample, labels)
        if s > best_s + 0.01:  # only add a voice if it clearly separates better
            best_k, best_s = k, s
    if best_k == 1:
        C = E.sum(0, keepdims=True); C /= np.linalg.norm(C)
        return np.zeros(n, int), C
    return kmeans_cos(E, best_k)


def _merge_similar(C, threshold):
    """Merge voice groups whose average voices are this similar (fixes one person split in two)."""
    C = [c for c in C]
    merged = True
    while merged and len(C) > 1:
        merged = False
        S = np.array(C) @ np.array(C).T
        np.fill_diagonal(S, -1)
        i, j = np.unravel_index(np.argmax(S), S.shape)
        if S[i, j] >= threshold:
            c = C[i] + C[j]
            C[i] = c / (np.linalg.norm(c) + 1e-9)
            del C[j]
            merged = True
    return np.array(C)


def speech_chunks(words, gap=0.5, max_len=3.5):
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and (w["start"] - words[cur[-1]]["end"] > gap or w["end"] - words[cur[0]]["start"] > max_len):
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


def diarize(encoder, audio, words, n_voices=None, sr=16000, merge_threshold=0.80, progress=None):
    """Returns one voice number (0, 1, 2...) per word, numbered in order of first appearance."""
    if not words:
        return []
    chunks = speech_chunks(words)
    wavs, durations = [], []
    for c in chunks:
        a = int(max(0, words[c[0]]["start"] - 0.05) * sr)
        b = int(min(len(audio) / sr, words[c[-1]]["end"] + 0.05) * sr)
        wavs.append(audio[a:max(b, a + int(0.3 * sr))])
        durations.append((b - a) / sr)
    durations = np.array(durations)
    E = np.zeros((len(wavs), 256), np.float32)
    for s in range(0, len(wavs), 64):  # in batches so we can report progress
        E[s:s + 64] = encoder.embed_many(wavs[s:s + 64])
        if progress:
            progress(min(len(wavs), s + 64), len(wavs))
    good = durations >= 1.0  # short snippets give unreliable voice prints
    if good.sum() < 2:
        good = np.ones(len(E), bool)
    _, C = cluster_voices(E[good], n_voices)
    if not n_voices:
        C = _merge_similar(C, merge_threshold)
    labels = np.argmax(E @ C.T, axis=1)
    sims = np.sort(E @ C.T, axis=1)
    margin = sims[:, -1] - (sims[:, -2] if C.shape[0] > 1 else 0)
    for i in range(1, len(labels) - 1):  # a lone short/uncertain chunk between two of the same voice
        if labels[i - 1] == labels[i + 1] != labels[i] and (durations[i] < 1.5 or margin[i] < 0.05):
            labels[i] = labels[i - 1]
    order = {}
    for l in labels:
        order.setdefault(int(l), len(order))
    per_word = [0] * len(words)
    for c, l in zip(chunks, labels):
        for i in c:
            per_word[i] = order[int(l)]
    return per_word
