from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers.app import app as app_router

app = FastAPI(
    title="OR-Tools + SimPy + FastAPI + Babylon.js Job Shop Demo",
    description="Job Shop 排程优化 + 随机扰动仿真 + 3D 可视化示例",
    version="1.0.0",
)


@app.get("/")
def root():
    return {
        "message": "OR-Tools + SimPy + FastAPI + Babylon.js Demo",
        "docs": "/docs",
        "visualization": "/vis",
        "endpoints": [
            "GET /demo/jobs",
            "GET /demo/pipeline",
            "POST /optimize",
            "POST /simulate",
            "POST /pipeline",
        ],
    }


app.include_router(app_router)

# 挂载 Babylon.js 前端页面
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/vis", StaticFiles(directory=STATIC_DIR, html=True), name="visualization")
