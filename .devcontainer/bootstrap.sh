#!/usr/bin/env bash
# Deliberately boring, and short enough to read in full before trusting it.
#
# This script runs INSIDE an environment that carries provider credentials as environment
# variables. Anything it executes can read them. So it installs a fixed list and does
# nothing else: no curl-pipe-to-shell, no dynamic package resolution, no fetching a script
# from anywhere, and nothing that prints the environment.
#
# If this file ever needs to become clever, that is the moment to ask whether the
# cleverness belongs somewhere without secrets in scope.
set -euo pipefail

echo "installing ffmpeg"
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends ffmpeg

echo "installing python dependencies"
# Pinned to what the pipeline actually imports, and nothing more. Every extra package is
# another author who can read the credentials in this environment.
python -m pip install --quiet --no-input \
  "pillow==11.3.0" \
  "numpy==2.0.2" \
  "pyyaml==6.0.3" \
  "google-genai"

echo
echo "verifying the toolchain the pipeline actually needs"
ffmpeg -version | head -1
ffprobe -version | head -1
python - <<'PY'
import PIL, numpy, yaml
print(f"pillow {PIL.__version__}  numpy {numpy.__version__}  pyyaml {yaml.__version__}")
try:
    from google import genai; print("google-genai present")
except Exception as e:
    print(f"google-genai MISSING: {e}")
PY

echo
echo "offline suites — these make zero paid calls and need no credentials:"
echo "  python3 test_firewall.py"
echo "  python3 test_runtime_firewall.py"
echo "  python3 test_camera_probe.py"
echo
echo "credentials come from Codespaces secrets, never from a file in this repo."
