"""Compatibility entry point for running the Document Processor desktop application."""

import sys
from pathlib import Path

# Allow `python app.py` to work without installing the package: ensure the
# bundled `src/` directory is importable even when the package is not installed.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from document_processor.app import main


if __name__ == "__main__":
    main()
