"""Source-checkout wrapper for the installed VIREA evidence validator."""

from virea_cli.production_e2e_evidence_validator import main

if __name__ == "__main__":
    raise SystemExit(main())
