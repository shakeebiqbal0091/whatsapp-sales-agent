
from fastapi import FastAPI
from workers import asgi

app = FastAPI()


@app.get("/")
async def home():
    return {"status": "ok", "message": "Cloudflare test is working"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


Default = asgi.entrypoint(app)
