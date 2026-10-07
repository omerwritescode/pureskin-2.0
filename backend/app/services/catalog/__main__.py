"""python -m app.services.catalog   (from backend/): load products.json and print the load
report; if the load stops, print every refused row's problems and exit 1."""

import sys

from .loader import run

sys.stdout.reconfigure(encoding="utf-8")
sys.exit(run())
