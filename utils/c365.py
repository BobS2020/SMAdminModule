# c365apis.py

import aiohttp
import json
from urllib.parse import urlencode, quote
import os
import asyncio
import time

from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------
# Classe365 API configuration
# -----------------------------------------
BASE_URL = os.getenv("C365_BASE_URL")
AUTH_HEADER = os.getenv("C365_AUTH_HEADER")

LAST_C365_CALL = 0
MIN_DELAY = 1   # seconds between ANY C365 calls

CALL_HISTORY = []
WINDOW_SECONDS = 60
MAX_CALLS_PER_WINDOW = 20   # tune this based on observation

# Global semaphore to limit concurrent Classe365 requests
classe365_lock = asyncio.Semaphore(1)


# c365apis.py

class C365CooldownException(Exception):
    """
    Raised when Classe365 rate limit is hit.
    Engines catch this and invoke status_bar.run_cooldown().
    """
    def __init__(self, retry_after: int):
        super().__init__(f"Classe365 cooldown required: {retry_after} seconds")
        self.retry_after = retry_after


# -----------------------------------------
# Throttling
# -----------------------------------------
async def throttle():
    """
    Global throttle to:
    - enforce a minimum delay between ANY Classe365 calls
    - enforce a max calls-per-window bucket
    """
    global LAST_C365_CALL, CALL_HISTORY

    now = time.time()

    # Remove calls older than the window
    CALL_HISTORY = [t for t in CALL_HISTORY if now - t < WINDOW_SECONDS]

    # If too many calls in the last 60 seconds, pause
    if len(CALL_HISTORY) >= MAX_CALLS_PER_WINDOW:
        sleep_time = WINDOW_SECONDS * 1.25
        raise C365CooldownException(retry_after=sleep_time)


    # Enforce minimum delay between calls
    wait = LAST_C365_CALL + MIN_DELAY - now
    if wait > 0:
        await asyncio.sleep(wait)

    # Record this call
    CALL_HISTORY.append(time.time())
    LAST_C365_CALL = time.time()


# -----------------------------------------
# Helpers for lockout detection
# -----------------------------------------
def _is_strong_lockout(result) -> bool:
    """
    High-confidence lockout patterns:
    - explicit 429
    - HTML
    - empty string
    - bare 'OK' (Classe365 sometimes does this)
    - error field containing '429'
    """
    # String cases
    if isinstance(result, str):
        s = result.strip()
        if not s:
            return True
        if s == "OK":
            return True
        if "429" in s:
            return True
        if "<html" in s.lower():
            return True

    # Dict cases
    if isinstance(result, dict):
        if result.get("status") == 429:
            return True
        err = result.get("error", "")
        if isinstance(err, str) and "429" in err:
            return True

    return False


def _is_ambiguous_lockout(result) -> bool:
    """
    Ambiguous patterns that *might* be lockouts:
    - empty dict
    - data is {} or []
    - None
    These can be valid for some POSTs, so we only retry a couple of times.
    """
    if result is None:
        return True

    if isinstance(result, dict):
        if result == {}:
            return True
        if "data" in result:
            data = result.get("data")
            if data == {} or data == []:
                return True

    return False


# -----------------------------------------
# Unified safe call wrapper
# -----------------------------------------
async def safe_c365_call(func, *args, **kwargs):
    """
    Wraps ANY Classe365 call (GET or POST) with:
    - global throttle
    - lockout detection
    - limited retries
    - returns the ORIGINAL result (no format changes)

    Strategy:
    - Strong lockouts: retry up to 6 times with ~60s cooldown
    - Ambiguous lockouts: retry up to 2 times with ~30s cooldown
    - Otherwise: return the original result immediately
    """

    print("safe_c365_call entered:", func.__name__)

    await throttle()

    last_result = None

    for attempt in range(6):
        async with classe365_lock:
            result = await func(*args, **kwargs)

        result_orig = result
        last_result = result_orig

       # import json
        #print("RAW C365 RESPONSE:", json.dumps(result_orig, indent=2))


        # 1. Strong lockout → always retry (up to 6 times)
        if _is_strong_lockout(result_orig):
            print(f"⚠️ Strong Classe365 lockout detected (attempt {attempt + 1}/6) — cooling down 60s...")
            #await asyncio.sleep(60)
            #await throttle()
            continue

        # 2. Ambiguous lockout → retry only a couple of times
        if _is_ambiguous_lockout(result_orig):
            if attempt < 2:
                print(f"⚠️ Possible Classe365 lockout (attempt {attempt + 1}/3) — cooling down 30s...")
                #await asyncio.sleep(30)
                #await throttle()
                continue
            else:
                # After a few tries, accept it as-is
                print("ℹ️ Ambiguous lockout pattern persisted; returning last result as-is.")
                return result_orig

        # 3. Normal case → return untouched result
        return result_orig

    print("❌ Classe365 call failed or remained locked after multiple retries; returning last result.")
    return last_result


