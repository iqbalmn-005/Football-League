from django.http import JsonResponse
from leagues.public_views import custom_404_view, custom_500_view


def _is_api_request(request):
    return (
        request.path.startswith('/api/') or
        '/api/' in request.path or
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in request.headers.get('accept', '').lower() or
        'application/json' in (getattr(request, 'content_type', '') or '').lower()
    )


class CustomErrorPageMiddleware:
    """
    Ensures Futbolix's branded 404 and 500 error pages are rendered consistently
    across both development (DEBUG=True) and production (DEBUG=False) modes,
    while preserving or returning JSON responses for API calls.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Preserve JSON API responses and static/media files
        content_type = response.headers.get('content-type', '').lower()
        if 'application/json' in content_type:
            return response

        # Skip Django admin internals
        if request.path.startswith('/admin/'):
            return response

        # Intercept 404 Not Found
        if response.status_code == 404:
            if _is_api_request(request):
                return JsonResponse({'success': False, 'errors': ['Requested API endpoint or resource was not found (404).']}, status=404)
            return custom_404_view(request)

        # Intercept 500 Internal Server Error
        if response.status_code == 500:
            if _is_api_request(request):
                return JsonResponse({'success': False, 'errors': ['An internal server error occurred while processing the request (500).']}, status=500)
            return custom_500_view(request)

        return response
