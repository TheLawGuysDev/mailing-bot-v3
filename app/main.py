from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

from app.utils.logging import configure_logging
from app.db import Base, engine
import app.models  # noqa: F401
from app.routers import health, auth, admin, jobs, mailing, monday

configure_logging()

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Demand Letter Bot Backend V3", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(WEB_ROOT, "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def serve_html(filename: str) -> FileResponse:
    path = os.path.join(WEB_ROOT, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Missing {filename}")
    return FileResponse(path)


@app.get("/", include_in_schema=False)
def home():
    return serve_html("login.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return serve_html("dashboard.html")


@app.get("/manager", include_in_schema=False)
def manager_page():
    return serve_html("manager_dashboard.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return serve_html("admin_dashboard.html")


@app.get("/change-password", include_in_schema=False)
def change_password_page():
    return serve_html("change_password.html")

@app.get("/monday-view", include_in_schema=False)
def monday_view_page():
    return serve_html("monday_view.html")

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(jobs.router)
app.include_router(mailing.router)
app.include_router(monday.router)