import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.services.flow_control_service import (
    FlowCancelledError,
    FlowControlService,
    clear_cancel_request,
)


@pytest.fixture(autouse=True)
def clear_flow_cancel_registry():
    clear_cancel_request("novel-flow")


@pytest.mark.asyncio
async def test_flow_control_service_requests_and_clears_stop(async_session):
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel-flow",
        phase=Phase.VOLUME_PLANNING,
        checkpoint_data={"existing": "value"},
    )

    service = FlowControlService(async_session)
    result = await service.request_stop("novel-flow")

    assert result["stop_requested"] is True
    state = await director.resume("novel-flow")
    assert state.checkpoint_data["existing"] == "value"
    assert state.checkpoint_data["flow_control"]["cancel_requested"] is True
    assert await service.is_cancel_requested("novel-flow") is True
    with pytest.raises(FlowCancelledError):
        await service.raise_if_cancelled("novel-flow")

    await service.clear_stop("novel-flow")

    state = await director.resume("novel-flow")
    assert "flow_control" not in state.checkpoint_data
    assert await service.is_cancel_requested("novel-flow") is False
