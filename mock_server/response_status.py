"""Interpretacion interna de estados Response IEEE 2030.5."""

DER_RESPONSE_STATUS_NAMES = {
    0: "no_status",
    1: "received",
    2: "started",
    3: "completed",
    4: "opt_out",
    5: "opt_in",
    6: "cancelled",
    7: "superseded",
    8: "partial_opt_out",
    9: "partial_opt_in",
    10: "no_participation",
    11: "test_event",
}

DER_RESPONSE_CONTROL_STATUSES = {
    1: "received",
    2: "started",
    3: "completed",
    4: "rejected",
    6: "cancelled",
    7: "superseded",
    8: "rejected",
    10: "rejected",
}


def response_status_name(response_status):
    return DER_RESPONSE_STATUS_NAMES.get(int(response_status), "unknown")


def control_status_for_response(response_status):
    return DER_RESPONSE_CONTROL_STATUSES.get(int(response_status))
