import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PERSONA_PATH = ROOT / "config" / "persona.yaml"


@pytest.fixture(scope="session")
def persona_path() -> Path:
    return PERSONA_PATH


@pytest.fixture(scope="session")
def persona(persona_path):
    from src.core.persona import load_persona

    return load_persona(persona_path)
