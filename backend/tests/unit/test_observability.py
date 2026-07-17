import json
from datetime import datetime

import pytest
import structlog

from wildfireops.observability import configure_observability


def test_production_observability_emits_utc_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_observability("production")

    structlog.get_logger().info("ingestion_run", source_name="nws", outcome="success")

    captured = capsys.readouterr()
    event = json.loads(captured.out)
    assert event["event"] == "ingestion_run"
    assert event["source_name"] == "nws"
    assert event["outcome"] == "success"
    assert event["level"] == "info"
    timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    offset = timestamp.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0
