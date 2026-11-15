# Compatibility and environment lock

This project adopts a single pinned environment for all research work. Do not upgrade the stack mid-project without updating this file and the lockfile/CI image.

- Python: 3.13.1
- PyTorch: 2.5.1
- CUDA: 12.4 (build matched to the PyTorch wheel used in the lab image)
- PyG: 2.6.1
- Opacus: 1.4.1
- Flower: 1.18.0
- Hydra: 1.3.2
- MLflow: 2.18.0
- pytest: 8.3.4

This repository is intentionally set up to run on CPU for the fixture dataset and to support GPU-capable runs only when a real GPU environment is explicitly available.
