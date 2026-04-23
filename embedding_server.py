"""Simple embedding server using sentence-transformers."""
import os
from functools import lru_cache

from fastapi import FastAPI
from huggingface_hub import snapshot_download
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

app = FastAPI()

MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
DIMENSIONS = 1024


def _resolve_model_path(model_name: str) -> str:
    try:
        return snapshot_download(model_name, local_files_only=True)
    except Exception:
        return model_name


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    resolved_model = _resolve_model_path(MODEL_NAME)
    print(f"Loading {resolved_model}...")
    model = SentenceTransformer(resolved_model)
    print("Model loaded successfully")
    return model


class EmbedRequest(BaseModel):
    input: list[str]


@app.post("/v1/embeddings")
async def embeddings(req: EmbedRequest):
    if not req.input:
        return {"data": []}

    embeddings = get_model().encode(req.input, normalize_embeddings=True).tolist()

    return {
        "data": [
            {"embedding": emb, "index": i}
            for i, emb in enumerate(embeddings)
        ]
    }


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "bge-m3"}]}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 9997))
    uvicorn.run(app, host="0.0.0.0", port=port)
