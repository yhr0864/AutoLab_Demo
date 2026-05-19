from fastapi import FastAPI

from app.routers.app import app as app_router

app = FastAPI(
    title="OR-Tools + SimPy + FastAPI Job Shop Demo",
    description="Job Shop 排程优化 + 随机扰动仿真 + Web API 示例",
    version="1.0.0",
)


@app.get("/")
def root():
    return {
        "message": "OR-Tools + SimPy + FastAPI demo",
        "docs": "/docs",
        "endpoints": [
            "GET /demo/jobs",
            "POST /optimize",
            "POST /simulate",
            "POST /pipeline",
            "GET /demo/pipeline",
        ],
    }


app.include_router(app_router)
