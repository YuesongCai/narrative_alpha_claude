"""Source adapters — registry contract + manual adapter."""

from datetime import datetime

from narrativeflow.sources import default_registry
from narrativeflow.sources.manual import ManualSource


def test_default_registry_loads_yaml_config():
    reg = default_registry()
    keys = reg.keys()
    assert "hackernews" in keys
    assert "sec_edgar_8k" in keys
    # At least one RSS feed should be registered.
    rss_keys = [k for k in keys if k not in {"hackernews", "sec_edgar_8k"}]
    assert len(rss_keys) >= 3


def test_manual_adapter_yields_one_item():
    adapter = ManualSource(
        title="Test thesis",
        body="The market is wrong about X for Y reason.",
        url="https://example.com/x",
        author="Tester",
        published_at=datetime(2026, 5, 10),
    )
    items = list(adapter.fetch())
    assert len(items) == 1
    assert items[0].title == "Test thesis"
    assert items[0].url == "https://example.com/x"
    assert items[0].published_at == datetime(2026, 5, 10)
