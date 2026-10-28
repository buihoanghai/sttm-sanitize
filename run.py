"""Optional short entrypoint: python3 run.py --input reports --output out."""
from sttm_sanitize.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
