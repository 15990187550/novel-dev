import importlib
import sys
import types


def test_embedding_server_lazy_loads_model_in_offline_mode(monkeypatch):
    calls = []
    snapshot_calls = []

    class FakeSentenceTransformer:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

    def fake_snapshot_download(*args, **kwargs):
        snapshot_calls.append((args, kwargs))
        return "/tmp/bge-m3-snapshot"

    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(snapshot_download=fake_snapshot_download),
    )
    sys.modules.pop("embedding_server", None)

    module = importlib.import_module("embedding_server")

    assert calls == []

    model = module.get_model()

    assert model is module.get_model()
    assert snapshot_calls == [
        (
            ("BAAI/bge-m3",),
            {"local_files_only": True},
        )
    ]
    assert calls == [(("/tmp/bge-m3-snapshot",), {})]
    assert module.os.environ["HF_HUB_OFFLINE"] == "1"
    assert module.os.environ["TRANSFORMERS_OFFLINE"] == "1"
