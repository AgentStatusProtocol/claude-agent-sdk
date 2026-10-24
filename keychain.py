"""Read secrets from the macOS Keychain (no third-party dependencies)."""

import os
import subprocess
import sys


def keychain_secret(service, account=None):
    """Return the secret stored under `service`, or None if absent or not on macOS."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", account or os.environ.get("USER", ""),
             "-s", service, "-w"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    secret = result.stdout.strip()
    return secret if result.returncode == 0 and secret else None


def describe(service):
    """Describe a Keychain item without revealing it."""
    secret = keychain_secret(service)
    if secret is None:
        return f"No Keychain item '{service}' readable for user {os.environ.get('USER')}."
    shape = "looks like an Anthropic key" if secret.startswith("sk-ant-") else "does NOT start with sk-ant-"
    return f"Keychain item '{service}' found: {len(secret)} characters, {shape}, ends with …{secret[-4:]}"


if __name__ == "__main__":
    print(describe(sys.argv[1] if len(sys.argv) > 1 else "anthropic-api-key"))
