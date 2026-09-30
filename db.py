import mysql.connector
from mysql.connector import Error
import os
from datetime import datetime


def fallback_log(message):
    try:
        with open("error_fallback.log", "a") as f:
            f.write(f"{datetime.now()} - {message}\n")
    except:
        pass


# ---------------------------------------------------------
# Helper: get MySQL connection for StudentChanges DB
# ---------------------------------------------------------
def _get_conn():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME_STUDENTCHANGES")
    )


# ---------------------------------------------------------
# 1. INSERT INTO StudentChangeLog
# ---------------------------------------------------------
def insert_change_log(payload):
    """
    Inserts a new row into StudentChangeLog.
    Returns the new LogId (int) or None on error.
    """

    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        sql = """
            INSERT INTO StudentChangeLog
            (StudentNo, C365Id, FirstName, LastName, Date,
             RequestedBy, ChangeFrom, ChangeTo, ChangeNotes,
             AddMade, ByUser, DeleteDone, Admin, AdminNotes,
             CohortToDelete, QtrToClose, CreatedAt, UpdatedAt,
             ProgramFrom, ProgramTo)
            VALUES (%s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s)
        """

        values = (
            payload.get("StudentNo"),
            payload.get("C365Id"),
            payload.get("FirstName"),
            payload.get("LastName"),
            payload.get("Date"),
            payload.get("RequestedBy"),
            payload.get("ChangeFrom"),
            payload.get("ChangeTo"),
            payload.get("ChangeNotes"),
            payload.get("AddMade"),
            payload.get("ByUser"),
            payload.get("DeleteDone"),
            payload.get("Admin"),
            payload.get("AdminNotes"),
            payload.get("CohortToDelete"),
            payload.get("QtrToClose"),
            payload.get("CreatedAt"),
            payload.get("UpdatedAt"),
            payload.get("ProgramFrom"),
            payload.get("ProgramTo"),
        )

        cursor.execute(sql, values)
        conn.commit()

        return cursor.lastrowid

    except Error as e:
        fallback_log(f"MySQL insert_change_log error: {e}")
        #print("MySQL insert_change_log error:", e)
        return None

    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------
# 2. INSERT INTO ChangeStatusRecord
# ---------------------------------------------------------
def insert_status_record(payload):
    """
    Inserts a new row into ChangeStatusRecord.
    Returns True on success, False on error.
    """

    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        sql = """
            INSERT INTO ChangeStatusRecord
            (LogId, Version, ArchiveCode, ProgramCode,
             EnrollCode, DeleteCode, WorkshopCode,
             QtrToClose, StatusDate)
            VALUES (%s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s)
        """

        values = (
            payload.get("LogId"),
            payload.get("Version"),
            payload.get("ArchiveCode"),
            payload.get("ProgramCode"),
            payload.get("EnrollCode"),
            payload.get("DeleteCode"),
            payload.get("WorkshopCode"),
            payload.get("QtrToClose"),
            payload.get("StatusDate"),
        )

        cursor.execute(sql, values)
        conn.commit()

        return True

    except Error as e:
        fallback_log(f"MySQL insert_status_record error: {e}")
        print("MySQL insert_status_record error:", e)
        return False

    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------
# 3. INSERT INTO EventLog
# ---------------------------------------------------------
def insert_event_log(payload):
    """
    Inserts a new row into EventLog.
    Returns True on success, False on error.
    """

    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        sql = """
            INSERT INTO EventLog
            (LogId, EventDate, EventType, EventMessage, SMVersion)
            VALUES (%s, %s, %s, %s, %s)
        """



        values = (
            payload.get("LogId"),
            payload.get("EventDate"),
            payload.get("EventType"),
            payload.get("EventMessage"),
            payload.get("SMVersion"),
        )

        print("Log ID:", payload.get("LogId") )
        print("EventType: ", payload.get("EventType"))
        print("Error Message: ", payload.get("EventMessage"))

        cursor.execute(sql, values)
        conn.commit()

        return True

    except Error as e:
        fallback_log(f"MySQL insert_event_log error: {e}")
        return False

    finally:
        if conn:
            conn.close()

def update_event_logs_with_log_id(log_id):
    """
    Attach all pre-commit logs (LogId = 0) to the real LogId
    after the StudentChanges record is created.
    """

    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor()
    
        sql = """
            UPDATE EventLog
            SET LogId = %s
            WHERE LogId = 0
        """
        cursor = conn.cursor()
        cursor.execute(sql, (log_id,))
        conn.commit()

    except Error as e:
        fallback_log(f"MySQL update_event_logs_with_log_id error: {e}")
        #print("MySQL insert_event_log error:", e)
        return False

    finally:
        if conn:
            conn.close()

