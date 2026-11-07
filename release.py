"""
Bones Caption Studio - build environments + portable releases.

    python release.py setup [cpu|gpu|all]   one-time: create the private build environments
    python release.py build [cpu|gpu|all]   build portable release zip(s)
    python release.py run                   run the app from source (GPU environment if set up)

The build environments live in %LOCALAPPDATA%\\BonesCaptionStudio\\envs (outside OneDrive), so your
normal Python and its packages (TTS etc.) are never changed. Releases go to
%USERPROFILE%\\BonesCaptionStudio_Releases (also outside OneDrive).

  CPU edition: small, runs on every Windows 10/11 64-bit PC.
  GPU edition: NVIDIA graphics cards transcribe much faster; on other PCs it falls back to the CPU.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
LOCAL = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "BonesCaptionStudio")
ENVS = os.path.join(LOCAL, "envs")
WORK = os.path.join(LOCAL, "pyinstaller")
OUT_ROOT = os.path.join(os.path.expanduser("~"), "BonesCaptionStudio_Releases")
COUNTER_FILE = os.path.join(OUT_ROOT, "beta_counter.json")
GITHUB_LIMIT = 2 * 1024 ** 3          # GitHub: each release file must be under 2 GB
PART_SIZE = 1900 * 1024 ** 2          # split bigger zips into 1.9 GB parts

TORCH_VERSION = "2.9.1"
EDITIONS = {
    "cpu": {"label": "CPU", "torch_index": "https://download.pytorch.org/whl/cpu",
            "zip_tag": "Windows_x64_CPU"},
    "gpu": {"label": "GPU", "torch_index": "https://download.pytorch.org/whl/cu128",
            "zip_tag": "Windows_x64_GPU-NVIDIA"},
}
APP_PACKAGES = ["openai-whisper==20250625", "PySide6", "Pillow", "pyinstaller"]

os.makedirs(LOCAL, exist_ok=True)
os.makedirs(OUT_ROOT, exist_ok=True)
LOG = open(os.path.join(ROOT, "release_log.txt"), "a", encoding="utf-8")


def say(*parts):
    msg = " ".join(str(p) for p in parts)
    print(msg, flush=True)
    LOG.write(msg + "\n")
    LOG.flush()


def fail(msg):
    say("")
    say("FAILED:", msg)
    say("(details in release_log.txt)")
    sys.exit(1)


def run(cmd, show=False):
    say(">", " ".join(cmd))
    if show:  # stream to the window as well (long downloads), still logged
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in proc.stdout:
            print(line, end="", flush=True)
            LOG.write(line)
        LOG.flush()
        return proc.wait()
    return subprocess.run(cmd, stdout=LOG, stderr=subprocess.STDOUT).returncode


def human(n):
    return f"{n / 1024 ** 2:,.0f} MB"


def env_python(edition):
    return os.path.join(ENVS, edition, "Scripts", "python.exe")


def env_ready(edition):
    py = env_python(edition)
    if not os.path.exists(py):
        return False
    return subprocess.run([py, "-c", "import torch, whisper, PySide6, PyInstaller"],
                          capture_output=True).returncode == 0


def pick_editions(arg):
    if arg in (None, "all"):
        return ["cpu", "gpu"]
    if arg in EDITIONS:
        return [arg]
    fail(f"Unknown edition '{arg}' (use cpu, gpu or all)")


# ====================================================================== setup
def setup(editions):
    say(f"=== Setting up build environments in {ENVS} ===")
    say("Your normal Python is not changed.")
    for ed in editions:
        info = EDITIONS[ed]
        target = os.path.join(ENVS, ed)
        say("")
        say(f"--- {info['label']} environment ---")
        if not os.path.exists(env_python(ed)):
            if run([sys.executable, "-m", "venv", target]) != 0:
                fail(f"Couldn't create the {ed} environment")
        py = env_python(ed)
        run([py, "-m", "pip", "install", "--upgrade", "pip"])
        say(f"Installing PyTorch {TORCH_VERSION} ({info['label']}) - this is a big download"
            + (" (~3 GB)" if ed == "gpu" else " (~250 MB)") + "...")
        if run([py, "-m", "pip", "install", f"torch=={TORCH_VERSION}", "--index-url", info["torch_index"]], show=True) != 0:
            fail(f"PyTorch install failed for {ed}")
        say("Installing Whisper, PySide6, Pillow, PyInstaller...")
        if run([py, "-m", "pip", "install"] + APP_PACKAGES, show=True) != 0:
            fail(f"Package install failed for {ed}")
        check = subprocess.run([py, "-c",
                                "import torch, numpy, whisper, numba, PySide6; "
                                "torch.from_numpy(numpy.zeros(2)); "
                                "print('torch', torch.__version__, '| cuda build', torch.version.cuda, "
                                "'| GPU here:', torch.cuda.is_available(), '| numpy', numpy.__version__, "
                                "'| numba', numba.__version__, '| PySide6', PySide6.__version__)"],
                               capture_output=True, text=True)
        say(check.stdout.strip() or check.stderr.strip()[-800:])
        if check.returncode != 0:
            fail(f"The {ed} environment doesn't work - see above")
        say(f"{info['label']} environment ready.")
    say("")
    say("SETUP OK")


# ====================================================================== run from source
def run_app():
    for ed in ("gpu", "cpu"):
        if os.path.exists(env_python(ed)):
            say(f"Running from source with the {EDITIONS[ed]['label']} environment")
            sys.exit(subprocess.call([env_python(ed), os.path.join(ROOT, "bones_caption_studio.py")]))
    say("No build environment yet - running with your normal Python")
    sys.exit(subprocess.call([sys.executable, os.path.join(ROOT, "bones_caption_studio.py")]))


# ====================================================================== build
def next_version():
    with open("bones_caption_studio.py", "r", encoding="utf-8") as f:
        match = re.search(r'APP_VERSION = "([^"]+)"', f.read())
    if not match:
        fail("Couldn't find APP_VERSION in bones_caption_studio.py")
    base = match.group(1)
    try:
        with open(COUNTER_FILE, "r", encoding="utf-8") as f:
            counters = json.load(f)
    except Exception:
        counters = {}
    beta = counters.get(base, 0) + 1
    return base, beta, counters


def find_base_model():
    local = os.path.join(ROOT, "models", "base.pt")
    for path in (local, os.path.join(os.path.expanduser("~"), ".cache", "whisper", "base.pt")):
        if os.path.exists(path):
            return path
    say("Downloading the Whisper 'base' model (~140 MB)...")
    os.makedirs(os.path.dirname(local), exist_ok=True)
    py = env_python("cpu") if os.path.exists(env_python("cpu")) else env_python("gpu")
    run([py, "-c", "import whisper; whisper._download(whisper._MODELS['base'], r'%s', False)" % os.path.dirname(local)])
    if not os.path.exists(local):
        fail("Couldn't download the Whisper base model")
    return local


def folder_size(path):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)


def sha256_of(path):
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def split_file(path):
    """Split into .001/.002... parts that 7-Zip/WinRAR open directly, plus a JOIN bat for plain Windows."""
    parts = []
    with open(path, "rb") as src:
        index = 1
        while True:
            chunk = src.read(PART_SIZE)
            if not chunk:
                break
            part = f"{path}.{index:03}"
            with open(part, "wb") as dst:
                dst.write(chunk)
            parts.append(part)
            index += 1
    names = [os.path.basename(p) for p in parts]
    join_bat = os.path.join(os.path.dirname(path), f"JOIN_{os.path.basename(path)}.bat")
    with open(join_bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("@echo off\ncd /d \"%~dp0\"\n"
                "echo Joining the download parts into one zip...\n"
                f"copy /b {'+'.join(chr(34) + n + chr(34) for n in names)} \"{os.path.basename(path)}\"\n"
                f"echo Done: {os.path.basename(path)}  -  right-click it and choose Extract All.\npause\n")
    os.remove(path)
    return parts, join_bat


def build_edition(ed, version, base_model, docs):
    info = EDITIONS[ed]
    py = env_python(ed)
    say("")
    say(f"=== {info['label']} edition ===")
    if not env_ready(ed):
        say(f"Skipping: the {info['label']} build environment isn't set up (run setup_build_tools.bat).")
        return None

    dist = os.path.join(WORK, ed, "dist")
    say("Building with PyInstaller (5-20 minutes)...")
    started = time.time()
    if run([py, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--workpath", os.path.join(WORK, ed, "build"), "--distpath", dist, "BonesCaptionStudio.spec"]) != 0:
        fail(f"PyInstaller failed for the {ed} edition")
    say(f"Build finished in {(time.time() - started) / 60:.1f} min")
    app = os.path.join(dist, "BonesCaptionStudio")
    for needed in ("ffmpeg.exe", "ffprobe.exe"):
        if not os.path.exists(os.path.join(app, "_internal", needed)):
            fail(f"{needed} is missing from the {ed} build")

    name = f"BonesCaptionStudio_v{version}_{info['label']}"
    out_dir = os.path.join(OUT_ROOT, name)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(app, out_dir)
    with open(os.path.join(out_dir, "portable.txt"), "w", encoding="utf-8") as f:
        f.write("This file turns on portable mode.\n"
                "Settings, presets, logs and downloaded Whisper models stay inside this folder.\n"
                "Delete it to store settings in %APPDATA%\\BonesCaptionStudio instead.\n")
    with open(os.path.join(out_dir, "version.txt"), "w", encoding="utf-8") as f:
        f.write(f"{version} ({info['label']})\n")
    os.makedirs(os.path.join(out_dir, "models"), exist_ok=True)
    shutil.copy2(base_model, os.path.join(out_dir, "models", "base.pt"))
    for src in docs:
        shutil.copy2(src, os.path.join(out_dir, os.path.basename(src)))
    say("Folder:", out_dir, human(folder_size(out_dir)))

    zip_path = os.path.join(OUT_ROOT, f"BonesCaptionStudio_v{version}_{info['zip_tag']}.zip")
    say("Zipping (a few minutes)...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for root, _, files in os.walk(out_dir):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, OUT_ROOT))
    size = os.path.getsize(zip_path)
    digest = sha256_of(zip_path)
    say("Zip:", os.path.basename(zip_path), human(size))
    result = {"edition": info["label"], "zip": os.path.basename(zip_path), "size": size,
              "sha256": digest, "parts": [], "join": None}
    if size >= GITHUB_LIMIT:
        say("Over GitHub's 2 GB limit - splitting into parts...")
        parts, join_bat = split_file(zip_path)
        result["parts"] = [os.path.basename(p) for p in parts]
        result["join"] = os.path.basename(join_bat)
        say("Parts:", ", ".join(result["parts"]), "+", result["join"])
    with open(os.path.join(OUT_ROOT, f"{os.path.basename(zip_path)}.sha256.txt"), "w", encoding="utf-8") as f:
        f.write(f"{digest}  {os.path.basename(zip_path)}\n")
    return result


def write_notes(version, results):
    changes = ""
    try:
        with open("CHANGELOG.md", "r", encoding="utf-8") as f:
            sections = re.split(r"\n(?=## )", f.read())
        changes = "\n\n".join(s.strip() for s in sections[1:4])
    except Exception:
        pass
    downloads = []
    for r in results:
        if r["edition"] == "CPU":
            who = "**CPU edition** (works on every PC, smallest download)"
        else:
            who = "**GPU edition** (much faster on NVIDIA graphics cards; also runs on other PCs using the CPU)"
        if r["parts"]:
            files = ", ".join(f"`{p}`" for p in r["parts"]) + f" and `{r['join']}`"
            how = (f"download all parts plus `{r['join']}` into one folder and double-click the .bat "
                   f"(or open `{r['parts'][0]}` with 7-Zip/WinRAR)")
        else:
            files, how = f"`{r['zip']}`", "download it"
        downloads.append(f"- {who}: {files} ({human(r['size'])}). To use: {how}.")
    sums = "\n".join(f"- `{r['zip']}`: `{r['sha256']}`" for r in results)
    notes = f"""# Bones Caption Studio v{version}

