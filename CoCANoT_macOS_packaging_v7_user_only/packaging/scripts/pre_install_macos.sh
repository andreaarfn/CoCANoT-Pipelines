#!/bin/bash
set -euo pipefail

echo "Validating CoCANoT per-user installation destination..."
echo "PREFIX=${PREFIX}"

case "${PREFIX}" in
    /Users/*/Library/CoCANoT/runtime)
        ;;
    *)
        echo "ERROR: CoCANoT must be installed for the current user under ~/Library/CoCANoT/runtime."
        echo "ERROR: Refusing unexpected installation destination: ${PREFIX}"
        exit 1
        ;;
esac

# Never allow collision with the developer environment name.
case "${PREFIX}" in
    */Library/cocanot-pipelines)
        echo "ERROR: Refusing to install over a cocanot-pipelines development environment."
        exit 1
        ;;
esac

exit 0
