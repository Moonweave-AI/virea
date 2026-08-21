#!/usr/bin/env python3
"""Compatibility wrapper for the installed VIREA real-E2E validator."""

from virea_cli.real_e2e_validator import main

if __name__ == "__main__":
    raise SystemExit(main())
