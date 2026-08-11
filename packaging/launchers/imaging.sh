#!/bin/bash

PREFIX="__COCANOT_PREFIX__"

export PATH="${PREFIX}/bin:${PATH}"
export FSLDIR="${PREFIX}"
export PYTHONPATH="${PREFIX}/app:${PYTHONPATH:-}"

exec "${PREFIX}/bin/python" \
  "${PREFIX}/app/ImagingPipeline/dashboard.py"