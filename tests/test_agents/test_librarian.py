import pytest

from novel_dev.agents.librarian import LibrarianAgent


def test_extract_entities():
    agent = LibrarianAgent()
    text = "Lin Feng picked up the Azure Sword at Qingyun Sect."
    result = agent.extract_entities(text)
    assert "Lin Feng" in result["characters"]
    assert "Azure Sword" in result["items"]
    assert "Qingyun Sect" in result["locations"]
