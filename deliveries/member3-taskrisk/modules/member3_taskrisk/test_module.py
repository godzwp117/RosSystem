#!/usr/bin/env python3
"""Run the Member 3 real-algorithm tests, not copied placeholder tests."""
import sys
from pathlib import Path
import pytest

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    sys.exit(pytest.main([str(root / "tests/unit/test_member3_taskrisk.py"),
                         "-q", "-p", "no:cacheprovider"]))
