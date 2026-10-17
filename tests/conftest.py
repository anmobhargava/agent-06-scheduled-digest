import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"       # no usage reporting from the crew library
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ.pop("ANTHROPIC_API_KEY", None)             # tests run offline; the scripted model stands in for Claude
os.environ.pop("MAX_RUN_USD", None)
os.environ.pop("MONTHLY_CAP_USD", None)

import pytest  # noqa: E402


@pytest.fixture
def out(tmp_path):
    return tmp_path / "out"
