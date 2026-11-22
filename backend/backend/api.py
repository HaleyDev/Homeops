from rest_framework import status
from rest_framework.response import Response


def ok(data=None, message="OK", status_code=status.HTTP_200_OK):
    return Response(
        {"code": 0, "data": data, "message": message},
        status=status_code,
    )


class ApiResponseMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if 200 <= response.status_code < 300 and not (
            isinstance(response.data, dict) and "code" in response.data
        ):
            response.data = {"code": 0, "data": response.data, "message": "OK"}
        return response
