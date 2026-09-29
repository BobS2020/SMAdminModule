import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# MSAL auth router
from auth import router as auth_router
from auth import ensure_token

# Admin module routes
from admin_routes import router as admin_router

BASE_URL = os.getenv("BASE_URL", "http://localhost:8001")

app = FastAPI(title="SM Admin Module")

from utils.code_table_loader import load_code_table

app.state.code_table = load_code_table()

# Static + templates
app.mount("/static", StaticFiles(directory="static"), name="static")
#templates = Jinja2Templates(directory="templates")

# Routers
app.include_router(auth_router)
app.include_router(admin_router)

@app.get("/")
async def root(request: Request):
    access_token = request.cookies.get("access_token")
    if access_token:
        return RedirectResponse(f"{BASE_URL}/admin/screen1")
    return RedirectResponse(f"{BASE_URL}/auth/start")
