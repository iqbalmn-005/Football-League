from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from accounts.models import UserRole, OrganizerStatus


def super_admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, "Please log in to access the Super Admin Console.")
            return redirect(f"/login/?next={request.path}")

        profile = getattr(request.user, 'profile', None)
        if request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN):
            return view_func(request, *args, **kwargs)

        messages.error(request, "Access denied: Super Admin credentials required.")
        return redirect('/')
    return _wrapped_view


def approved_organizer_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, "Please log in to access the Organizer Dashboard.")
            return redirect(f"/login/?next={request.path}")

        profile = getattr(request.user, 'profile', None)
        if request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN):
            return view_func(request, *args, **kwargs)

        if profile and profile.role == UserRole.ORGANIZER:
            if profile.organizer_status == OrganizerStatus.SUSPENDED:
                messages.error(request, "Your account has been suspended by the platform administrator.")
                return redirect('/')
            return view_func(request, *args, **kwargs)

        messages.warning(request, "You need a League Organizer account to access this area.")
        return redirect('/register/')
    return _wrapped_view

