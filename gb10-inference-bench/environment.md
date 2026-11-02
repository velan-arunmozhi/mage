# Environment

Measured on the allocated node unless noted.

## Compute node (job 480649)

- Host: `scholar-k061.rcac.purdue.edu`
- Kernel: `7.0.0-1013-nvidia-64k` Ubuntu 24.04, aarch64
- GPU: NVIDIA GB10, compute capability 12.1, driver **595.71.05**, CUDA runtime reported 13.2
- `nvidia-smi` does not report a memory total (unified memory). llama.cpp reports **126756 MiB** addressable, VMM off, about **109284 MiB** free at probe time
- CPU: 20 cores, 10x Cortex-X925 (up to 3.9 GHz) + 10x Cortex-A725 (up to 2.8 GHz)
- RAM: 123 GiB total, swap 95 GiB present (benchmarks must not rely on swap)
- Local `/tmp`: 3.5 TB NVMe (`/dev/nvme0n1p5`), used for the vLLM image build because scratch is mounted `nodev`
- Root filesystem: 123 GB NVMe, 100 GB free at probe
- Slurm: partition `spark-batch`, 20 CPUs, 120500 MB, 1x `gpu:nvidia_gb10`, 4:00:00
- Python: 3.12.3
- Apptainer: 1.4.5
- nvcc on the node: CUDA 13.1, V13.1.115 (the llama.cpp build was compiled with `/apps/spack/scholar-dgx/apps/cuda/13.1.1`)

## llama.cpp

- Binary: `/scratch/scholar/billin19/src/llama.cpp/build-no-vmm/bin`
- Version: 0.7.0-dev, build 1, commit `31288c9c66e59377f7788d920678a565bb89dd37`
- Built with GCC 14.2.0 for Linux aarch64
- CMake: `GGML_CUDA=ON`, `GGML_CUDA_NO_VMM=ON`, `GGML_CUDA_FA=ON`, `CMAKE_CUDA_ARCHITECTURES=121a-real`

## Login node

- `scholar-fe00.rcac.purdue.edu`, RHEL 9, x86_64, 377 GiB RAM
- QOS `normal`: 2 jobs, 4 hour wall
- An ARM64 image build on scratch failed while creating the SIF (`nodev` mount). The retry is on the compute node's local `/tmp`.

## Local workstation

Not used for inference. RTX 2060, 6 GB, x86_64 WSL2.
