"""Entrypoint for hosted deploys: `main.py:mcp`.

Prefect Horizon loads the server by file path with
importlib.util.spec_from_file_location, which gives the module no package
context -- so it cannot load src/cronometer_mcp/server.py directly: the
relative `from .client import ...` in it fails. This file sits at the repo
root and imports the package by name instead.

Nothing else belongs here. Horizon ignores `if __name__ == "__main__"`.
Run the server yourself with the `cronometer-mcp` console script.
"""

import sys
from pathlib import Path

try:
    from cronometer_mcp.server import load_dotenv_for_local_dev, mcp
except ImportError:
    # Not pip-installed (the platform may only install dependencies, not the
    # project itself). Fall back to the src/ layout in this repo.
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from cronometer_mcp.server import load_dotenv_for_local_dev, mcp

# A hosted deploy injects real environment variables and has no .env; this is
# only so `fastmcp run main.py:mcp` works locally the same way.
load_dotenv_for_local_dev()

__all__ = ["mcp"]