# -----------------------------------------
# SAFE get_students() for GradeAudit
# -----------------------------------------
async def _fetch_students(scope: str = "active"):
    # Validate scope
    if scope not in ("active", "all", "alumni"):
        raise ValueError(f"Invalid student scope: {scope}")

    api_filter = {"student_type": scope}
    filter_json = json.dumps(api_filter)
    encoded_filter = quote(filter_json)

    url = f"{BASE_URL}/studentsData?acds_id=4&filter={encoded_filter}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": AUTH_HEADER
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            text = await response.text()
            try:
                return await response.json()
            except:
                return text


async def get_students(scope: str = "active"):
    """
    Safe wrapper for studentsData.
    scope = "active" | "all" | "alumni"
    Returns the 'data' list or [].
    """
    result = await safe_c365_call(_fetch_students, scope)

    if isinstance(result, dict):
        data = result.get("data", [])
        print(f"studentsData loaded ({scope}):", len(data))
        return data

    #print("studentsData returned unexpected format. RAW:")
    #print(result)
    return []


# -----------------------------------------
# get_student_info
# -----------------------------------------
async def _fetch_student_info(student_id: int):
    """
    Low-level fetch for a single student's info via studentsData filter.
    """
    filter_json = json.dumps({"student_type": "all", "id": str(student_id)})
    encoded_filter = quote(filter_json)
    url = f"{BASE_URL}/studentsData?filter={encoded_filter}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": AUTH_HEADER
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            try:
                return await resp.json()
            except:
                return text


async def get_student_info(student_id: int):
    """
    Calls Classe365 /studentsData with filter for a single student.
    Returns the 'data' list or [].
    """
    result = await safe_c365_call(_fetch_student_info, student_id)

    if isinstance(result, dict):
        return result.get("data", [])

    print("get_student_info returned unexpected format. RAW:")
    print(result)
    return []


# -----------------------------------------
# SAFE get_academic_data() for GradeAudit
# -----------------------------------------
async def _fetch_academic_data(acds_id: int = 4):
    url = f"{BASE_URL}/getAcademicDataForAll?acds_id={acds_id}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": AUTH_HEADER
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            try:
                return await resp.json()
            except:
                return text


async def get_academic_data(acds_id: int = 4):
    """
    Safe wrapper for getAcademicDataForAll.
    Returns the FULL dict so safe_c365_call can detect lockouts.
    """
    return await safe_c365_call(_fetch_academic_data, acds_id)


# -----------------------------------------
# get_student_assessment
# -----------------------------------------
async def _fetch_student_assessment(student_id: int):
    """
    Low-level fetch for studentScore.
    """
    url = f"{BASE_URL}/studentScore?id={student_id}&acds_id=4"

    headers = {
        "Content-Type": "application/json",
        "Authorization": AUTH_HEADER
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            try:
                return await resp.json()
            except:
                return text


async def get_student_assessment(student_id: int):
    """
    Safe wrapper for studentScore.
    Returns the 'data' block or {}.
    """
    result = await safe_c365_call(_fetch_student_assessment, student_id)

    if isinstance(result, dict):
        if "data" not in result:
            print("Unexpected API response format for studentScore")
            return {}
        return result["data"]

    print("get_student_assessment returned unexpected format. RAW:")
    print(result)
    return {}


# -----------------------------------------
# save_assessment_score
# -----------------------------------------
async def _post_save_assessment_score(
    student_id: int,
    acds_id: int,
    subject_id: int,
    assessment_id: int,
    score: str,
    comment: str,
    status: str,
):
    """
    Low-level POST to /saveAssessmentScore.
    Returns raw text (Classe365 sometimes returns JSON, sometimes not).
    """
    url = f"{BASE_URL}/saveAssessmentScore"

    # Classe365 expects FLAT score_data, not nested by student ID
    score_data = {
        str(student_id): {
            "score": score,
            "comment": comment,
            "status": status
        }
    }

    body = (
        f"acds_id={acds_id}"
        f"&assessment_id={assessment_id}"
        f"&subject_id={subject_id}"
        f"&score_data={json.dumps(score_data)}"
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": AUTH_HEADER
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=body.encode("utf-8")) as resp:
            text = await resp.text()
            return {"status": resp.status, "raw": text}


async def save_assessment_score(
    student_id: int,
    acds_id: int,
    subject_id: int,
    assessment_id: int,
    score: str = "0",
    comment: str = "Auto-zeroed score",
    status: str = ""
):
    """
    Correct Classe365 /saveAssessmentScore implementation.
    Routed through safe_c365_call so bulk zeroing operations
    don't trip 429 lockouts.
    Returns a dict: {"status": http_status, "response": parsed_or_raw}
    """
    result = await safe_c365_call(
        _post_save_assessment_score,
        student_id,
        acds_id,
        subject_id,
        assessment_id,
        score,
        comment,
        status,
    )

    # result is {"status": int, "raw": text}
    if not isinstance(result, dict) or "raw" not in result:
        return {"status": None, "response": {"error": "Unexpected result format", "raw": result}}

    raw = result["raw"]
    status_code = result.get("status")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"error": "Invalid JSON", "raw": raw}

    return {"status": status_code, "response": parsed}


