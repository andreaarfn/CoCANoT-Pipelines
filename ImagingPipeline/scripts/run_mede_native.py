#!/usr/bin/env python3
"""Run MEDE 0.0.13 defacing on a single 3D NIfTI in an isolated Python worker.

MEDE uses a PyTorch model and normally launches four DataLoader processes.
Restrict inference to one process to lower peak memory pressure.
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # Set threading before importing torch/numpy.
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[key] = "1"

    import nibabel as nib
    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    import mede.dicom_skullstrip_defacing as mede_inference
    from mede.dataset import InferenceDataset

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    source = nib.load(str(args.input))
    if len(source.shape) != 3:
        raise ValueError(f"MEDE Step 3C test only supports 3D NIfTI; got {source.shape}")

    def low_memory_loader(path: str, batch_size: int = 1):
        dataset = InferenceDataset({"image_path": [path]})
        return DataLoader(dataset, batch_size=1, num_workers=0, pin_memory=False)

    # MEDE's default dataloader uses four prefetched processes; on smaller
    # Apple Silicon machines, this may cause an avoidable RAM spike.
    mede_inference.get_inference_loader = low_memory_loader

    with tempfile.TemporaryDirectory(prefix="cocanot_mede_") as directory:
        inference = mede_inference.Inference(
            output_path=directory, gpu=None, deface=True, verbose=True
        )
        inference(str(args.input))
        basename = args.input.name
        if basename.endswith(".nii.gz"):
            basename = basename[:-7]
        elif basename.endswith(".nii"):
            basename = basename[:-4]
        produced = Path(directory) / (basename + "_deface.nii.gz")
        if not produced.is_file():
            raise RuntimeError(f"MEDE did not create expected output: {produced}")
        result = nib.load(str(produced))
        # Prevent a resampled/reoriented image from being accepted as matching
        # CoCANoT's spatial geometry without a deliberate inverse transform.
        if result.shape != source.shape:
            raise ValueError(f"MEDE changed image dimensions: {source.shape} -> {result.shape}")
        if not np.allclose(result.affine, source.affine, rtol=1e-5, atol=1e-5):
            raise ValueError("MEDE output affine differs from input; review required")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced, args.output)
    print(f"MEDE defacing completed: {args.output}", flush=True)


if __name__ == "__main__":
    main()