def update_user_deletion_mysql(log_id, username):
    """
    Correctly updates deletion fields in StudentChangeLog.
    """

    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        # 1. Update StudentChangeLog
        sql1 = """
            UPDATE StudentChangeLog
            SET DeleteDone = NOW(),
                Admin = %s                
            WHERE LogId = %s;
        """
        
        cursor.execute(sql1, (username, log_id))

        conn.commit()
        return True

    except Exception as e:
        print("MySQL deletion update error:", e)
        return False

    finally:
        if conn:
            conn.close()


def run_mysql(sql, params=None):
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        conn.commit()
        return True

    except Error as e:
        fallback_log(f"MySQL error: {e}")
        return False

    finally:
        if conn:
            conn.close()

        
def fetchall_mysql(sql, params=None):
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor(dictionary=True)

        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        rows = cursor.fetchall()
        return rows

    except Error as e:
        fallback_log(f"MySQL SELECT error: {e}")
        return []

    finally:
        if conn:
            conn.close()


def get_changelog_entries(mode=None, name=None, qtr=None):
    """
    Returns a list of change log entries filtered by mode, name, or quarter.
    Used by Admin Screen2.
    """

    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor(dictionary=True)

        sql = """
            SELECT 
                scl.LogId,
                scl.StudentNo,
                scl.FirstName,
                scl.LastName,
                scl.Date,
                scl.RequestedBy,
                scl.ChangeFrom,
                scl.ChangeTo,
                scl.ChangeNotes,
                scl.AddMade,
                scl.ByUser,
                scl.DeleteDone,
                scl.Admin,
                scl.AdminNotes,
                scl.CohortToDelete,
                scl.QtrToClose,
                csr.ArchiveCode,
                csr.ProgramCode,
                csr.EnrollCode,
                csr.DeleteCode,
                csr.WorkshopCode,
                csr.QtrToClose AS StatusQtr
            FROM StudentChangeLog scl
            LEFT JOIN ChangeStatusRecord csr
                ON scl.LogId = csr.LogId
            WHERE 1=1
        """

        params = []

        # Mode filter
        if mode:
            sql += " AND (csr.ArchiveCode = %s OR csr.ProgramCode = %s OR csr.EnrollCode = %s OR csr.DeleteCode = %s OR csr.WorkshopCode = %s)"
            params.extend([mode, mode, mode, mode, mode])

        # Name filter
        if name:
            sql += " AND (scl.FirstName LIKE %s OR scl.LastName LIKE %s)"
            params.extend([f"%{name}%", f"%{name}%"])

        # Quarter filter
        if qtr:
            sql += " AND (scl.QtrToClose = %s OR scl.CohortToDelete = %s)"
            params.extend([qtr, qtr])

        sql += " ORDER BY scl.LogId DESC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return rows

    except Error as e:
        fallback_log(f"MySQL get_changelog_entries error: {e}")
        return []

    finally:
        if conn:
            conn.close()

def get_changelog_by_id(logid):
    """
    Returns a single change log record with status + event logs.
    Used by Admin Screen3.
    """

    conn = None
    try:
        conn = _get_conn()
        cursor = conn.cursor(dictionary=True)

        # Main record
        sql_main = """
            SELECT 
                scl.*,
                csr.ArchiveCode,
                csr.ProgramCode,
                csr.EnrollCode,
                csr.DeleteCode,
                csr.WorkshopCode,
                csr.QtrToClose AS StatusQtr
            FROM StudentChangeLog scl
            LEFT JOIN ChangeStatusRecord csr
                ON scl.LogId = csr.LogId
            WHERE scl.LogId = %s
        """

        cursor.execute(sql_main, (logid,))
        record = cursor.fetchone()

        if not record:
            return None

        # Event logs
        sql_events = """
            SELECT *
            FROM EventLog
            WHERE LogId = %s
            ORDER BY EventDate DESC
        """

        cursor.execute(sql_events, (logid,))
        events = cursor.fetchall()

        record["events"] = events
        return record

    except Error as e:
        fallback_log(f"MySQL get_changelog_by_id error: {e}")
        return None

    finally:
        if conn:
            conn.close()


