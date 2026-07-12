from rest_framework.views import exception_handler


def teacher_mobile_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    detail = ""
    errors = None
    if isinstance(data, dict):
        detail_value = data.get("detail")
        if detail_value:
            detail = str(detail_value)
        else:
            errors = data
            detail = "Request validation failed."
    else:
        detail = str(data)

    payload = {
        "success": False,
        "detail": detail,
    }
    if errors is not None:
        payload["errors"] = errors
    response.data = payload
    return response
