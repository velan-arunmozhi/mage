# Failures and exclusions

## This session

No completed experiment has failed yet. Entries are appended here when a command exits non-zero.

## Environment fact, not a benchmark result

The local WSL2 machine (`DESKTOP-LMHIG5A`) has an NVIDIA GeForce RTX 2060, 6 GB, driver 581.80, 7.7 GB RAM. It cannot run the models in this study. It was not used for inference.

## Historical, from earlier Scholar logs (not re-run)

The llama.cpp build at `/home/billin19/llama.cpp/build` (not `build-no-vmm`) hit `CUDA error: unspecified launch failure` in `ggml_backend_cuda_device_event_synchronize` while loading `Qwen2.5-Coder-14B` Q4_K_M. Later loads of Qwen3.6 used `/scratch/scholar/billin19/src/llama.cpp/build-no-vmm` (`GGML_CUDA_NO_VMM=ON`, architecture `121a-real`) and reached about 50 tok/s on a short prompt. This session uses that no-VMM build.

`--no-mmap` is not a valid flag in this llama.cpp revision (`31288c9`). Load mode is selected with `-lm`.
