from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import (
    routes_signals, routes_market, routes_simulate, routes_backtest,
    routes_jobs, routes_news, routes_oracle,
)
from app.db_init import apply_schema
from app.scheduler import start_background_jobs
from app import config

app = FastAPI(title="Oracle X", description="AI cross-market alpha engine")

app.add_middleware(
    CORSMiddleware,
    # Set ALLOWED_ORIGINS (comma-separated) in the environment for any real
    # deployment — see app/config.py. Defaults to "*" only for local dev.
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_signals.router)
app.include_router(routes_market.router)
app.include_router(routes_simulate.router)
app.include_router(routes_backtest.router)
app.include_router(routes_jobs.router)
app.include_router(routes_news.router)
app.include_router(routes_oracle.router)


@app.on_event("startup")
async def on_startup():
    try:
        apply_schema()
    except Exception as exc:
        # Log and continue rather than crash the whole app — a schema
        # apply failure (e.g. DB not reachable yet) shouldn't take down
        # /health, which is useful for debugging a bad deploy.
        print(f"schema apply failed on startup: {exc}")

    # Fires off every ingestion/pipeline job as a background task. This is
    # what makes the app self-sufficient with zero manual `python -m
    # app.jobs.X` invocation — required since there's no terminal access
    # in a phone-only workflow.
    start_background_jobs()


@app.get("/health")
def health():
    return {"status": "ok", "service": "oracle-x"}