# -----------------------------------------
# POST helpers (program change, status change, enrollment)
# -----------------------------------------
C365_BASE_URL = os.getenv("C365_BASE_URL")  # e.g. https://tenant.classe365.com


# ---------- post_student_program_change ----------
async def _post_student_program_change(form_data: dict):
    """
    Low-level POST to /student.
    """
    url = f"{C365_BASE_URL}/student"

    body = {
        "data": json.dumps(form_data)
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": AUTH_HEADER,
    }

    print("POSTING TO C365:", url)
    #print("HEADERS:", headers)
    #print("FORM DATA:", form_data)

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=body, headers=headers) as resp:
            text = await resp.text()
            print("Classe365 POST status:", resp.status)
            #print("Classe365 raw response (first 500 chars):", text[:500])
            return text


async def post_student_program_change(
    student_id: str,
    first_name: str,
    last_name: str,
    student_no: str,
    program_code: str,
):
    """
    Calls Classe365 /student using application/x-www-form-urlencoded.
    Supports program changes.
    Returns "OK" on success, or an error message string on failure.
    """

    def sanitize_payload(d: dict):
        return {k: ("" if v is None else v) for k, v in d.items()}

    form_data = {
        "id": student_id,
        "first_name": first_name,
        "last_name": last_name,
        "admission_number": student_no,
    }

    if program_code:
        form_data["select_78"] = program_code

    form_data = sanitize_payload(form_data)

    raw = await safe_c365_call(_post_student_program_change, form_data)

    try:
        data = json.loads(raw)
    except Exception:
        return f"Invalid JSON returned from Classe365: {str(raw)[:200]}"

    # Handle both legacy and modern formats
    if "response" in data:
        inner = data["response"]
        if isinstance(inner, str):
            inner = json.loads(inner)
    else:
        inner = data

    # Success formats:
    # 1️⃣ {"response":"{\"success\":true,\"error\":null}"}
    # 2️⃣ {"success":1,"id":640}
    # 3️⃣ {"success":true,"id":640}
    success_values = {1, True, "true"}
    if inner.get("success") in success_values:
        return "OK"

    err = inner.get("error")
    if err:
        return f"Classe365 error: {err}"

    return f"Unknown response from Classe365: {inner}"


# ---------- post_student_oba_status_change ----------
async def _post_student_oba_status_change(form_data: dict):
    """
    Low-level POST to /student for OBA status changes.
    """
    url = f"{C365_BASE_URL}/student"

    body = {
        "data": json.dumps(form_data)
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": AUTH_HEADER,
    }

    print("POSTING TO C365:", url)
    #print("HEADERS:", headers)
    #print("FORM DATA:", form_data)

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=body, headers=headers) as resp:
            text = await resp.text()
            print("Classe365 POST status:", resp.status)
            #print("Classe365 raw response (first 500 chars):", text[:500])
            return text


