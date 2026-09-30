from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import ensure_token
from db import get_changelog_entries, get_changelog_by_id, update_user_deletion_mysql
import os
from dotenv import load_dotenv
load_dotenv()
from utils.code_table_loader import get_code_message

BASE_URL = os.getenv("BASE_URL", "http://localhost:8001")

templates = Jinja2Templates(directory="templates")

router = APIRouter()

print("TEMPLATES TYPE:", type(templates))

# Screen0 – Admin Gate
@router.get("/admin")
async def admin_home(request: Request):
    result = await ensure_token(request)
    if result:
        return result
    return RedirectResponse(f"{BASE_URL}/admin/screen1")


# Screen1 – Search Hub
@router.get("/admin/screen1")
async def screen1(request: Request):


    result = await ensure_token(request)
    if result:
        return result
    return templates.TemplateResponse(
        request,
        "screen1.html",
        {"request": request}
    )



# Screen2 – Results List
@router.get("/admin/screen2")
async def screen2(request: Request, mode: str = None, name: str = None, qtr: str = None):
    result = await ensure_token(request)
    if result:
        return result

    results = get_changelog_entries(mode, name, qtr)
    return templates.TemplateResponse(
        request,
        "screen2.html",
        {"request": request, "results": results}
    )



# Screen3 – Review + Confirm Deletion
@router.get("/admin/screen3")
async def screen3(request: Request, logid: int):

    # ⭐ Save the original URL BEFORE ensure_token()
    original_url = str(request.url)
    response = RedirectResponse(url="/auth/start")
    response.set_cookie("post_auth_redirect", original_url)

    result = await ensure_token(request)
    if result:
        return result

    record = get_changelog_by_id(logid)
    username = request.cookies.get("user_name")
    email = request.cookies.get("user_id")

    code_table = request.app.state.code_table

    delete_msg = get_code_message(code_table, "Delete", record["DeleteCode"])
    program_msg = get_code_message(code_table, "Program", record["ProgramCode"])
    workshop_msg = get_code_message(code_table, "Workshop", record["WorkshopCode"])
    enroll_msg = get_code_message(code_table, "Enrollment", record["EnrollCode"])
    archive_msg = get_code_message(code_table, "Archive", record["ArchiveCode"])

    print("Delete Code ", record["DeleteCode"])
    print("Delete Msg: ", delete_msg )
    print("Workshop Code ", record["WorkshopCode"])
    print("WORKSHOP Msg ", workshop_msg )
    print("Enroll Code: ", record["EnrollCode"])
    print("Enroll Msg: ", enroll_msg)
    print("User name: ", username)
    title_text = "Review Changes"
    subtitle_text = "If advised, delete old enrollment in C365 and select Confirm"


    return templates.TemplateResponse(
        request,
        "screen3.html",
        {
            "request": request,
            "record": record,
            "username": username,
            "email": email,
            "delete_msg": delete_msg,
            "program_msg": program_msg,
            "workshop_msg": workshop_msg,
            "enroll_msg": enroll_msg,
            "archive_msg" : archive_msg,
            "title_text" : title_text,
            "subtitle_text" : subtitle_text,
        }
    )


from fastapi import Form

@router.get("/admin/delete")
async def screen3(request: Request, logid: int):
    
    # Ensure user is authenticated
    result = await ensure_token(request)
    if result:
        return result

    # MSAL identity
    username = request.cookies.get("user_name")

    # Perform deletion update
    update_user_deletion_mysql(logid, username)

    # Redirect back to Screen2
    return RedirectResponse(
        "/admin/screen4",
        status_code=303
    )

@router.get("/admin/screen4")
async def screen4(request: Request):
    # Ensure user is authenticated
    result = await ensure_token(request)
    if result:
        return result

    username = request.cookies.get("user_name")

    return templates.TemplateResponse(
        request,
        "screen4.html",
        {
            "request": request,
            "username": username
        }
    )