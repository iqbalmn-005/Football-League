from leagues.public_views import custom_404_view, custom_500_view


class CustomErrorPageMiddleware:
    """
    Ensures Futbolix's branded 404 and 500 error pages are rendered consistently
    across both development (DEBUG=True) and production (DEBUG=False) modes,
    while preserving raw JSON responses for API calls.
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
            if request.path.startswith('/api/') or request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return response
            return custom_404_view(request)

        # Intercept 500 Internal Server Error
        if response.status_code == 500:
            if request.path.startswith('/api/') or request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return response
            return custom_500_view(request)

        return response
