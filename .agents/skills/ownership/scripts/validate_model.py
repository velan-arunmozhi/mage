"""Run the ownership B-UML/B-OCL snapshot adapter from the MAGE suite."""
import runpy
from pathlib import Path
import sys

if __name__ == "__main__":
    runtime = Path(__file__).resolve().parents[2] / "_shared/bocl/validate_model.py"
    sys.exit(runpy.run_path(str(runtime))["main"]("ownership"))
