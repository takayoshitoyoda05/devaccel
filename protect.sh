#!/usr/bin/env bash
# devaccel protect — run from the target project root (asks before changing GitHub settings)
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/kit/devaccel.py" protect "$@"
