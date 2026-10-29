#!/usr/bin/env python3
"""Run PyFaceWipe in the current native Python environment (no WSL/FSL).

Internal Step 3C worker. PyFaceWipe writes its own filename under the output
directory; stage it first and move the produced file to CoCANoT's expected path.
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np


def run(source: Path, target: Path, mask_path: Path | None = None) -> None:
    try:
        from pyfacewipe import PyFaceWipe
    except ImportError as exc:
        raise RuntimeError(
            "PyFaceWipe is missing from the application's Python environment. "
            "Install pyfacewipe with its native dependencies (including torch)."
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cocanot_facewipe_") as staging:
        result = PyFaceWipe(use_gpu=False).deface(
            source=source, output_dir=Path(staging), save_steps=False
        )
        staged = Path(result["outfile"])
        if not staged.is_file():
            raise RuntimeError(f"PyFaceWipe returned no output NIfTI at {staged}")
        # Preserve ATLAS's canonical *_defaced.nii.gz filenames.
        image = nib.load(str(staged))
        if len(image.shape) != 3:
            raise RuntimeError(f"Unexpected PyFaceWipe output shape: {image.shape}")
        nib.save(image, str(target))
        if mask_path is not None:
            keep_mask = np.asarray(result["deface_mask"]) != 0
            if keep_mask.shape != image.shape:
                raise RuntimeError("PyFaceWipe mask does not match source geometry")
            np.save(str(mask_path), keep_mask, allow_pickle=False)
    print(f"PyFaceWipe completed: {target}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mask", type=Path)
    args = parser.parse_args()
    run(args.input, args.output, args.mask)