**Beta test build.** Portable, nothing to install. Windows 10/11 (64-bit).

## Which download?
{chr(10).join(downloads)}

Not sure? Take the CPU edition.

## Run it
1. Right-click the zip and choose **Extract All**. Don't run it from inside the zip.
2. Open the extracted folder and double-click **BonesCaptionStudio.exe**.
3. If Windows shows "Windows protected your PC" (the app isn't code-signed yet), click **More info**, then **Run anyway**.

The Whisper **Base** model is included, so captions work offline. Other models download once into the app's `models` folder.
The Transcription panel shows whether a GPU was found.

## Reporting bugs
Click **📂 Logs & Settings** at the top of the app and attach `debug_log.txt`, plus the version from the title bar.

## What's new
{changes}

## SHA-256
{sums}
"""
    path = os.path.join(OUT_ROOT, f"RELEASE_NOTES_v{version}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(notes)
    return path


def build(editions):
    base, beta, counters = next_version()
    version = f"{base}-beta.{beta}"
    say(f"=== Bones Caption Studio release v{version} ===")
    ready = [ed for ed in editions if env_ready(ed)]
    if not ready:
        fail("No build environment is set up yet. Run setup_build_tools.bat first.")

    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        if not os.path.exists(os.path.join(ROOT, tool)):
            fallback = os.path.join(ROOT, "dist", "BonesCaptionStudio", tool)
            if os.path.exists(fallback):
                shutil.copy2(fallback, os.path.join(ROOT, tool))
            else:
                fail(f"{tool} not found next to release.py")
    docs = [os.path.join(ROOT, "release_files", "README.txt"),
            os.path.join(ROOT, "release_files", "THIRD_PARTY_NOTICES.txt"),
            os.path.join(ROOT, "CHANGELOG.md")]
    docs = [d for d in docs if os.path.exists(d)]
    base_model = find_base_model()

    results = []
    for ed in editions:
        result = build_edition(ed, version, base_model, docs)
        if result:
            results.append(result)
    if not results:
        fail("Nothing was built")
    notes = write_notes(version, results)
    counters[base] = beta
    with open(COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump(counters, f, indent=2)
    say("")
    say("RELEASE OK")
    say("  Output folder:", OUT_ROOT)
    say("  Notes:", os.path.basename(notes))
    if sys.platform == "win32":
        os.startfile(OUT_ROOT)


if __name__ == "__main__":
    LOG.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {' '.join(sys.argv[1:])} =====\n")
    command = sys.argv[1] if len(sys.argv) > 1 else "build"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if command == "setup":
        setup(pick_editions(arg))
    elif command == "build":
        build(pick_editions(arg))
    elif command == "run":
        run_app()
    else:
        fail(f"Unknown command '{command}' (use setup, build or run)")
