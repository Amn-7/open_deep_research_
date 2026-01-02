from django.conf import settings
from django.http import HttpResponse


class CorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            response = HttpResponse(status=200)
        else:
            response = self.get_response(request)

        origin = request.headers.get("Origin")
        if not origin:
            return response

        if getattr(settings, "CORS_ALLOW_ALL", False):
            response["Access-Control-Allow-Origin"] = origin
        elif origin in getattr(settings, "CORS_ALLOWED_ORIGINS", []):
            response["Access-Control-Allow-Origin"] = origin
        else:
            return response

        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response["Access-Control-Max-Age"] = "86400"
        return response
