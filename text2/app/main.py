from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.routes import router

app = FastAPI(title="轻量 OJ", description="个人学习用在线代码题库与判题系统", version="1.0.0")
app.include_router(router)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", include_in_schema=False)
def index(): return FileResponse(static_dir / "index.html")

@app.get("/health")
def health(): return {"status": "ok"}