async def post_student_oba_status_change(
    student_id: str,
    first_name: str,
    last_name: str,
    student_no: str,
    student_status: str,
):
    """
    Calls Classe365 /student using application/x-www-form-urlencoded.
    Supports OBA status changes.
    Returns "OK" on success, or an error message string on failure.
    """

    def sanitize_payload(d: dict):
        return {k: ("" if v is None else v) for k, v in d.items()}

    form_data = {
        "id": student_id,
        "first_name": first_name,
        "last_name": last_name,
        "admission_number": student_no,
    }

    if student_status:
        form_data["select_65"] = student_status

    form_data = sanitize_payload(form_data)

    raw = await safe_c365_call(_post_student_oba_status_change, form_data)

    try:
        data = json.loads(raw)
    except Exception:
        return f"Invalid JSON returned from Classe365: {str(raw)[:200]}"

    if "response" in data:
        inner = data["response"]
        if isinstance(inner, str):
            inner = json.loads(inner)
    else:
        inner = data

    success_values = {1, True, "true"}
    if inner.get("success") in success_values:
        return "OK"

    err = inner.get("error")
    if err:
        return f"Classe365 error: {err}"

    return f"Unknown response from Classe365: {inner}"


# ---------- post_new_enrollment ----------
async def _post_new_enrollment(form_data: dict):
    """
    Low-level POST to /studentCourseEnroll.
    """
    url = f"{C365_BASE_URL}/studentCourseEnroll"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": AUTH_HEADER,
    }

    print("POSTING TO C365:", url)
    #print("HEADERS:", headers)
    #print("FORM DATA:", form_data)

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=form_data, headers=headers) as resp:
            text = await resp.text()
            print("Classe365 POST status:", resp.status)
            #print("Classe365 raw response (first 500 chars):", text[:500])
            return text


async def post_new_enrollment(
    acds_id: int,
    student_id: int,
    class_id: int,
    section_id: int,
):
    """
    Adds an enrollment for a student via /studentCourseEnroll.
    Returns "OK" on success, or an error message string on failure.
    """

    form_data = {
        "acds_id": acds_id,
        "student_id": student_id,
        "class_id": class_id,
        "section_id": section_id,
    }

    raw = await safe_c365_call(_post_new_enrollment, form_data)

    try:
        data = json.loads(raw)
    except Exception:
        return f"Invalid JSON returned from Classe365: {str(raw)[:200]}"

    if "response" in data:
        inner = data["response"]
        if isinstance(inner, str):
            inner = json.loads(inner)
    else:
        inner = data

    success_values = {1, True, "true"}
    if inner.get("success") in success_values:
        return "OK"

    err = inner.get("error")
    if err:
        return f"Classe365 error: {err}"

    return f"Unknown response from Classe365: {inner}"


# ---------- post_C365_status_change ----------
async def _post_C365_status_change(form_data: dict):
    """
    Low-level POST to /studentStatusUpdate for a single student.
    """
    url = f"{C365_BASE_URL}/studentStatusUpdate"
    headers = {
        "Authorization": AUTH_HEADER,  # no explicit Content-Type
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=form_data, headers=headers) as resp:
            text = await resp.text()
            print("Classe365 POST status:", resp.status)
            #print("Classe365 raw response (first 500 chars):", text[:500])
            return text


async def post_C365_status_change(student_id: int, status: str):
    """
    Updates one student's status in Classe365.
    """
    form_data = {
        "student_ids": str(student_id),
        "status": status,
    }

    raw = await safe_c365_call(_post_C365_status_change, form_data)

    try:
        data = json.loads(raw)
    except Exception:
        return f"Invalid JSON returned from Classe365: {str(raw)[:200]}"

    inner = data.get("response", data)
    if isinstance(inner, str):
        inner = json.loads(inner)

    if inner.get("success") in (1, True, "true"):
        return "OK"

    err = inner.get("error")
    if err:
        return f"Classe365 error: {err}"

    return f"Unknown response from Classe365: {inner}"

# -----------------------------------------
# subjectScore (safe-wrapped)
# -----------------------------------------
async def _fetch_subject_scores(subject_id, acds_id=4):
    base_url = os.getenv("C365_BASE_URL")
    auth_header = os.getenv("C365_AUTH_HEADER")

    url = f"{base_url}/subjectScore"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }
    params = {
        "id": subject_id,
        "acds_id": acds_id
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
            except:
                return text
            return data


async def get_subject_scores(subject_id, acds_id=4):
    """
    Safe wrapper for subjectScore API.
    Uses safe_c365_call() for throttling, retries, and 429 handling.
    Returns whatever the endpoint returns (dict or string).
    """
    result = await safe_c365_call(_fetch_subject_scores, subject_id, acds_id)
    return result

