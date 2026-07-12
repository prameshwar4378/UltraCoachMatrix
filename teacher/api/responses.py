from rest_framework.response import Response


def api_response(data=None, *, message="", status_code=200, meta=None):
    payload = {"success": 200 <= status_code < 400}
    if message:
        payload["message"] = message
        payload["detail"] = message
    if data:
        payload.update(data)
    if meta is not None:
        payload["meta"] = meta
    return Response(payload, status=status_code)


def list_response(results, *, meta=None, status_code=200):
    payload = {"success": True, "results": results}
    if meta is not None:
        payload["meta"] = meta
    return Response(payload, status=status_code)
