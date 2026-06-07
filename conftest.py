"""Put the project root on sys.path so tests can `import pipeline` etc.

The app modules live at the repo root (not a package), so without this pytest
would only add the tests/ directory to the path and the imports would fail.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
