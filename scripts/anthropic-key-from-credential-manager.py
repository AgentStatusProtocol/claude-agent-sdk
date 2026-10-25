#!/usr/bin/env python3
"""apiKeyHelper for the Claude Agent SDK on Windows.

Prints one Credential Manager secret to stdout and nothing else. Claude Code
runs this when it needs the key and keeps the key in its own memory. The key
is not written to a file and does not enter the parent Python process.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keychain import keychain_secret


def main():
    if sys.platform != "win32":
        sys.stderr.write(
            "This helper reads Windows Credential Manager. "
            "On macOS the agent uses scripts/anthropic-key-from-keychain.sh.\n"
        )
        return 1
    service = sys.argv[1] if len(sys.argv) > 1 else "anthropic-api-key"
    secret = keychain_secret(service)
    if not secret:
        sys.stderr.write(f"No Credential Manager item '{service}' readable for this Windows user.\n")
        return 1
    sys.stdout.buffer.write(secret.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
