from db import fetchall_mysql, fallback_log


def load_code_table():
    """
    Loads the entire CodeTable from MySQL into a nested dictionary:
    {
        "ENROLL": {0: "msg", 1: "msg", 2: "msg"},
        "PROGRAM": {...},
        "WORKSHOP": {...},
        "DELETE": {...},
        "ARCHIVE": {...},
        ...
    }
    """
    sql = """
        SELECT CodeType, Value, Message
        FROM CodeTable
        ORDER BY CodeType, Value;
    """

    rows = fetchall_mysql(sql)

    if not rows:
        fallback_log("CodeTable returned no rows.")
        return {}

    table = {}

    for row in rows:
        code_type = row["CodeType"]
        code_value = row["Value"]
        code_message = row["Message"]

        if code_type not in table:
            table[code_type] = {}

        table[code_type][code_value] = code_message

    return table


def get_code_message(code_table, code_type, code_value):
    """
    Returns the message for a given code_type and code_value.
    """
    try:
        return code_table[code_type][code_value]
    except KeyError:
        return f"No message found for {code_type} code {code_value}"
