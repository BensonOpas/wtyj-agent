# test_190_content_pipeline_gate.py — Brief 190: Content pipeline archival
import asyncio
from unittest.mock import patch, MagicMock


# --- Test 1: Scheduler does NOT start when content_pipeline is false/absent ---
@patch("agents.social.scheduler.start_scheduler")
@patch("agents.social.webhook_server.config_loader")
def test_scheduler_not_started_when_pipeline_off(mock_config, mock_start):
    mock_config.get_raw.return_value = {"features": {}}
    from agents.social.webhook_server import lifespan

    async def _run():
        async with lifespan(MagicMock()):
            pass

    asyncio.run(_run())
    mock_start.assert_not_called()


# --- Test 2: Scheduler DOES start when content_pipeline is true ---
@patch("agents.social.scheduler.start_scheduler")
@patch("agents.social.webhook_server.config_loader")
def test_scheduler_started_when_pipeline_on(mock_config, mock_start):
    mock_config.get_raw.return_value = {"features": {"content_pipeline": True}}
    from agents.social.webhook_server import lifespan

    async def _run():
        async with lifespan(MagicMock()):
            pass

    asyncio.run(_run())
    mock_start.assert_called_once()
