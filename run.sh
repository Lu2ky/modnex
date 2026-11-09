#!/usr/bin/env bash
# Arranca el gestor en http://127.0.0.1:8765
cd "$(dirname "$0")"
exec python3 app.py
