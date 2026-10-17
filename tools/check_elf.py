#!/usr/bin/env python3
"""Fail closed on missing, invalid, foreign or dynamically linked artifacts."""

import pathlib
import subprocess
import sys


def check(path):
    if not path.is_file():
        raise ValueError("missing artifact")
    header = subprocess.check_output(["readelf", "-h", str(path)], text=True)
    program = subprocess.check_output(["readelf", "-l", str(path)], text=True)
    dynamic = subprocess.check_output(["readelf", "-d", str(path)], text=True)
    if "Advanced Micro Devices X86-64" not in header or "ELF64" not in header:
        raise ValueError("not x86-64 ELF64")
    if "INTERP" in program or "NEEDED" in dynamic:
        raise ValueError("dynamic dependency")
    if "GNU_STACK" not in program or "RWE" in program:
        raise ValueError("executable stack or RWX segment")


if __name__ == "__main__":
    try:
        check(pathlib.Path(sys.argv[1]))
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError) as error:
        print(f"ELF verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    print("PASS static Linux x86-64 ELF; no INTERP/NEEDED")
