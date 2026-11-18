#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automated Google Colab GPU runner via `google-colab-cli`, uploading the local
`stable-diffusion.cpp` (sd-cli) binary to the Colab VM and exposing a single-thread
HTTP API for Z-Image-Turbo / Z-Image-Base GGUF models.

Key architectural highlights:
1. Direct use of prebuilt CUDA `sd-cli` binary uploaded to
   `/content/stable-diffusion.cpp/build/bin/sd-cli` on Colab VM, avoiding Google Drive mounting.
2. Lightweight runtime without heavy ComfyUI or PyTorch training stacks, optimized for T4 GPU VRAM.
3. Fast generation with Z-Image-Turbo GGUF (default Q6, 8 steps, CFG 1.0) with Flash Attention and VAE Tiling.
4. Robust job receipts (`/content/sdcpp_outputs/z_image/job_<id>.json`) and automatic reconnection
   if temporary WebSocket disconnections occur.
5. Dual endpoints: custom `/api/generate` and OpenAI-compatible `/v1/images/generations`.
"""

import argparse
import base64
import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("zimage_turbo_api")

IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------------
# Compatibility wrapper to execute `colab` natively on Windows
# (Patches missing termios, tty, fcntl, and Unix signals in google-colab-cli PyPI package)
# ---------------------------------------------------------------------------
WINDOWS_COLAB_WRAPPER_CODE = r'''
import os
import sys
import types
import signal

if os.name == "nt":
    for mod_name in ("termios", "tty", "fcntl", "pty"):
        if mod_name not in sys.modules:
            mod = types.ModuleType(mod_name)
            mod.TCSADRAIN = 1
            mod.TCSANOW = 0
            mod.TCSAFLUSH = 2
            mod.ECHO = 8
            mod.ICANON = 2
            mod.LOCK_EX = 2
            mod.LOCK_SH = 1
            mod.LOCK_NB = 4
            mod.LOCK_UN = 8
            mod.tcgetattr = lambda fd: [0, 0, 0, 0, 0, 0, [0] * 32]
            mod.tcsetattr = lambda fd, when, attrs: None
            mod.setraw = lambda fd, when=0: None
            mod.setcbreak = lambda fd, when=0: None
            mod.flock = lambda fd, op: None
            mod.ioctl = lambda fd, req, arg=0, mutate_flag=True: 0
            sys.modules[mod_name] = mod

    for sig_name in ("SIGHUP", "SIGWINCH", "SIGALRM", "SIGQUIT", "SIGPIPE"):
        if not hasattr(signal, sig_name):
            setattr(signal, sig_name, signal.SIGTERM)

try:
    from colab_cli.cli import app as colab_app
except ImportError:
    try:
        from colab_cli.main import app as colab_app
    except ImportError:
        from colab_cli import cli as colab_app

if __name__ == "__main__":
    colab_app()
'''

# ---------------------------------------------------------------------------
# Standard Aspect Ratios (all dimensions are guaranteed multiples of 32)
# ---------------------------------------------------------------------------
ASPECT_RATIOS: Dict[str, Tuple[int, int]] = {
    # 16:9 Widescreen (notebook default: 1920x1088)
    "16:9": (1920, 1088),
    "1920x1088 (16:9)": (1920, 1088),
    "1280x736 (16:9)": (1280, 736),
    "1344x768 (16:9)": (1344, 768),
    # 9:16 Portrait / Vertical
    "9:16": (1088, 1920),
    "1088x1920 (9:16)": (1088, 1920),
    "736x1280 (9:16)": (736, 1280),
    "768x1344 (9:16)": (768, 1344),
    # 1:1 Square
    "1:1": (1024, 1024),
    "1024x1024 (1:1)": (1024, 1024),
    "1280x1280 (1:1)": (1280, 1280),
    # 4:3 Standard
    "4:3": (1152, 864),
    "1152x864 (4:3)": (1152, 864),
    # 3:4 Portrait
    "3:4": (864, 1152),
    "864x1152 (3:4)": (864, 1152),
    # 3:2 Photography
    "3:2": (1248, 832),
    "1248x832 (3:2)": (1248, 832),
    # 2:3 Portrait
    "2:3": (832, 1248),
    "832x1248 (2:3)": (832, 1248),
    # 21:9 Ultrawide
    "21:9": (2016, 864),
    "2016x864 (21:9)": (2016, 864),
}


def resolve_local_sd_binary(input_path: Optional[str] = None) -> Path:
    """
    Locate the `sd-cli` binary from the provided path or automatically search
    inside the workspace directory.
    """
    candidates: List[Path] = []
    if input_path:
        p = Path(input_path).resolve()
        candidates.extend([p, p / "sd-cli"])

    workspace_root = Path(__file__).resolve().parent
    candidates.extend([
        workspace_root / "stable-diffusion.cpp" / "build" / "bin" / "sd-cli" / "sd-cli",
        workspace_root / "stable-diffusion.cpp" / "build" / "bin" / "sd-cli",
        workspace_root / "stable-diffusion.cpp" / "build" / "bin" / "sd-cli.exe",
    ])

    for c in candidates:
        if c.is_file():
            return c
        if c.is_dir() and (c / "sd-cli").is_file():
            return c / "sd-cli"

    raise FileNotFoundError(
        "Binary file 'sd-cli' not found. Searched paths:\n"
        + "\n".join(f" - {c}" for c in candidates)
    )


# ---------------------------------------------------------------------------
# Remote bootstrap code & generate() function on Google Colab VM
# Based on Z_Image_GGUF_T4_SDCPP_Colab.ipynb
# ---------------------------------------------------------------------------
REMOTE_BOOTSTRAP_CODE = r'''
import os
import sys
import time
import json
import uuid
import shutil
import random
import pathlib
import subprocess
from datetime import datetime

ROOT = pathlib.Path("/content")
MODEL_SLUG = "z_image"
MODELS_DIR = ROOT / "sdcpp_models" / MODEL_SLUG
OUTPUT_DIR = ROOT / "sdcpp_outputs" / MODEL_SLUG
BUILD_DIR = ROOT / "stable-diffusion.cpp" / "build"
BIN_DIR = BUILD_DIR / "bin"
SD_BIN = BIN_DIR / "sd-cli"

for d in (MODELS_DIR, OUTPUT_DIR, BIN_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 1. Check GPU environment
try:
    import torch
    assert torch.cuda.is_available(), "Google Colab GPU runtime (T4/L4/A100) required."
    gpu_name = torch.cuda.get_device_name(0)
    vram_gib = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    print(f"[Colab-Bootstrap] GPU: {gpu_name} | VRAM: {vram_gib:.1f} GiB", flush=True)
except Exception as e:
    print(f"[Colab-Bootstrap] GPU check warning: {e}", flush=True)

# 2. Install lightweight Python dependencies (NO ComfyUI / Diffusers)
print("[Colab-Bootstrap] Installing lightweight dependencies: huggingface_hub, Pillow, nvidia-ml-py...", flush=True)
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "huggingface_hub>=0.34,<2", "Pillow", "nvidia-ml-py"],
    check=True,
)
from huggingface_hub import hf_hub_download

# 3. Verify uploaded sd-cli binary
if not SD_BIN.is_file():
    raise FileNotFoundError(
        f"sd-cli binary not found at {SD_BIN}. "
        "Please ensure the binary upload step completed successfully."
    )

SD_BIN.chmod(SD_BIN.stat().st_mode | 0o755)
EXEC_ENV = os.environ.copy()
EXEC_ENV["LD_LIBRARY_PATH"] = f"{BIN_DIR}:{EXEC_ENV.get('LD_LIBRARY_PATH', '')}"

chk = subprocess.run(
    [str(SD_BIN), "--version"],
    env=EXEC_ENV,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
print(f"[Colab-Bootstrap] sd-cli version check (exit {chk.returncode}):\n{chk.stdout.strip()[:500]}", flush=True)
if chk.returncode != 0:
    raise RuntimeError(f"sd-cli binary failed to execute: {chk.stdout}")

# 4. Model configuration
TURBO_FILES = {
    "Q4": "z_image_turbo-Q4_K.gguf",
    "Q5": "z_image_turbo-Q5_0.gguf",
    "Q6": "z_image_turbo-Q6_K.gguf",
    "Q8": "z_image_turbo-Q8_0.gguf",
}
BASE_FILES = {
    "Q4": "z_image-Q4_0.gguf",
    "Q8": "z_image-Q8_0.gguf",
}
ENCODER_OPTIONS = {
    "Q4_K_M": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    "Q5_K_M": "Qwen3-4B-Instruct-2507-Q5_K_M.gguf",
    "Q6_K": "Qwen3-4B-Instruct-2507-Q6_K.gguf",
}

def get_model(label: str, repo: str, filename: str) -> pathlib.Path:
    local_target = MODELS_DIR / filename
    if local_target.exists():
        print(f"[Colab-Bootstrap] ✅ {label} already cached: {filename} ({local_target.stat().st_size / 1e9:.2f} GB)", flush=True)
        return local_target
    print(f"[Colab-Bootstrap] 📥 Downloading {label}: {repo}/{filename}...", flush=True)
    p = pathlib.Path(hf_hub_download(repo_id=repo, filename=filename, local_dir=str(MODELS_DIR)))
    print(f"[Colab-Bootstrap] ✅ Successfully downloaded {p.name} ({p.stat().st_size / 1e9:.2f} GB)", flush=True)
    return p

# Preload default weights for Z-Image Turbo (Q6 DiT + Q4_K_M Text Encoder + FLUX VAE)
print("[Colab-Bootstrap] Preloading default weights for Z-Image Turbo...", flush=True)
MODEL_PATHS = {
    "dit": get_model("DiT (Turbo Q6)", "leejet/Z-Image-Turbo-GGUF", "z_image_turbo-Q6_K.gguf"),
    "encoder": get_model("Text Encoder (Qwen3-4B)", "unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
    "vae": get_model("VAE (FLUX ae)", "Comfy-Org/Z-Image-Turbo", "split_files/vae/ae.safetensors"),
}

# 5. Image generation via sd-cli
def generate(input_payload: dict):
    values = input_payload["input"]
    positive_prompt = values.get("positive_prompt") or values.get("prompt") or ""
    negative_prompt = values.get("negative_prompt", "")
    seed = int(values.get("seed", 0))
    if seed == 0:
        seed = random.randint(1, 2147483647)

    variant = values.get("variant", "Turbo")
    is_turbo = (str(variant).lower() == "turbo")
    quant = values.get("quant", "Q6")
    encoder_quant = values.get("encoder_quant", "Q4_K_M")

    # Determine default steps and CFG by variant
    default_steps = 8 if is_turbo else 30
    default_cfg = 1.0 if is_turbo else 5.0
    steps = int(values.get("steps") or default_steps)
    cfg = float(values.get("cfg") or default_cfg)

    width = int(values.get("width", 1920))
    height = int(values.get("height", 1088))
    width = max(32, (width // 32) * 32)
    height = max(32, (height // 32) * 32)

    sampler_name = values.get("sampler_name", "euler")
    use_fa = bool(values.get("use_flash_attention", True))
    use_tiling = bool(values.get("use_vae_tiling", True))
    max_vram_gb = int(values.get("max_vram_gb", 12))

    # Select model weights
    if is_turbo:
        dit_file = TURBO_FILES.get(quant, "z_image_turbo-Q6_K.gguf")
        dit_repo = "leejet/Z-Image-Turbo-GGUF"
    else:
        dit_file = BASE_FILES.get(quant, "z_image-Q4_0.gguf")
        dit_repo = "leejet/Z-Image-GGUF"
    enc_file = ENCODER_OPTIONS.get(encoder_quant, "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")

    dit_path = get_model(f"DiT ({variant} {quant})", dit_repo, dit_file)
    encoder_path = get_model(f"Encoder ({encoder_quant})", "unsloth/Qwen3-4B-Instruct-2507-GGUF", enc_file)
    vae_path = MODEL_PATHS["vae"]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"z_image_{variant.lower()}_{width}x{height}_s{steps}_seed{seed}_{stamp}_{uuid.uuid4().hex[:6]}"
    image_path = OUTPUT_DIR / f"{run_id}.png"
    log_path = OUTPUT_DIR / f"{run_id}.log"

    cmd = [
        str(SD_BIN),
        "--diffusion-model", str(dit_path),
        "--llm", str(encoder_path),
        "--vae", str(vae_path),
        "-p", positive_prompt,
        "-W", str(width), "-H", str(height),
        "--seed", str(seed), "--rng", "cpu",
        "--steps", str(steps), "--cfg-scale", str(cfg),
        "--sampling-method", sampler_name,
        "--auto-fit", "on", "--max-vram", str(max_vram_gb),
        "-o", str(image_path),
    ]
    if negative_prompt and negative_prompt.strip():
        cmd.extend(["-n", negative_prompt.strip()])
    if use_fa:
        cmd.append("--diffusion-fa")
    if use_tiling:
        cmd.append("--vae-tiling")

    print(f"[Z-Image-Colab] Starting generation: {width}x{height}, {steps} steps, CFG {cfg}, seed={seed}", flush=True)
    t0 = time.monotonic()
    with log_path.open("w", encoding="utf-8") as logfile:
        proc = subprocess.Popen(
            cmd,
            env=EXEC_ENV,
            cwd=str(BUILD_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        for line in proc.stdout:
            print(line, end="", flush=True)
            logfile.write(line)
        ret = proc.wait()

    elapsed = time.monotonic() - t0
    if ret != 0 or not image_path.is_file():
        raise RuntimeError(f"sd-cli failed with exit code {ret}. See detailed log at: {log_path}")

    print(f"[Z-Image-Colab] ✅ Completed in {elapsed:.2f}s! Output: {image_path}", flush=True)
    return str(image_path), seed, elapsed

print("__ZIMAGE_COLAB_READY__", flush=True)
'''


# ---------------------------------------------------------------------------
# Google Colab session runner via `google-colab-cli`
# ---------------------------------------------------------------------------
class ColabSingleThreadRunner:
    """
    Manages Google Colab sessions using `google-colab-cli`,
    uploads the prebuilt `sd-cli` binary to Colab VM, and coordinates
    single-threaded image generation tasks using a mutex lock.
    """

    def __init__(
        self,
        session_name: str = "zimage-turbo",
        gpu_type: str = "T4",
        high_mem: bool = False,
        sd_binary_path: Optional[str] = None,
        notebook_path: Optional[str] = None,
        output_dir: str = "./outputs",
        keep_alive_on_exit: bool = False,
        use_wsl: bool = False,
        assign_retries: int = 3,
        assign_retry_delay: int = 20,
    ):
        self.session_name = session_name
        self.gpu_type = gpu_type
        self.high_mem = high_mem
        self.sd_binary_path = sd_binary_path
        self.notebook_path = notebook_path
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.keep_alive_on_exit = keep_alive_on_exit
        self.use_wsl = use_wsl
        self.assign_retries = assign_retries
        self.assign_retry_delay = assign_retry_delay

        # Synchronization lock ensuring strict single-thread execution on Colab kernel
        self._lock = threading.Lock()
        self._is_ready = False
        self._last_error: Optional[str] = None
        self._cli_prefix: List[str] = ["colab"]
        self._win_shim_path: Optional[Path] = None

    @staticmethod
    def _win_to_wsl_path(win_path: str) -> str:
        """Convert Windows path (C:\\Users\\...) to WSL path (/mnt/c/Users/...)."""
        p = Path(win_path).resolve()
        drive = p.drive.rstrip(":").lower()
        rest = p.as_posix().split(":", 1)[-1].lstrip("/")
        return f"/mnt/{drive}/{rest}"

    def _prepare_cli_command(self) -> None:
        """
        Automatically detect the appropriate method to run `colab` on Linux/macOS/Windows.
        """
        if IS_WINDOWS and self.use_wsl:
            if shutil.which("wsl") is None:
                raise RuntimeError("You specified --use-wsl, but WSL is not installed on this system.")
            self._cli_prefix = ["wsl", "colab"]
            logger.info("Using WSL2 mode on Windows: 'wsl colab'")
            return

        # 1. Highest priority: colab in local .venv of this project
        bin_subdir = "Scripts" if IS_WINDOWS else "bin"
        colab_bin = "colab.exe" if IS_WINDOWS else "colab"

        local_venv_colab = Path(__file__).resolve().parent / ".venv" / bin_subdir / colab_bin
        if local_venv_colab.is_file():
            test_proc = subprocess.run(
                [str(local_venv_colab), "version"],
                text=True,
                capture_output=True,
            )
            if test_proc.returncode == 0:
                self._cli_prefix = [str(local_venv_colab)]
                logger.info("Using local .venv colab: %s", local_venv_colab)
                return

        # 2. Check colab in current active environment Scripts/bin
        venv_colab = Path(sys.prefix) / bin_subdir / colab_bin
        if venv_colab.is_file():
            test_proc = subprocess.run(
                [str(venv_colab), "version"],
                text=True,
                capture_output=True,
            )
            if test_proc.returncode == 0:
                self._cli_prefix = [str(venv_colab)]
                logger.info("Using active environment colab: %s", venv_colab)
                return

        if shutil.which("colab") is not None:
            if not IS_WINDOWS:
                self._cli_prefix = ["colab"]
                return

            test_proc = subprocess.run(
                ["colab", "version"],
                text=True,
                capture_output=True,
            )
            if test_proc.returncode == 0:
                self._cli_prefix = ["colab"]
                logger.info("Using system 'colab' command directly on Windows Native.")
                return

            if any(m in test_proc.stderr for m in ("termios", "tty", "fcntl")):
                logger.info(
                    "Detected missing Unix modules on Windows PyPI. "
                    "Activating automatic Windows Compatibility Shim..."
                )
                shim_file = Path(tempfile.gettempdir()) / "colab_windows_shim.py"
                shim_file.write_text(WINDOWS_COLAB_WRAPPER_CODE, encoding="utf-8")
                self._win_shim_path = shim_file
                self._cli_prefix = [sys.executable, str(shim_file)]
                return

        raise RuntimeError(
            "Command 'colab' not found. Please verify your virtual environment or install google-colab-cli:\n"
            "  pip install google-colab-cli"
        )

    def _ensure_authenticated_interactive(self) -> None:
        """
        Verify Google Colab OAuth2 authentication.
        """
        cmd = self._cli_prefix + ["--auth", "oauth2", "sessions"]
        logger.info("Checking Google Colab CLI authentication (%s)...", " ".join(cmd))
        env = os.environ.copy()
        env["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        proc = subprocess.run(cmd, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Google Colab CLI authentication failed (exit code {proc.returncode}). "
                "Please run: colab --auth oauth2 sessions"
            )

    def _run_cli(
        self,
        args: list,
        input_text: Optional[str] = None,
        timeout: int = 1800,
        stream_output: bool = False,
    ) -> str:
        """
        Execute `colab ...` command and return complete stdout.
        Supports real-time console streaming if stream_output=True.
        """
        cmd = self._cli_prefix + ["--auth", "oauth2"] + args
        logger.info("Executing CLI: %s", " ".join(cmd[:6]) + ("..." if len(cmd) > 6 else ""))

        env = os.environ.copy()
        env["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        if stream_output:
            collected_lines: List[str] = []
            with subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if input_text is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            ) as proc:
                if input_text is not None and proc.stdin is not None:
                    try:
                        proc.stdin.write(input_text)
                        proc.stdin.close()
                    except Exception as exc:
                        logger.warning("Error writing stdin: %s", exc)

                assert proc.stdout is not None
                for line in proc.stdout:
                    try:
                        sys.stdout.write(line)
                    except UnicodeEncodeError:
                        sys.stdout.write(
                            line.encode(sys.stdout.encoding or "utf-8", errors="backslashreplace").decode(
                                sys.stdout.encoding or "utf-8"
                            )
                        )
                    sys.stdout.flush()
                    collected_lines.append(line)

                proc.wait(timeout=timeout)
                full_out = "".join(collected_lines)
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Command {' '.join(cmd[:4])}... failed (exit code {proc.returncode}):\n{full_out}"
                    )
                return full_out

        proc = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command {' '.join(cmd[:4])}... failed (exit code {proc.returncode}):\n"
                f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
            )
        return proc.stdout

    def _ensure_binary_uploaded(self) -> None:
        """
        Upload `sd-cli` binary to /content/stable-diffusion.cpp/build/bin/sd-cli
        on Colab VM instead of mounting Google Drive.
        """
        local_bin = resolve_local_sd_binary(self.sd_binary_path)
        local_size = local_bin.stat().st_size
        logger.info("Local sd-cli binary: %s (%.2f MB)", local_bin, local_size / 1e6)

        # 1. Create necessary remote directories on Colab VM
        create_dirs_script = (
            "import pathlib\n"
            "for p in [\n"
            "    '/content/stable-diffusion.cpp/build/bin',\n"
            "    '/content/sdcpp_models/z_image',\n"
            "    '/content/sdcpp_outputs/z_image',\n"
            "]:\n"
            "    pathlib.Path(p).mkdir(parents=True, exist_ok=True)\n"
            "print('__DIRS_READY__', flush=True)\n"
        )
        self._run_cli(
            ["exec", "--timeout", "60", "-s", self.session_name],
            input_text=create_dirs_script,
            timeout=90,
        )

        # 2. Check if binary already exists on Colab with identical size
        check_binary_script = (
            "import pathlib\n"
            "p = pathlib.Path('/content/stable-diffusion.cpp/build/bin/sd-cli')\n"
            "print(f'__REMOTE_SIZE__:{p.stat().st_size if p.is_file() else -1}', flush=True)\n"
        )
        check_out = self._run_cli(
            ["exec", "--timeout", "60", "-s", self.session_name],
            input_text=check_binary_script,
            timeout=90,
        )
        remote_size = -1
        match = re.search(r"__REMOTE_SIZE__:(-?\d+)", check_out)
        if match:
            remote_size = int(match.group(1))

        if remote_size == local_size:
            logger.info("Binary sd-cli already exists on Colab with matching size (%d bytes). Skipping upload.", local_size)
            self._run_cli(
                ["exec", "--timeout", "60", "-s", self.session_name],
                input_text=(
                    "import pathlib, os\n"
                    "p = pathlib.Path('/content/stable-diffusion.cpp/build/bin/sd-cli')\n"
                    "p.chmod(p.stat().st_mode | 0o755)\n"
                ),
                timeout=90,
            )
            return

        # 3. Temporarily gzip compress binary for faster transfer and HTTP payload compliance
        logger.info("Gzip compressing sd-cli binary to optimize Colab upload speed...")
        with tempfile.NamedTemporaryFile("wb", suffix=".gz", delete=False) as tmp_gz:
            tmp_gz_path = Path(tmp_gz.name)

        try:
            with open(local_bin, "rb") as f_in, gzip.open(tmp_gz_path, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)

            gz_size = tmp_gz_path.stat().st_size
            logger.info(
                "Compressed size: %.2f MB (original: %.2f MB). Uploading to Colab...",
                gz_size / 1e6,
                local_size / 1e6,
            )

            upload_target = (
                self._win_to_wsl_path(str(tmp_gz_path))
                if (IS_WINDOWS and self.use_wsl)
                else str(tmp_gz_path)
            )

            self._run_cli(
                ["upload", "-s", self.session_name, upload_target, "/content/stable-diffusion.cpp/build/bin/sd-cli.gz"],
                timeout=600,
            )

            # Unpack on Colab
            unpack_script = (
                "import gzip, shutil, pathlib\n"
                "gz_p = pathlib.Path('/content/stable-diffusion.cpp/build/bin/sd-cli.gz')\n"
                "bin_p = pathlib.Path('/content/stable-diffusion.cpp/build/bin/sd-cli')\n"
                "if gz_p.exists():\n"
                "    with gzip.open(gz_p, 'rb') as f_in, open(bin_p, 'wb') as f_out:\n"
                "        shutil.copyfileobj(f_in, f_out)\n"
                "    gz_p.unlink(missing_ok=True)\n"
                "bin_p.chmod(bin_p.stat().st_mode | 0o755)\n"
                "print(f'__UNPACK_SIZE__:{bin_p.stat().st_size}', flush=True)\n"
            )
            unpack_out = self._run_cli(
                ["exec", "--timeout", "120", "-s", self.session_name],
                input_text=unpack_script,
                timeout=180,
            )
            match_unpack = re.search(r"__UNPACK_SIZE__:(\d+)", unpack_out)
            if not match_unpack or int(match_unpack.group(1)) != local_size:
                raise RuntimeError(f"Unpacking sd-cli failed on Colab. Output received: {unpack_out}")

            logger.info("Successfully uploaded and unpacked sd-cli (%d bytes)!", local_size)
        finally:
            tmp_gz_path.unlink(missing_ok=True)

    def _run_bootstrap_script(self) -> None:
        """Push and execute REMOTE_BOOTSTRAP_CODE on Colab VM."""
        with tempfile.NamedTemporaryFile("w", suffix="_bootstrap.py", delete=False, encoding="utf-8") as tmp:
            tmp.write(REMOTE_BOOTSTRAP_CODE)
            bootstrap_file = tmp.name

        try:
            boot_arg = (
                self._win_to_wsl_path(bootstrap_file)
                if (IS_WINDOWS and self.use_wsl)
                else bootstrap_file
            )
            out = self._run_cli(
                ["exec", "--timeout", "1800", "-s", self.session_name, "-f", boot_arg],
                timeout=3600,
                stream_output=True,
            )
            if "__ZIMAGE_COLAB_READY__" not in out:
                logger.warning("Bootstrap output does not contain expected ready flag. Check logs:\n%s", out)
        finally:
            Path(bootstrap_file).unlink(missing_ok=True)

    def start_and_bootstrap(self) -> None:
        """
        Initialize GPU runtime on Google Colab, upload sd-cli binary,
        and preload Z-Image-Turbo GGUF model weights.
        """
        with self._lock:
            if self._is_ready:
                return

            self._prepare_cli_command()
            self._ensure_authenticated_interactive()

            # 1. Check existing session or create new one
            sessions_out = self._run_cli(["sessions"], timeout=90)
            if self.session_name not in sessions_out:
                logger.info(
                    "Initializing new Colab runtime (session=%s, gpu=%s)...",
                    self.session_name,
                    self.gpu_type,
                )
                new_cmd = ["new", "-s", self.session_name, "--gpu", self.gpu_type]
                if self.high_mem:
                    new_cmd.append("--high-mem")

                allocated = False
                last_err = None
                for attempt in range(1, self.assign_retries + 1):
                    try:
                        self._run_cli(new_cmd, timeout=300, stream_output=True)
                        allocated = True
                        break
                    except Exception as exc:
                        last_err = exc
                        err_str = str(exc)
                        if "Service Unavailable" in err_str or "503" in err_str:
                            logger.warning(
                                "[Colab 503] Colab %s GPU cluster is busy/unavailable (attempt %d/%d). Waiting %ds...",
                                self.gpu_type,
                                attempt,
                                self.assign_retries,
                                self.assign_retry_delay,
                            )
                            if attempt < self.assign_retries:
                                time.sleep(self.assign_retry_delay)
                        elif "412" in err_str or "TooManyAssignmentsError" in err_str:
                            logger.error(
                                "[Colab 412] Assignment limit reached or free GPU quota exhausted."
                            )
                            raise
                        else:
                            raise

                if not allocated and last_err:
                    self._last_error = str(last_err)
                    raise last_err
            else:
                logger.info("Reusing existing Colab session: %s", self.session_name)

            # 2. If user specified custom notebook, execute it first
            if self.notebook_path:
                nb_path = Path(self.notebook_path).resolve()
                if not nb_path.exists():
                    raise FileNotFoundError(f"Notebook file not found: {nb_path}")
                nb_arg = self._win_to_wsl_path(str(nb_path)) if (IS_WINDOWS and self.use_wsl) else str(nb_path)
                logger.info("Executing Colab Notebook: %s", nb_arg)
                self._run_cli(
                    ["exec", "--timeout", "1800", "-s", self.session_name, "-f", nb_arg],
                    timeout=3600,
                    stream_output=True,
                )

            # 3. Upload sd-cli binary to Colab VM
            logger.info("Verifying and uploading sd-cli binary to Colab VM...")
            self._ensure_binary_uploaded()

            # 4. Install dependencies and preload Z-Image-Turbo weights
            logger.info("Bootstrapping Z-Image-Turbo (stable-diffusion.cpp) on Colab VM...")
            self._run_bootstrap_script()

            self._is_ready = True
            logger.info("Colab session '%s' is ready to serve single-thread API requests!", self.session_name)

    def _poll_job_receipt(self, receipt_path: str, max_wait_sec: int = 180) -> Optional[dict]:
        """
        Recover task result if `colab exec` WebSocket drops temporarily.
        """
        logger.info("Checking task status on Colab VM (%s)...", receipt_path)
        check_code = (
            "import json, os\n"
            f"p = {repr(receipt_path)}\n"
            "if os.path.exists(p):\n"
            "    print('__RECEIPT__:' + open(p, encoding='utf-8').read(), flush=True)\n"
            "elif 'generate' not in globals():\n"
            "    print('__KERNEL_RESET__', flush=True)\n"
            "else:\n"
            "    print('__STILL_RUNNING__', flush=True)\n"
        )

        deadline = time.time() + max_wait_sec
        while time.time() < deadline:
            time.sleep(5)
            try:
                out = self._run_cli(
                    ["exec", "--timeout", "30", "-s", self.session_name],
                    input_text=check_code,
                    timeout=45,
                )
            except Exception as poll_exc:
                logger.warning("Polling retry after temporary connection error: %s", poll_exc)
                continue

            if "__RECEIPT__:" in out:
                raw_json = out.split("__RECEIPT__:", 1)[1].strip().splitlines()[0]
                return json.loads(raw_json)
            if "__KERNEL_RESET__" in out:
                logger.warning("Detected Colab Kernel restart. Re-bootstrapping environment...")
                self._run_bootstrap_script()
                return None
        return None

    def generate_image(self, params: dict) -> dict:
        """
        Send generation request to `generate()` on Colab and download output to local outputs directory.
        Protected by self._lock to ensure single-thread sequential execution.
        """
        with self._lock:
            if not self._is_ready:
                logger.info("Colab runtime not ready, attempting initialization/reconnection...")
                self.start_and_bootstrap()
                if not self._is_ready:
                    raise RuntimeError(f"Colab runtime not ready: {self._last_error or 'GPU not allocated'}")

            job_id = uuid.uuid4().hex[:10]
            receipt_path = f"/content/sdcpp_outputs/z_image/job_{job_id}.json"
            payload_json = json.dumps({"input": params}, ensure_ascii=False)

            remote_snippet = (
                "import json\n"
                "if 'generate' not in globals():\n"
                "    raise RuntimeError('__KERNEL_NEEDS_BOOTSTRAP__')\n"
                f"_req = json.loads({repr(payload_json)})\n"
                "_img_path, _seed, _elapsed = generate(_req)\n"
                "_meta = {'remote_path': _img_path, 'seed': _seed, 'elapsed': _elapsed}\n"
                f"with open({repr(receipt_path)}, 'w', encoding='utf-8') as _f:\n"
                "    json.dump(_meta, _f)\n"
                "print('__RESULT_JSON__:' + json.dumps(_meta), flush=True)\n"
            )

            result_meta: Optional[dict] = None
            try:
                stdout = self._run_cli(
                    ["exec", "--timeout", "1800", "-s", self.session_name],
                    input_text=remote_snippet,
                    timeout=1860,
                    stream_output=True,
                )
                match = re.search(r"__RESULT_JSON__:(\{.*\})", stdout)
                if match:
                    result_meta = json.loads(match.group(1))
            except RuntimeError as exc:
                err_text = str(exc)
                if "__KERNEL_NEEDS_BOOTSTRAP__" in err_text:
                    logger.warning("Kernel restarted, reloading Z-Image environment and retrying...")
                    self._run_bootstrap_script()
                    stdout = self._run_cli(
                        ["exec", "--timeout", "1800", "-s", self.session_name],
                        input_text=remote_snippet,
                        timeout=1860,
                        stream_output=True,
                    )
                    match = re.search(r"__RESULT_JSON__:(\{.*\})", stdout)
                    if match:
                        result_meta = json.loads(match.group(1))
                elif "Connection was lost" in err_text:
                    logger.warning(
                        "colab-cli WebSocket connection dropped temporarily while GPU is busy. "
                        "Waiting for result receipt from %s...",
                        receipt_path,
                    )
                    result_meta = self._poll_job_receipt(receipt_path, max_wait_sec=180)
                else:
                    raise

            if not result_meta:
                raise RuntimeError("No image output received from Colab VM.")

            remote_path = result_meta["remote_path"]
            used_seed = result_meta["seed"]
            elapsed_sec = result_meta.get("elapsed", 0.0)

            local_filename = Path(remote_path).name
            local_path = self.output_dir / local_filename
            download_target = (
                self._win_to_wsl_path(str(local_path))
                if (IS_WINDOWS and self.use_wsl)
                else str(local_path)
            )

            self._run_cli(
                ["download", "-s", self.session_name, remote_path, download_target],
                timeout=180,
            )

            return {
                "local_path": str(local_path),
                "remote_path": remote_path,
                "seed": used_seed,
                "elapsed": elapsed_sec,
            }

    def stop(self) -> None:
        """Stop Colab session upon API server shutdown if --keep-session flag is not set."""
        with self._lock:
            if not self._is_ready or self.keep_alive_on_exit:
                return
            try:
                logger.info("Stopping Colab session '%s'...", self.session_name)
                self._run_cli(["stop", "-s", self.session_name], timeout=60)
            except Exception as exc:
                logger.warning("Failed to stop Colab session automatically: %s", exc)
            finally:
                self._is_ready = False


# ---------------------------------------------------------------------------
# Schema definitions for HTTP API (Z-Image Turbo & OpenAI Compatibility)
# ---------------------------------------------------------------------------
class ZImageGenerateRequest(BaseModel):
    positive_prompt: Optional[str] = Field(
        default=None,
        description="Detailed positive description of the image to generate.",
    )
    prompt: Optional[str] = Field(
        default=None,
        description="Alias equivalent to positive_prompt.",
    )
    negative_prompt: str = Field(
        default="",
        description="Elements or attributes to exclude from the generated image.",
    )
    aspect_ratio: Optional[str] = Field(
        default="1920x1088 (16:9)",
        description="Aspect ratio preset: '1920x1088 (16:9)', '1024x1024 (1:1)', '1088x1920 (9:16)', etc.",
    )
    width: Optional[int] = Field(
        default=None,
        description="Direct width in pixels (overrides aspect_ratio, must be divisible by 32).",
    )
    height: Optional[int] = Field(
        default=None,
        description="Direct height in pixels (overrides aspect_ratio, must be divisible by 32).",
    )
    seed: int = Field(default=0, description="Random seed (0 = auto-generate random seed).")
    steps: int = Field(default=8, ge=1, le=100, description="Number of sampling steps (default 8 for Z-Image-Turbo).")
    cfg: float = Field(default=1.0, ge=1.0, le=20.0, description="CFG scale (default 1.0 for Z-Image-Turbo).")
    sampler_name: str = Field(default="euler", description="Sampling algorithm (default: euler).")
    variant: Literal["Turbo", "Base"] = Field(default="Turbo", description="Model variant: 'Turbo' or 'Base'.")
    quant: str = Field(default="Q6", description="DiT quantization: Q4, Q5, Q6, Q8 (default: Q6).")
    encoder_quant: str = Field(default="Q4_K_M", description="Text Encoder quantization: Q4_K_M, Q5_K_M, Q6_K.")
    use_flash_attention: bool = Field(default=True, description="Enable Flash Attention to accelerate computation.")
    use_vae_tiling: bool = Field(default=True, description="Enable VAE Tiling for smooth high-resolution decoding.")
    max_vram_gb: int = Field(default=12, ge=6, le=16, description="Max VRAM allocation limit (GB) on Colab T4.")
    response_format: Literal["json", "b64_json", "image"] = Field(
        default="json",
        description="Response format: 'json' (metadata + path), 'b64_json' (with base64 data), or 'image' (PNG file stream).",
    )


class OpenAIImageCompatRequest(BaseModel):
    """Schema compatible with standard OpenAI Image Generation API (`/v1/images/generations`)."""

    model: str = Field(default="z-image-turbo", description="Model name identifier.")
    prompt: str = Field(..., description="Prompt describing the image to generate.")
    negative_prompt: str = Field(default="")
    size: str = Field(default="1920x1088", description="Image dimensions as WxH (e.g., '1920x1088', '1024x1024').")
    steps: int = Field(default=8)
    cfg: float = Field(default=1.0)
    seed: int = Field(default=0)
    response_format: Literal["b64_json", "url"] = Field(default="b64_json")


# ---------------------------------------------------------------------------
# FastAPI single-thread application setup
# ---------------------------------------------------------------------------
RUNNER: Optional[ColabSingleThreadRunner] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if RUNNER is not None:
        try:
            RUNNER.start_and_bootstrap()
        except Exception as exc:
            logger.error("Could not initialize Colab GPU session during server startup: %s", exc)
            logger.warning(
                "API Server continues running at http://127.0.0.1:2504 (Standby Mode). "
                "Check GET /health or send POST /api/bootstrap to retry connection."
            )
    yield
    if RUNNER is not None:
        RUNNER.stop()


app = FastAPI(
    title="Z-Image-Turbo Colab Single-Thread API",
    description=(
        "Single-thread API automatically driving Google Colab GPU via google-colab-cli "
        "to run Z-Image-Turbo GGUF using stable-diffusion.cpp."
    ),
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_dimensions(aspect_ratio: Optional[str], width: Optional[int], height: Optional[int]) -> Tuple[int, int]:
    w, h = 1920, 1088
    if width is not None and height is not None:
        w, h = width, height
    elif aspect_ratio and aspect_ratio in ASPECT_RATIOS:
        w, h = ASPECT_RATIOS[aspect_ratio]
    elif aspect_ratio and "x" in aspect_ratio:
        raw = aspect_ratio.split("(")[0].strip().split("x")
        w, h = int(raw[0]), int(raw[1])

    # Ensure dimensions are divisible by 32 as required by stable-diffusion.cpp
    w = max(32, (w // 32) * 32)
    h = max(32, (h // 32) * 32)
    return w, h


@app.get("/health")
def health_check():
    """Check connection and GPU status of the Google Colab session."""
    is_ready = RUNNER._is_ready if RUNNER else False
    status_label = "ready" if is_ready else ("waiting_for_gpu" if (RUNNER and RUNNER._last_error) else "initializing")

    data = {
        "status": status_label,
        "backend": "stable-diffusion.cpp",
        "model": "Z-Image-Turbo",
        "session_name": RUNNER.session_name if RUNNER else None,
        "gpu_type": RUNNER.gpu_type if RUNNER else None,
        "platform": "windows" if IS_WINDOWS else sys.platform,
        "use_wsl": RUNNER.use_wsl if RUNNER else False,
        "single_thread_locked": RUNNER._lock.locked() if RUNNER else False,
    }
    if not is_ready and RUNNER and RUNNER._last_error:
        data["last_error"] = RUNNER._last_error
        data["notice"] = (
            "Google Colab returned HTTP 503 (GPU cluster temporarily congested or free quota limit reached). "
            "Server is ready. Send POST /api/bootstrap to retry connection."
        )
    return data


@app.post("/api/bootstrap")
def api_trigger_bootstrap():
    """Manually trigger reconnection or initialization of the Google Colab session."""
    if RUNNER is None:
        raise HTTPException(status_code=500, detail="Runner has not been initialized.")
    try:
        RUNNER.start_and_bootstrap()
        return {
            "status": "ready" if RUNNER._is_ready else "waiting_for_gpu",
            "message": "Successfully connected and initialized!" if RUNNER._is_ready else "Still waiting for GPU from Colab.",
            "session_name": RUNNER.session_name,
            "gpu_type": RUNNER.gpu_type,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Colab has not assigned GPU yet (503 Service Unavailable): {exc}"
        ) from exc


@app.post("/api/generate")
def api_generate_zimage(req: ZImageGenerateRequest):
    """
    Primary endpoint to generate images with Z-Image-Turbo / Base using stable-diffusion.cpp.
    Uses synchronous def + internal mutex lock for strict single-thread execution.
    """
    if RUNNER is None:
        raise HTTPException(status_code=500, detail="Runner has not been initialized.")

    final_prompt = req.positive_prompt or req.prompt
    if not final_prompt or not final_prompt.strip():
        raise HTTPException(status_code=400, detail="Please provide prompt or positive_prompt.")

    width, height = _resolve_dimensions(req.aspect_ratio, req.width, req.height)
    payload = {
        "positive_prompt": final_prompt,
        "negative_prompt": req.negative_prompt,
        "width": width,
        "height": height,
        "seed": req.seed,
        "steps": req.steps,
        "cfg": req.cfg,
        "sampler_name": req.sampler_name,
        "variant": req.variant,
        "quant": req.quant,
        "encoder_quant": req.encoder_quant,
        "use_flash_attention": req.use_flash_attention,
        "use_vae_tiling": req.use_vae_tiling,
        "max_vram_gb": req.max_vram_gb,
    }

    try:
        result = RUNNER.generate_image(payload)
    except Exception as exc:
        logger.exception("Error during image generation on Colab:")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    local_path = Path(result["local_path"])

    if req.response_format == "image":
        return FileResponse(
            path=str(local_path),
            media_type="image/png",
            filename=local_path.name,
            headers={"X-Seed": str(result["seed"])},
        )

    response_data = {
        "status": "success",
        "backend": "stable-diffusion.cpp",
        "model": f"Z-Image-{req.variant}",
        "quant": req.quant,
        "seed": result["seed"],
        "width": width,
        "height": height,
        "steps": req.steps,
        "cfg": req.cfg,
        "elapsed_seconds": round(result.get("elapsed", 0.0), 2),
        "local_path": str(local_path),
        "remote_path": result["remote_path"],
    }

    if req.response_format == "b64_json":
        response_data["b64_json"] = base64.b64encode(local_path.read_bytes()).decode("utf-8")

    return JSONResponse(content=response_data)


@app.post("/v1/images/generations")
def openai_compatible_generations(req: OpenAIImageCompatRequest):
    """
    Endpoint compatible with standard OpenAI Image Generation API.
    """
    if RUNNER is None:
        raise HTTPException(status_code=500, detail="Runner has not been initialized.")

    width, height = _resolve_dimensions(req.size, None, None)
    payload = {
        "positive_prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "width": width,
        "height": height,
        "seed": req.seed,
        "steps": req.steps,
        "cfg": req.cfg,
        "sampler_name": "euler",
        "variant": "Turbo",
        "quant": "Q6",
        "encoder_quant": "Q4_K_M",
        "use_flash_attention": True,
        "use_vae_tiling": True,
        "max_vram_gb": 12,
    }

    try:
        result = RUNNER.generate_image(payload)
    except Exception as exc:
        logger.exception("Error during image generation on Colab:")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    local_path = Path(result["local_path"])
    b64_data = base64.b64encode(local_path.read_bytes()).decode("utf-8")

    return {
        "created": int(time.time()),
        "model": req.model,
        "seed": result["seed"],
        "data": [
            {
                "b64_json": b64_data if req.response_format == "b64_json" else None,
                "local_path": str(local_path),
                "revised_prompt": req.prompt,
            }
        ],
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Automatically launch Google Colab via google-colab-cli and serve single-thread API for Z-Image-Turbo (stable-diffusion.cpp)."
    )
    parser.add_argument(
        "--session",
        default="zimage-turbo",
        help="Session name in google-colab-cli (default: zimage-turbo).",
    )
    parser.add_argument(
        "--gpu",
        default="T4",
        choices=["T4", "L4", "G4", "A100", "H100"],
        help="GPU type to allocate on Google Colab (default: T4).",
    )
    parser.add_argument(
        "--high-mem",
        action="store_true",
        help="Request high-memory instance (--high-mem) if account has Colab Pro.",
    )
    parser.add_argument(
        "--sd-binary",
        default="stable-diffusion.cpp/build/bin/sd-cli",
        help="Path to prebuilt local sd-cli binary or its directory (default: stable-diffusion.cpp/build/bin/sd-cli).",
    )
    parser.add_argument(
        "--notebook",
        default=None,
        help="Path to custom .ipynb file to run during startup (optional).",
    )
    parser.add_argument(
        "--output-dir",
        default="./outputs",
        help="Local directory to store downloaded output images (default: ./outputs).",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Keep Colab session active when stopping the API server.",
    )
    parser.add_argument(
        "--use-wsl",
        action="store_true",
        help="On Windows: force running colab commands via WSL2 ('wsl colab ...').",
    )
    parser.add_argument(
        "--assign-retries",
        type=int,
        default=3,
        help="Max retries for session allocation on 503 Service Unavailable (default: 3).",
    )
    parser.add_argument(
        "--assign-delay",
        type=int,
        default=20,
        help="Delay between session retry attempts in seconds (default: 20).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind the API server to (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=2504,
        help="Port number to bind the API server to (default: 2504).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import uvicorn

    cli_args = parse_args()
    RUNNER = ColabSingleThreadRunner(
        session_name=cli_args.session,
        gpu_type=cli_args.gpu,
        high_mem=cli_args.high_mem,
        sd_binary_path=cli_args.sd_binary,
        notebook_path=cli_args.notebook,
        output_dir=cli_args.output_dir,
        keep_alive_on_exit=cli_args.keep_session,
        use_wsl=cli_args.use_wsl,
        assign_retries=cli_args.assign_retries,
        assign_retry_delay=cli_args.assign_delay,
    )

    # Run uvicorn with workers=1 combined with threading.Lock() to strictly guarantee single-thread execution
    uvicorn.run(
        app,
        host=cli_args.host,
        port=cli_args.port,
        workers=1,
    )
