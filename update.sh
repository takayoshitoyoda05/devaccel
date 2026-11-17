#!/usr/bin/env bash
# devaccel update — run from the target project root
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/kit/devaccel.py" update "$@"
