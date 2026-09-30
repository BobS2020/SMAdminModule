import os
from dotenv import load_dotenv
import msal
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "local")
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8001")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["User.Read"]

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_confidential_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
    )


@router.get("/start")
async def auth_start():
    """
    User clicks 'Sign in with Microsoft' → redirect to Microsoft.
    """
    msal_app = _build_confidential_app()
    redirect_uri = f"{BASE_URL}/auth/callback"

    auth_url = msal_app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    return RedirectResponse(auth_url)


@router.get("/callback")
async def auth_callback(request: Request, code: str | None = None):
    """
    Microsoft redirects back here with ?code=...
    Exchange code for token, store in cookies, redirect to /screen1.
    """
    if not code:
        return HTMLResponse("Missing authorization code", status_code=400)

    msal_app = _build_confidential_app()
    redirect_uri = f"{BASE_URL}/auth/callback"

    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    if "access_token" not in result:
        return HTMLResponse(str(result), status_code=400)

    access_token = result["access_token"]

    claims = result.get("id_token_claims", {})
    user_email = claims.get("preferred_username", "unknown_user")
    user_name = claims.get("name", user_email)   # fallback to email if name missing

    redirect_target = request.cookies.get("post_auth_redirect", "/admin/screen1")
    response = RedirectResponse(url=redirect_target)

    response.set_cookie("access_token", access_token, httponly=True)
    response.set_cookie("user_id", user_email, httponly=True)
    response.set_cookie("user_name", user_name, httponly=True)

    return response


from fastapi import Request
from fastapi.responses import RedirectResponse

async def ensure_token(request: Request):
    """
    If the user has a token, return None.
    If not, redirect them to /auth/start.
    """
    access_token = request.cookies.get("access_token")

    if access_token:
        return None

    return RedirectResponse(url="/auth/start")
