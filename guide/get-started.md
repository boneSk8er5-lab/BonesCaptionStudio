# Install and first start

## Pick a version

- **CPU** works on every Windows 10/11 PC. It's the smaller download.
- **GPU (NVIDIA)** transcribes much faster if you have an NVIDIA graphics card. On a PC without one, it uses the CPU automatically.

Each version comes two ways:

- **Installer** (`..._Setup.exe`): run it and follow the steps. It adds a Start menu shortcut and lets you double-click projects to open them. No admin password needed.
- **Portable zip**: nothing to install. Right-click the zip, choose **Extract All**, open the folder and run `BonesCaptionStudio.exe`. It keeps its settings in its own folder, so it works from a USB stick too.

> Extract the zip to a short path like `C:\BCS` or your **Downloads** folder. Very deep folders can be too long for Windows.

## The GPU download comes in parts

GitHub only allows files up to 2 GB, so the GPU zip is split into `.zip.001` and `.zip.002`.

1. Download both parts **and** the `JOIN_....bat` file into the same folder.
2. Double-click the `JOIN_....bat`. It makes one normal `.zip`.
3. Extract that zip as above.

## "Windows protected your PC"

The app isn't signed with a paid certificate yet, so Windows may show a blue warning the first time. Click **More info**, then **Run anyway**. You only need to do this once.

## The first time you transcribe

The **Base** model comes with the app. Other models download the first time you use them (75 MB to 1.5 GB), and you'll see a progress bar while they download. After that, everything works offline.
