#!/usr/bin/env bash
# one-line: refuses model weights, any format, any size
# staged: yes — scans content
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# Weights never enter git. Not compressed, not sharded, not "just this once" — a repository that
# has carried one is permanently large, because history keeps it after the file is deleted.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }
found=$(find "$T" -type f \( -name '*.safetensors' -o -name '*.gguf' -o -name '*.ckpt' -o -name '*.pt' \
        -o -name '*.pth' -o -name '*.bin' -o -name '*.onnx' -o -name '*.msgpack' -o -name '*.h5' \) \
        -not -path '*/.git/*' 2>/dev/null)
if [ -n "$found" ]; then
  echo "weight-shaped files found:"; echo "$found" | sed 's/^/  /'; exit 1
fi
exit 0
