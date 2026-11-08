# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

# This forces the inclusion of all whisper assets
whisper_datas, whisper_binaries, whisper_hidden = collect_all('whisper')

# App icon is bundled so the window/taskbar use it too
extra_datas = [(f, '.') for f in ('BCS.ico', 'voice_encoder.npz') if os.path.exists(f)]  # icon + built-in voice model

# If ffmpeg.exe / ffprobe.exe sit next to this .spec they get bundled automatically,
# so a rebuild never leaves you without them.
extra_binaries = [(f, '.') for f in ('ffmpeg.exe', 'ffprobe.exe') if os.path.exists(f)]

a = Analysis(
    ['bones_caption_studio.py'],
    pathex=[],
    binaries=whisper_binaries + extra_binaries,
    datas=whisper_datas + extra_datas,
    hiddenimports=['tiktoken', 'regex', 'tqdm', 'torch', 'numpy', 'voice_detect'] + whisper_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Packages that happen to be installed in the build Python but the app never uses.
    # Leaving them out keeps the portable release small enough for a GitHub release.
    excludes=[
        'pandas', 'matplotlib', 'IPython', 'jupyter', 'notebook', 'tkinter',
        'spacy', 'thinc', 'blis', 'cymem', 'preshed', 'murmurhash', 'srsly', 'wasabi', 'weasel',
        'transformers', 'tokenizers', 'safetensors', 'huggingface_hub', 'hf_xet',
        'cv2', 'sklearn', 'scipy', 'librosa', 'soundfile', 'soxr', 'nltk', 'jieba',
        'sudachipy', 'sudachidict_core', 'pycrfsuite', 'onnxruntime', 'tensorboard',
        'torchvision', 'torchaudio', 'av', 'imageio', 'imageio_ffmpeg', 'aiohttp',
        'pydantic', 'pydantic_core', 'Cython', 'TTS', 'gruut', 'pypinyin', 'unidic_lite',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BonesCaptionStudio',
    icon='BCS.ico' if os.path.exists('BCS.ico') else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='BonesCaptionStudio',
)
