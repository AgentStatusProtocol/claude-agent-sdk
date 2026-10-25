"""Read and store secrets in the OS credential store (no third-party dependencies).

macOS uses the Keychain via `/usr/bin/security`. Windows uses Credential Manager
via `CredReadW` / `CredWriteW`. The secret never needs to appear on a command line.
"""

import argparse
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


def store_label():
    """Name of the OS secret store on this platform, or None when there is none."""
    if sys.platform == "darwin":
        return "Keychain"
    if sys.platform == "win32":
        return "Credential Manager"
    return None


def current_user():
    return os.environ.get("USER") or os.environ.get("USERNAME") or ""


def decode_credential_blob(raw):
    """Decode a Windows credential blob written as UTF-16LE (cmdkey does the same)."""
    if not raw:
        return ""
    if len(raw) % 2 == 0:
        text = raw.decode("utf-16le")
    else:
        text = raw.decode("utf-8")
    return text.lstrip("\ufeff").rstrip("\x00\r\n")


def keychain_secret(service, account=None):
    """Return the secret stored under `service`, or None if it is absent or unreadable.

    On macOS, `account` selects the Keychain account (default: $USER). On Windows the
    Credential Manager vault is already per Windows user, so `account` is ignored.
    """
    if sys.platform == "darwin":
        return _mac_read(service, account or os.environ.get("USER", ""))
    if sys.platform == "win32":
        return _win_read(service)
    return None


def store_secret(service, account=None):
    """Prompt for a secret and store it. The secret is not taken from the command line."""
    label = store_label()
    if label is None:
        raise SystemExit("No OS secret store on this system. Use --key-source env.")
    account = account or current_user()
    if sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/security", "add-generic-password", "-U", "-a", account, "-s", service, "-w"],
        )
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        print(f"Stored Keychain item '{service}'.")
        return
    secret = _prompt_secret(service)
    _win_write(service, secret, account)
    print(f"Stored Credential Manager item '{service}'.")


def delete_secret(service, account=None):
    """Remove a stored secret. Missing items are reported, not treated as a crash."""
    label = store_label()
    if label is None:
        raise SystemExit("No OS secret store on this system.")
    account = account or current_user()
    if sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/security", "delete-generic-password", "-a", account, "-s", service],
        )
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        print(f"Deleted Keychain item '{service}'.")
        return
    err = _win_delete(service)
    if err:
        if err == ERROR_NOT_FOUND:
            raise SystemExit(f"No Credential Manager item '{service}'.")
        raise SystemExit(f"Could not delete Credential Manager item '{service}' (Windows error {err}).")
    print(f"Deleted Credential Manager item '{service}'.")


def describe(service):
    """Describe a stored secret without revealing it."""
    label = store_label()
    user = current_user()
    if label is None:
        return f"No OS secret store on this system; cannot read '{service}'."
    secret = keychain_secret(service)
    if secret is None:
        return f"No {label} item '{service}' readable for user {user}."
    shape = "looks like an Anthropic key" if secret.startswith("sk-ant-") else "does NOT start with sk-ant-"
    return f"{label} item '{service}' found: {len(secret)} characters, {shape}, ends with …{secret[-4:]}"


def _prompt_secret(service):
    import getpass
    secret = getpass.getpass(f"Secret for Credential Manager item '{service}': ")
    if not secret:
        raise SystemExit("Empty secret, nothing stored.")
    return secret


def _mac_read(service, account):
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    secret = result.stdout.strip()
    return secret if result.returncode == 0 and secret else None


def _win_advapi32():
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.POINTER(_CREDENTIALW)]
    advapi32.CredFree.restype = None
    return advapi32


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _win_read(service):
    try:
        advapi32 = _win_advapi32()
        holder = ctypes.POINTER(_CREDENTIALW)()
        ok = advapi32.CredReadW(service, CRED_TYPE_GENERIC, 0, ctypes.byref(holder))
    except OSError:
        return None
    if not ok:
        return None
    try:
        cred = holder.contents
        if not cred.CredentialBlob or not cred.CredentialBlobSize:
            return None
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
    finally:
        advapi32.CredFree(holder)
    secret = decode_credential_blob(raw)
    return secret or None


def _win_write(service, secret, username):
    blob = secret.encode("utf-16le")
    blob_buf = ctypes.create_string_buffer(blob)
    cred = _CREDENTIALW()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = service
    cred.UserName = username
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.Comment = "Stored by the ASP Supplier Desk demo"
    advapi32 = _win_advapi32()
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        err = ctypes.get_last_error()
        raise SystemExit(f"Could not store Credential Manager item '{service}' (Windows error {err}).")


def _win_delete(service):
    """Return 0 when the item is gone, otherwise the Windows error code."""
    advapi32 = _win_advapi32()
    ctypes.set_last_error(0)
    if advapi32.CredDeleteW(service, CRED_TYPE_GENERIC, 0):
        return 0
    return ctypes.get_last_error() or 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read or store a secret in the macOS Keychain or Windows Credential Manager."
    )
    parser.add_argument("service", nargs="?", default="anthropic-api-key",
                        help="item name (default: anthropic-api-key)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--set", action="store_true",
                       help="prompt for the secret and store it; the secret is not a command argument")
    group.add_argument("--delete", action="store_true", help="remove the stored secret")
    args = parser.parse_args(argv)
    if args.set:
        store_secret(args.service)
        return
    if args.delete:
        delete_secret(args.service)
        return
    print(describe(args.service))


if __name__ == "__main__":
    main()
