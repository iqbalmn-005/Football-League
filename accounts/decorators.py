from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from accounts.models import UserRole, OrganizerStatus


def _is_ajax_request(request):
    """
    Detects if an incoming request is an AJAX or JSON API invocation.
    """
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
        'application/json' in request.headers.get('accept', '').lower()
    )


def super_admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if _is_ajax_request(request):
                return JsonResponse({
                    'success': False,
                    'error': 'Session expired. Please log in to access the Super Admin Console.',
                    'redirect': f"/login/?next={request.path}"
                }, status=401)
            messages.warning(request, "Please log in to access the Super Admin Console.")
            return redirect(f"/login/?next={request.path}")

        profile = getattr(request.user, 'profile', None)
        if request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN):
            return view_func(request, *args, **kwargs)

        if _is_ajax_request(request):
            return JsonResponse({
                'success': False,
                'error': 'Access denied: Super Admin credentials required.'
            }, status=403)
        messages.error(request, "Access denied: Super Admin credentials required.")
        return redirect('/')
    return _wrapped_view


def approved_organizer_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if _is_ajax_request(request):
                return JsonResponse({
                    'success': False,
                    'error': 'Session expired or not authenticated. Please log in.',
                    'redirect': f"/login/?next={request.path}"
                }, status=401)
            messages.warning(request, "Please log in to access the Organizer Dashboard.")
            return redirect(f"/login/?next={request.path}")

        profile = getattr(request.user, 'profile', None)
        if request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN):
            return view_func(request, *args, **kwargs)

        if profile and profile.role == UserRole.ORGANIZER:
            if profile.organizer_status == OrganizerStatus.SUSPENDED:
                if _is_ajax_request(request):
                    return JsonResponse({
                        'success': False,
                        'error': 'Your account has been suspended by the platform administrator.'
                    }, status=403)
                messages.error(request, "Your account has been suspended by the platform administrator.")
                return redirect('/')
            return view_func(request, *args, **kwargs)

        if _is_ajax_request(request):
            return JsonResponse({
                'success': False,
                'error': 'Access denied: League Organizer privileges required.'
            }, status=403)
        messages.warning(request, "You need a League Organizer account to access this area.")
        return redirect('/register/')
    return _wrapped_view


