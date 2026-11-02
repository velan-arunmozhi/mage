#!/usr/bin/env python3
from huggingface_hub import snapshot_download

path = snapshot_download(
    "ornith-ai/Ornith-1.5-35B-A3B-NVFP4",
    local_dir="/tmp/models/ornith-nvfp4",
)
print("DOWNLOAD_OK", path)
