"""Simple embedding server using sentence-transformers."""
import os
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

app = FastAPI()

MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
DIMENSIONS = 1024

print(f"Loading {MODEL_NAME}...")
model = SentenceTransformer(MODEL_NAME, local_files_only=True)
print("Model loaded successfully")


class EmbedRequest(BaseModel):
    input: list[str]


@app.post("/v1/embeddings")
async def embeddings(req: EmbedRequest):
    if not req.input:
        return {"data": []}

    embeddings = model.encode(req.input, normalize_embeddings=True).tolist()

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
