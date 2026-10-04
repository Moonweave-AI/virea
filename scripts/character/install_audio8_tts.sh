#!/usr/bin/env bash
# Run inside WSL Ubuntu 24.04; never install GPU drivers in WSL.
set -euo pipefail
runtime_root="${VIREA_AUDIO8_RUNTIME:-$HOME/.local/share/virea/audio8}"
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
uv_bin="${UV_BIN:-$HOME/.local/bin/uv}"
if ! ldconfig -p | grep -F 'libnuma.so.1' > /dev/null; then
  echo 'Install the system library first: sudo apt-get install libnuma1' >&2
  exit 1
fi
mkdir -p "$runtime_root"
checkout() {
  local url="$1" destination="$2" revision="$3"
  if [[ ! -d "$destination" ]]; then
    git clone --filter=blob:none "$url" "$destination"
    git -C "$destination" checkout "$revision"
  elif [[ "$(git -C "$destination" rev-parse HEAD)" != "$revision" ]]; then
    echo "Unexpected checkout in $destination; use a fresh VIREA_AUDIO8_RUNTIME." >&2
    exit 1
  fi
}
checkout https://github.com/Edge0-AI/Audio8_TTS.git "$runtime_root/source" 07e40f5d0b03fc473635ef378654bfb581027ac3
checkout https://github.com/sgl-project/sglang-omni.git "$runtime_root/omni" 68a572348837f7b004857b4b07993c20ade4c017
if [[ ! -x "$runtime_root/venv/bin/python" ]]; then
  "$uv_bin" venv "$runtime_root/venv" --python 3.12
fi
"$uv_bin" pip sync --python "$runtime_root/venv/bin/python" "$script_root/requirements-audio8.txt" \
  --index https://download.pytorch.org/whl/cu128 --index https://pypi.org/simple --index-strategy unsafe-best-match
"$uv_bin" pip install --python "$runtime_root/venv/bin/python" --no-deps -e "$runtime_root/omni"
bash "$runtime_root/source/sglang_omni/scripts/install_adapter.sh" "$runtime_root/omni"
echo "Ready: $runtime_root"
