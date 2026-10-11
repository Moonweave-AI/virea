#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_root=${VIREA_DATA_ROOT:-"$repo/.virea-runtime/portable"}
mkdir -p "$data_root/tools/uv"
data_root=$(CDPATH= cd -- "$data_root" && pwd)
uv="$data_root/tools/uv/uv"
if [ ! -x "$uv" ]; then
    printf '%s\n' '[VIREA 1/8] Installing the user-local runtime manager...'
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --proto '=https' --tlsv1.2 'https://astral.sh/uv/0.10.9/install.sh' -o "$data_root/install-uv.sh"
    elif command -v wget >/dev/null 2>&1; then
        wget 'https://astral.sh/uv/0.10.9/install.sh' -O "$data_root/install-uv.sh"
    else
        printf '%s\n' 'curl or wget is required to download the runtime manager.' >&2
        exit 1
    fi
    UV_UNMANAGED_INSTALL="$data_root/tools/uv" sh "$data_root/install-uv.sh"
fi
export UV_PYTHON_INSTALL_DIR="$data_root/tools/python"
export UV_CACHE_DIR="$data_root/cache/uv"
export PATH="$data_root/tools/uv:$PATH"
exec "$uv" run --no-project --python 3.12 "$repo/scripts/setup/first_run.py" --data-root "$data_root" "$@"
