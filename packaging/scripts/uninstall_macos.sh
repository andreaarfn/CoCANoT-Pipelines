#!/bin/bash
set -e

COCANOT_PREFIX="${HOME}/Library/cocanot-pipelines"

IMAGING_APP="/Applications/CoCANoT Imaging.app"
EP_APP="/Applications/CoCANoT Electrophysiology.app"

echo "Removing CoCANoT Pipelines..."

if [ -d "${COCANOT_PREFIX}" ]; then
    rm -rf "${COCANOT_PREFIX}"
fi

if [ -d "${IMAGING_APP}" ]; then
    rm -rf "${IMAGING_APP}"
fi

if [ -d "${EP_APP}" ]; then
    rm -rf "${EP_APP}"
fi

echo "CoCANoT Pipelines has been removed."