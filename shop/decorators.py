from django.http import HttpResponseForbidden
from functools import wraps
from django.conf import settings

def api_key_required(f):
    @wraps(f)
    def wrap(request, *args, **kwargs):
        api_key = request.headers.get('Authorization')
        if api_key != settings.API_KEY:
            return HttpResponseForbidden("Forbidden: Invalid API Key")
        return f(request, *args, **kwargs)
    return wrap