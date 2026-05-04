import pytest

from novel_dev.llm.subtasks import (
    LightweightSubtaskOrchestrator,
    RepairerSubtask,
    RetrieverSubtask,
    ValidatorSubtask,
)


@pytest.mark.asyncio
async def test_lightweight_subtask_orchestrator_runs_retriever_validator_and_repairer():
    async def retrieve(payload):
        return {"context": payload["query"]}

    def validate(payload):
        return {"valid": payload["value"] == "bad", "reason": "needs repair"}

    def repair(payload):
        fixed = dict(payload)
        fixed["value"] = "ok"
        return fixed

    orchestrator = LightweightSubtaskOrchestrator(
        retrievers=[RetrieverSubtask(name="context", handler=retrieve)],
        validators=[ValidatorSubtask(name="shape", handler=validate)],
        repairers=[RepairerSubtask(name="json", handler=repair)],
    )

    retrieved = await orchestrator.run_retriever("context", {"query": "summary"})
    validation = await orchestrator.run_validator("shape", {"value": "bad"})
    repaired = await orchestrator.run_repairer("json", {"value": "bad"})

    assert retrieved.payload == {"context": "summary"}
    assert validation.payload["valid"] is True
    assert repaired.payload == {"value": "ok"}
