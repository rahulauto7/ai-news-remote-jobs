import os
import sys
import json

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture
def sample_doc():
    """The committed sample analyzed_content.json (last real pipeline run)."""
    path = os.path.join(ROOT, ".tmp", "analyzed_content.json")
    if not os.path.exists(path):
        pytest.skip("no .tmp/analyzed_content.json sample present")
    with open(path, encoding="utf-8") as f:
        return json.load(f)
