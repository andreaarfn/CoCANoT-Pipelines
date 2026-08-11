#!/bin/bash

PREFIX="__COCANOT_PREFIX__"

export PATH="${PREFIX}/bin:${PATH}"
export PYTHONPATH="${PREFIX}/app:${PYTHONPATH:-}"

exec "${PREFIX}/bin/python" \
  "${PREFIX}/app/ElectrophysiologyPipeline/dashboard.py"