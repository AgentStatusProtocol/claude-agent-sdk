#!/bin/sh
# apiKeyHelper for the Claude Agent SDK: prints the Anthropic API key stored in the macOS Keychain.
# The key never lives in a file, in the shell history or in the parent process environment.
SERVICE="${1:-anthropic-api-key}"
exec /usr/bin/security find-generic-password -a "$USER" -s "$SERVICE" -w
