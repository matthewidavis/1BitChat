#!/usr/bin/env bash
# Convenience launcher for Linux/macOS — runs the server from source.
# Requires: python3, `pip install -r requirements.txt`, and a llama-server
# binary at build/bin/llama-server (build from https://github.com/microsoft/BitNet).
cd "$(dirname "$0")"
exec python3 chat-ui/server.py
