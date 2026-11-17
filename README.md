# 🚀 Multi-Model Colab API Server (stable-diffusion.cpp)

A single-thread HTTP API server (FastAPI) that automatically controls Google Colab GPU instances via `google-colab-cli` for high-speed image synthesis using modern GGUF models, powered by the optimized C++ inference engine **`stable-diffusion.cpp` (`sd-cli`)**.

The system provides standalone support for 3 independent models, each with dedicated 1-click startup scripts (`.bat` / `.sh`), an isolated Python server (`.py`), and a dedicated API port:
1. **Z-Image-Turbo / Base GGUF** (Default Port: `2504`)
2. **Qwen-Image-2.1 GGUF** (Default Port: `2505`)
3. **MiniMax H3-Image GGUF** (Default Port: `2506`)

---

## 📌 Table of Contents
- [1. Model Comparison & Selection Guide](#1-model-comparison--selection-guide)
- [2. Project Directory Structure](#2-project-directory-structure)
- [3. System Requirements & Setup](#3-system-requirements--setup)
- [4. Quick Start Guide (1-Click)](#4-quick-start-guide-1-click)
- [5. System Architecture & Workflow](#5-system-architecture--workflow)
- [6. API Endpoints by Model](#6-api-endpoints-by-model)
- [7. Testing & Verification (Batch / curl / PowerShell)](#7-testing--verification-batch--curl--powershell)
- [8. Colab Account Management & Troubleshooting](#8-colab-account-management--troubleshooting)
- [9. GitHub Repository & Git LFS Notes](#9-github-repository--git-lfs-notes)

---

## 1. Model Comparison & Selection Guide

| Model | Windows Script (.bat) | Linux / macOS Script (.sh) | Python Server File | API Port | Steps | CFG Scale | Sampler / Sigmas | Key Features |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Z-Image-Turbo** | `run_zimage_colab_api.bat` | `run_zimage_colab_api.sh` | `zimage_colab_api.py` | `2504` | **8** (Turbo) / 30 (Base) | **1.0** (Turbo) / 5.0 (Base) | `euler` | Ultra-fast (~10-15s on T4 GPU), only 8 steps, lightweight VRAM footprint (~8.1 GB weights) |
| **Qwen-Image-2.1** | `run_qwen_colab_api.bat` | `run_qwen_colab_api.sh` | `qwen_colab_api.py` | `2505` | **30** | **6.0** | `euler` | Exceptional photographic detail, deep prompt comprehension in English and Chinese |
| **MiniMax H3-Image** | `run_minimax_h3_colab_api.bat` | `run_minimax_h3_colab_api.sh` | `minimax_h3_colab_api.py` | `2506` | **6** | **1.0** | `euler` / `minimax-h3-image` | Only 6 steps, dedicated distilled scheduler, supports Text-to-Image and Image Editing |

---

## 2. Project Directory Structure

```text
ColabImageAPI/
│
├── 📂 notebook/                                 # Reference Google Colab notebooks
│   ├── Z_Image_GGUF_T4_SDCPP_Colab.ipynb        # Reference architecture for Z-Image Turbo / Base
│   ├── Qwen_Image_2_1_GGUF_T4_SDCPP_Colab.ipynb # Reference architecture for Qwen-Image-2.1
│   └── MiniMax_H3_Image_GGUF_T4_Colab.ipynb     # Reference architecture for MiniMax H3-Image
│
├── 📂 stable-diffusion.cpp/                     # Core C++ library
│   └── build/bin/sd-cli/
│       ├── sd-cli                               # Linux CUDA ELF binary (auto-uploaded to Colab)
│       └── sd-server
│
├── 📂 outputs/                                  # Downloaded PNG images and run logs
├── 📂 .venv/                                    # Shared Python virtual environment (>= 3.12)
├── 📄 requirements.txt                          # Python dependencies
│
├── ⚙️ ENVIRONMENT SETUP SCRIPTS (.venv):
│   ├── setup_venv.bat                           # Auto-creates/configures .venv on Windows
│   └── setup_venv.sh                            # Auto-creates/configures .venv on Linux / macOS
│
├── 🚀 1-CLICK API LAUNCH SCRIPTS:
│   ├── run_zimage_colab_api.bat / .sh           # Z-Image Turbo Server (Port 2504)
│   ├── run_qwen_colab_api.bat / .sh             # Qwen-Image-2.1 Server (Port 2505)
│   └── run_minimax_h3_colab_api.bat / .sh       # MiniMax H3-Image Server (Port 2506)
│
├── 🐍 PYTHON API SERVER SOURCE CODE:
│   ├── zimage_colab_api.py                      # FastAPI + Colab Runner for Z-Image
│   ├── qwen_colab_api.py                        # FastAPI + Colab Runner for Qwen 2.1
│   └── minimax_h3_colab_api.py                  # FastAPI + Colab Runner for MiniMax H3
│
├── 🧪 TEST SCRIPTS:
│   ├── test_generate_zimage.bat / .sh           # Test request for Z-Image (Port 2504)
│   ├── test_generate_qwen.bat / .sh             # Test request for Qwen 2.1 (Port 2505)
│   └── test_generate_minimax.bat / .sh          # Test request for MiniMax H3 (Port 2506)
│
├── 🔑 ACCOUNT UTILITIES:
│   ├── logout.bat                               # Delete OAuth token on Windows
│   └── logout.sh                                # Delete OAuth token on Linux / macOS
│
└── 📄 README.md                                 # Comprehensive project documentation
```

---

## 3. System Requirements & Setup

- **Operating System:** Windows 10 / 11, Linux (Ubuntu, Debian, Fedora, Arch, etc.), macOS.
- **Python Version:** Requires `>= 3.12` (mandated by `google-colab-cli`).
- **Automatic Environment Setup (`.venv`):**
  - **Method 1 (Dedicated Setup):**
    - Windows: Double-click [setup_venv.bat](file:///K:/Projects/JavaScript/ColabImageAPI/setup_venv.bat).
    - Linux / macOS: Run `chmod +x *.sh && ./setup_venv.sh`.
  - **Method 2 (Smart 1-Click Launch):**
    - Simply run any `run_*` script (`.bat` or `.sh`) directly. The script will **automatically verify and create the `.venv`** if it does not already exist!

> [!TIP]
> If your system does not yet have Python 3.12 installed, the cleanest and fastest solution is using `uv`:
> - **Windows:** `pip install uv` (then execute `setup_venv.bat`).
> - **Linux / macOS:** `curl -LsSf https://astral.sh/uv/install.sh | sh` (then execute `./setup_venv.sh`).
> `uv` will automatically download and install an isolated Python 3.12 standalone binary inside the project without modifying your system Python.

---

## 4. Quick Start Guide (1-Click)

### Step 1: Start your desired model server

#### On Windows:
- **Z-Image-Turbo (Ultra-fast 8 steps):** Double-click [run_zimage_colab_api.bat](file:///K:/Projects/JavaScript/ColabImageAPI/run_zimage_colab_api.bat)
- **Qwen-Image-2.1 (High detail):** Double-click [run_qwen_colab_api.bat](file:///K:/Projects/JavaScript/ColabImageAPI/run_qwen_colab_api.bat)
- **MiniMax H3-Image (6 steps + Image Editing):** Double-click [run_minimax_h3_colab_api.bat](file:///K:/Projects/JavaScript/ColabImageAPI/run_minimax_h3_colab_api.bat)

#### On Linux / macOS:
```bash
chmod +x *.sh
# Choose one of the models to start:
./run_zimage_colab_api.sh      # Port 2504
./run_qwen_colab_api.sh        # Port 2505
./run_minimax_h3_colab_api.sh  # Port 2506
```

### Step 2: Authorize Google Colab (First run only)
- Your default web browser will automatically open Google OAuth sign-in.
- Log in to your Google account and click **Allow** to grant permissions for Colab CLI.

### Step 3: Automated Server Bootstrapping
- Requests and provisions a GPU runtime (T4) on Google Colab.
- Compresses and uploads the local CUDA `sd-cli` binary to the Colab VM.
- Downloads the corresponding GGUF weights directly from Hugging Face into VM cache.
- Starts the local API server and reports readiness for incoming requests.

---

## 5. System Architecture & Workflow

```text
[Client / WebUI / App / curl]
            │
            ▼ HTTP Request (POST /api/generate)
[FastAPI Server (Local Port: 2504 / 2505 / 2506)] ──(Mutex Lock: Strict 1-Thread Execution)
            │
            ├─► 1. Reuse existing or allocate new Colab session via google-colab-cli
            ├─► 2. Verify sd-cli binary on Colab VM:
            │       - If missing: Temporary gzip compression -> Upload -> Extract to /content/stable-diffusion.cpp/build/bin/sd-cli
            │       - If size matches: Skip upload (instant startup)
            ├─► 3. Bootstrap: Download corresponding GGUF model weights from Hugging Face
            ├─► 4. Execute sd-cli subprocess on Colab (Stream progress logs back in real-time)
            ├─► 5. Save job receipt job_<id>.json (Resilient against temporary WebSocket disconnects)
            └─► 6. Download generated PNG image to ./outputs directory via colab download
```

---

## 6. API Endpoints by Model

All 3 API servers provide uniform, standardized endpoints:

### 1. `GET /health`
Inspects the availability and readiness of the Google Colab session and GPU.

### 2. `POST /api/bootstrap`
Manually reconnects or re-initializes the Google Colab session if GPU allocation was delayed.

### 3. `POST /api/generate` (Primary Endpoint)

#### Request payload for Z-Image-Turbo (`http://127.0.0.1:2504`):
```json
{
  "positive_prompt": "A beautiful sunset over tropical beach, turquoise water, palm trees",
  "negative_prompt": "blurry, low quality, distorted",
  "aspect_ratio": "16:9",
  "steps": 8,
  "cfg": 1.0,
  "variant": "Turbo",
  "quant": "Q6",
  "response_format": "json"
}
```

#### Request payload for Qwen-Image-2.1 (`http://127.0.0.1:2505`):
```json
{
  "positive_prompt": "A photorealistic portrait of an East Asian woman sitting by a luxury pool, 8k",
  "negative_prompt": "bad anatomy, blurry, cartoon",
  "aspect_ratio": "16:9",
  "steps": 30,
  "cfg": 6.0,
  "quant": "Q6",
  "encoder_quant": "UD-Q4_K_XL",
  "response_format": "json"
}
```

#### Request payload for MiniMax H3-Image (`http://127.0.0.1:2506`):
```json
{
  "positive_prompt": "A cinematic high-fashion portrait on a balcony overlooking the city at dusk",
  "negative_prompt": "deformed, watermark",
  "aspect_ratio": "16:9",
  "steps": 6,
  "cfg": 1.0,
  "quant": "Q4",
  "encoder": "compact_4b_int8",
  "reference_image_b64": null,
  "response_format": "json"
}
```
*(For image editing with MiniMax H3, pass the Base64-encoded string of the source image in the `reference_image_b64` field).*

### 4. `POST /v1/images/generations` (OpenAI Compatibility)
Drop-in compatible with official OpenAI SDKs, LangChain, and third-party WebUIs.

---

## 7. Testing & Verification (Batch / curl / PowerShell)

### Method 1: Using provided test scripts (Recommended)
- Test Z-Image: Double-click [test_generate_zimage.bat](file:///K:/Projects/JavaScript/ColabImageAPI/test_generate_zimage.bat)
- Test Qwen 2.1: Double-click [test_generate_qwen.bat](file:///K:/Projects/JavaScript/ColabImageAPI/test_generate_qwen.bat)
- Test MiniMax H3: Double-click [test_generate_minimax.bat](file:///K:/Projects/JavaScript/ColabImageAPI/test_generate_minimax.bat)

### Method 2: Testing with `curl`

#### Generate with Z-Image-Turbo (Port 2504):
```bash
curl -X POST "http://127.0.0.1:2504/api/generate" ^
  -H "Content-Type: application/json" ^
  -d "{\"positive_prompt\": \"A photorealistic cute fluffy cat sitting on a wooden bench, golden hour\", \"aspect_ratio\": \"16:9\", \"steps\": 8, \"cfg\": 1.0}"
```

#### Generate with Qwen-Image-2.1 (Port 2505):
```bash
curl -X POST "http://127.0.0.1:2505/api/generate" ^
  -H "Content-Type: application/json" ^
  -d "{\"positive_prompt\": \"A photorealistic cute fluffy cat sitting on a wooden bench, golden hour\", \"aspect_ratio\": \"16:9\", \"steps\": 30, \"cfg\": 6.0}"
```

#### Generate with MiniMax H3-Image (Port 2506):
```bash
curl -X POST "http://127.0.0.1:2506/api/generate" ^
  -H "Content-Type: application/json" ^
  -d "{\"positive_prompt\": \"A photorealistic cute fluffy cat sitting on a wooden bench, golden hour\", \"aspect_ratio\": \"16:9\", \"steps\": 6, \"cfg\": 1.0}"
```

---

## 8. Colab Account Management & Troubleshooting

### 🔴 Switching Google Colab Accounts when Quota is Exhausted
When your current Google account reaches its daily free GPU quota on Google Colab (resulting in `503 Service Unavailable` or `412 TooManyAssignments`):
1. Double-click [logout.bat](file:///K:/Projects/JavaScript/ColabImageAPI/logout.bat) (or run `./logout.sh` on Linux / macOS).
2. The script will delete the stored OAuth token from the system keyring.
3. Re-run your desired model `.bat` or `.sh` script (`run_zimage_colab_api.bat`, `run_qwen_colab_api.bat`, or `run_minimax_h3_colab_api.bat`).
4. Your browser will reopen to let you select another Google account that has remaining free GPU quota.

### 🔴 Image Dimension Requirements
- `sd-cli` requires both image width and height to be strictly divisible by 32.
- The server automatically handles normalization via `(width // 32) * 32`, allowing you to use any standard aspect ratio presets (`16:9`, `9:16`, `1:1`, `4:3`, `3:2`, `21:9`) safely.

---

## 9. GitHub Repository & Git LFS Notes

> [!IMPORTANT]
> The prebuilt binary file `stable-diffusion.cpp/build/bin/sd-cli/sd-cli` is approximately **124 MB**.
> Because GitHub enforces a strict 100 MB maximum file size limit for regular Git commits:
> 1. Use **Git LFS** (Large File Storage) to track large binaries before pushing:
>    ```bash
>    git lfs install
>    git lfs track "stable-diffusion.cpp/build/bin/sd-cli/*"
>    git add .gitattributes
>    ```
> 2. Alternatively, you can exclude the compiled binary from Git tracking via `.gitignore` and build or download `sd-cli` directly on the host machine or release assets.
