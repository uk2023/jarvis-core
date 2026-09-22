#!/usr/bin/env python3

import subprocess
import sys


COMMAND = [
    sys.executable,
    "-m",
    "unittest",
    "discover",
    "-v",
]


def main():
    print("=" * 72)
    print(" JARVIS LOCKED BLUEPRINT VERIFICATION GATE")
    print("=" * 72)
    print()
    print("Running complete test suite...")
    print()

    result = subprocess.run(COMMAND)

    print()
    print("=" * 72)

    if result.returncode == 0:
        print("BLUEPRINT STATUS: VERIFIED")
        print("ALL TESTS PASSED")
        print("=" * 72)
        return 0

    print("BLUEPRINT STATUS: FAILED")
    print("ARCHITECTURAL OR RUNTIME VIOLATION DETECTED")
    print("=" * 72)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
