# Compatibility and environment lock

This project adopts pinned dependencies and records what has actually been exercised. Do not upgrade the stack mid-project without updating this file and the lockfile/CI image.

- Python: 3.13.1 local development; CI currently uses 3.12
- Hydra: 1.3.2
- MLflow: 2.18.0
- pytest: 8.3.4
- pandas: 2.2.3
- Pandera: 0.22.1
- PyArrow: 18.1.0
- DVC: 3.67.1

The data-validation and fixture-Parquet pipeline has been exercised on CPU with the pinned data stack above. The PyTorch, CUDA, PyG, Opacus, and Flower combination is not yet installed or verified; it must be tested and recorded before model development begins. GPU runs require an explicitly available GPU environment.
