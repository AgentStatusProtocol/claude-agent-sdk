#!/bin/sh
SERVICE="${1:-anthropic-api-key}"
exec /usr/bin/security find-generic-password -a "$USER" -s "$SERVICE" -w
