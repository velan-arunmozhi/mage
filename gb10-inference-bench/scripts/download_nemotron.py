#!/usr/bin/env python3
"""Download the official GB10 NVFP4 Nemotron checkpoint and its DSpark drafter."""
from huggingface_hub import snapshot_download

model = snapshot_download(
    "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4",
    local_dir="/tmp/models/nemotron-nvfp4",
)
print("NEMOTRON_MODEL_OK", model, flush=True)
try:
    draft = snapshot_download(
        "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark",
        local_dir="/tmp/models/nemotron-dspark",
    )
    print("NEMOTRON_DSPARK_OK", draft, flush=True)
except Exception as exc:  # noqa: BLE001
    print(f"NEMOTRON_DSPARK_FAIL {type(exc).__name__}: {exc}", flush=True)
