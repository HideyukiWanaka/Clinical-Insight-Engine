from fastapi import FastAPI

app = FastAPI(title="Stat Consultant Backend")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
