# Webcam / video mode

`sentinel webcam` runs the same pipeline as `sentinel demo`, with a real detector
(Ultralytics **YOLO26n**) on live camera frames or a video file.

```
camera/video -> YOLO26n -> streaming aggregator -> triage -> reason -> decide
```

## Install the optional `vision` extra

```bash
uv sync --extra vision
```

This pulls `ultralytics` plus **CPU-only** PyTorch (~190 MB instead of the ~2 GB CUDA
build; see `[tool.uv.sources]` in `pyproject.toml`). The YOLO26n weights (5.3 MB) are
downloaded on first run to `~/.cache/sentinel-agent/`.

> **License:** Ultralytics YOLO is **AGPL-3.0**. Using it means your project must also be
> AGPL-3.0, or you need an Ultralytics Enterprise license. That's why it's an optional
> extra: the default install (synthetic demo, calibration library, agent) doesn't depend
> on it. [RF-DETR](https://github.com/roboflow/rf-detr) (Apache 2.0) could be dropped in
> through the same `Detector` protocol; it is more accurate but heavier on CPU.

## Run

```bash
uv run sentinel webcam                       # camera 0, preview window, q to quit
uv run sentinel webcam --source 1            # another camera
uv run sentinel webcam --source clip.mp4     # a video file
uv run sentinel webcam --zone 0.5,0,0.5,1    # restricted zone = right half of the frame
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--source` | `0` | Camera index or video path |
| `--fps` | `5` | Frames analysed per second (YOLO26n takes ~75 ms/frame on a laptop CPU) |
| `--zone` | `0.58,0.05,0.4,0.9` | Restricted zone as `x,y,w,h` fractions of the frame (drawn in red) |
| `--gap` | `1.5` | Seconds an object must be unseen before its event closes and is reasoned about |
| `--min-detections` | `3` | Frames a person **outside** the zone must be seen in before the agent reasons about it (anything in the zone always goes to the agent) |
| `--max-seconds` | none | Stop after this long |
| `--no-window` | off | No preview window (headless) |

Each event is printed when it closes: when the object has been gone for `--gap` seconds,
or after 30 s for someone who stays in view. Events with a person, or anything inside the
zone, go to the agent. Everything else is dismissed at triage without an LLM call, and so is
a person seen outside the zone in fewer than `--min-detections` frames. At 5 fps such a
single-frame flicker would otherwise land in human review, because the detector's per-frame
score is high while the agent's confidence (from track length) is low.

The agent runs in a background thread. A slow LLM call (seconds per event on Bedrock) doesn't
freeze the camera or the preview window; events are still decided one at a time, in the order
they closed. The window shows every camera frame and redraws the last boxes between analysed
frames.

## Using the webcam from WSL (usbipd-win)

WSL2 doesn't see USB webcams by default: there is no `/dev/video*`. `usbipd-win` forwards a
USB device from Windows into WSL. Recent WSL kernels (checked on 6.18) ship the UVC webcam
driver as a module, so this works:

```powershell
# Windows, once: install, then share the camera (admin; find its VID:PID with `usbipd list`)
winget install --id dorssel.usbipd-win -e
usbipd bind --hardware-id 046d:0825
```

```bash
# WSL, each time (after a reboot or `wsl --shutdown`, the attach is gone)
"/mnt/c/Program Files/usbipd-win/usbipd.exe" attach --wsl --hardware-id 046d:0825
sudo modprobe uvcvideo
sudo chgrp video /dev/video* && sudo chmod 660 /dev/video*   # WSL has no udev to do this
uv run sentinel webcam
```

On a Logitech C270 this gave 15 fps at 640x480 inside WSL, and the preview window opens
through WSLg. While the camera is attached to WSL, Windows apps cannot use it; give it back
with `usbipd detach --hardware-id 046d:0825`. Right after a detach, Windows needs a few
seconds before the camera can be attached again.

## Running from Windows when the repo lives in WSL

The alternative is to run the command with Windows Python on the same checkout:

```powershell
# once: install uv for Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# every time (new PowerShell window)
cd $HOME
$env:UV_PROJECT_ENVIRONMENT = "$HOME\.venvs\sentinel-agent"
$repo = "\\wsl.localhost\Ubuntu\home\<you>\path\to\sentinel-agent"   # your checkout
uv sync --project $repo --extra vision
uv run --project $repo sentinel webcam
```

`UV_PROJECT_ENVIRONMENT` keeps the Windows virtualenv on the Windows disk, separate from the
Linux `.venv` in the repo. Otherwise the two would overwrite each other, and a venv on a
`\\wsl.localhost` path is slow. `uv` downloads Python 3.12 for Windows by itself.

Run it from a Windows folder (`cd $HOME`) and point at the repo with `--project`. Do not `cd`
into the `\\wsl.localhost` path: Ultralytics reads `/etc/os-release` at import, which Windows
then resolves to the Linux file, a symlink it can't open (`OSError: [Errno 22]`).

On Windows, cameras are opened with DirectShow. OpenCV's default backend, Media Foundation,
took 60 s to open a Logitech C270; DirectShow opens it in 0.5 s. The first YOLO inference
(~2 s) runs before the clock starts, and the run ends with a line like
`67 frames analysed in 15.3 s (4.4 fps)`.

Events from a Windows run are saved to `sentinel.db` in the folder you ran from (`$HOME`
above). To query them over MCP from WSL, point the server at that file:
`SENTINEL_DB_PATH=/mnt/c/Users/<you>/sentinel.db uv run sentinel serve-mcp`.

## Honest limitations

- **`p_cv` is uncalibrated here** (it's marked `*` in the output). Live input has no ground
  truth, so there is nothing to fit Platt scaling on; `p_cv` is YOLO's raw box confidence.
  A real deployment would fit the calibrator on a human-reviewed history of this camera's
  true/false positives, and the result only holds while the scene stays similar.
- The aggregator is a minimal greedy tracker (time gap + center distance). Two people
  crossing each other can swap or merge events. A real tracker (e.g. ByteTrack) would fix
  that.
- `--fps` trades CPU for responsiveness. At the default 5 fps, a person must be visible for
  about 2 s to count as a "sustained track" (10 detections) in the demo heuristic.
