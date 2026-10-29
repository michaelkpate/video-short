#!/bin/bash
# Check what Video Short needs and prepare it. Prints each missing tool with its install command and exits 1,
# so the agent can ask the user before installing. When everything is present, it installs numpy and fetches
# HyperFrames with its headless Chrome and the Parakeet speech model (about 1 GB in all), so nothing stalls later.
# On Windows, run it from Git Bash.
DIR="$(cd "$(dirname "$0")" && pwd)"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) WIN=1 ;;
  *) WIN=0 ;;
esac
missing=0
# need COMMAND BREW_FORMULA WINGET_ID
need() {
  command -v "$1" >/dev/null && return
  if [ "$WIN" = 1 ]; then echo "missing: $1  (Windows: winget install --id $3 -e)"
  else echo "missing: $1  (Mac: brew install $2)"; fi
  missing=1
}
need ffmpeg ffmpeg Gyan.FFmpeg
need yt-dlp yt-dlp yt-dlp.yt-dlp
need node node OpenJS.NodeJS.LTS
# Python 3.10+: uv can provide it, otherwise python3 (or python on Windows, where python3 may be the Store stub).
if ! command -v uv >/dev/null && ! python3 -c "import sys" >/dev/null 2>&1 && ! python -c "import sys" >/dev/null 2>&1; then
  if [ "$WIN" = 1 ]; then echo "missing: python  (Windows: winget install --id Python.Python.3.12 -e)"
  else echo "missing: python3  (Mac: brew install python)"; fi
  missing=1
fi
if command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  if [ "$WIN" = 1 ]; then echo "too old: node $(node -v), needs 22 or newer  (Windows: winget upgrade --id OpenJS.NodeJS.LTS -e)"
  else echo "too old: node $(node -v), needs 22 or newer  (Mac: brew upgrade node)"; fi
  missing=1
fi
[ "$missing" = 1 ] && exit 1
"$DIR/py" -c "import numpy" || exit 1
HF=hyperframes@0.8.169
LOG="$(mktemp)"
quiet() { "$@" >"$LOG" 2>&1 || { tail -c 1500 "$LOG"; return 1; }; }   # progress spinners stay out of the agent's context
quiet npx -y $HF browser ensure || { echo "HyperFrames could not download its Chrome"; exit 1; }
quiet npx -y $HF models install parakeet || { echo "HyperFrames could not download the Parakeet speech model"; exit 1; }
echo "ready: ffmpeg, yt-dlp, Python, Node $(node -v), HyperFrames with Chrome and Parakeet"
