from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import UserProfile, UserRole, OrganizerStatus, OrganizerApplication, ActivityLog, Notification, PlatformSetting


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard_dispatch')

    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        identifier = request.POST.get('phone') or request.POST.get('username') or request.POST.get('identifier') or ''
        password = request.POST.get('password', '')
        remember = request.POST.get('remember')

        identifier = identifier.strip()
        user = authenticate(request, username=identifier, password=password)

        if user is not None:
            profile = getattr(user, 'profile', None)
            if profile and profile.organizer_status == OrganizerStatus.SUSPENDED:
                messages.error(request, "Your account has been suspended by the platform administrator.")
                return render(request, 'login.html', {'identifier': identifier})

            login(request, user)
            if not remember:
                request.session.set_expiry(0)  # Browser close expiry
            else:
                request.session.set_expiry(1209600)  # 2 weeks

            ActivityLog.log('USER_LOGIN', f"User {user.username} logged in.", user=user, ip=get_client_ip(request))

            # Role-based redirection:
            # Organizers and Super Admins ALWAYS go directly to their respective dashboards, never to landing page
            if user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN):
                if next_url and next_url.startswith('/super-admin/'):
                    return redirect(next_url)
                return redirect('super_admin_dashboard')

            if profile and profile.role == UserRole.ORGANIZER:
                if next_url and (next_url.startswith('/organizer/') or next_url == '/organizer.html'):
                    return redirect(next_url)
                return redirect('organizer_dashboard')

            if next_url and next_url != '/' and not next_url.startswith('/?'):
                return redirect(next_url)
            return redirect('landing_page')
        else:
            messages.error(request, "Invalid phone number, username, or password.")
            return render(request, 'login.html', {'identifier': identifier, 'error': 'Invalid credentials.'})

    return render(request, 'login.html', {'next': next_url})


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard_dispatch')

    setting = PlatformSetting.get_settings()

    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', UserRole.ORGANIZER).upper()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not phone or not password:
            messages.error(request, "Phone number and password are required.")
            return render(request, 'registration.html', {'phone': phone, 'full_name': full_name, 'role': role})

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'registration.html', {'phone': phone, 'full_name': full_name, 'role': role})

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return render(request, 'registration.html', {'phone': phone, 'full_name': full_name, 'role': role})

        # Check existing user
        username = phone
        if User.objects.filter(username=username).exists() or UserProfile.objects.filter(phone=phone).exists():
            messages.error(request, "An account with this phone number already exists.")
            return render(request, 'registration.html', {'phone': phone, 'full_name': full_name, 'role': role})

        # Split full name
        first_name, last_name = "", ""
        if full_name:
            parts = full_name.split(None, 1)
            first_name = parts[0]
            if len(parts) > 1:
                last_name = parts[1]

        target_role = UserRole.ORGANIZER if role == 'ORGANIZER' else UserRole.VIEWER
        if target_role == UserRole.ORGANIZER and not setting.allow_organizer_registration:
            messages.warning(request, "Organizer registration is temporarily paused. Registered as viewer.")
            target_role = UserRole.VIEWER

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        profile = user.profile
        profile.phone = phone
        profile.role = target_role
        profile.organizer_status = OrganizerStatus.PENDING if target_role == UserRole.ORGANIZER else OrganizerStatus.NOT_APPLIED
        profile.save()

        ActivityLog.log('USER_REGISTER', f"New user registered: {username} as {target_role}.", user=user, ip=get_client_ip(request))

        login(request, user, backend='accounts.backends.PhoneOrUsernameBackend')

        if target_role == UserRole.ORGANIZER:
            messages.success(request, f"Welcome to Touchline, {user.first_name or user.username}! You can now create your league and submit it for review.")
            return redirect('organizer_dashboard')

        messages.success(request, f"Welcome to Touchline, {user.first_name or user.username}!")
        return redirect('landing_page')

    return render(request, 'registration.html')


def logout_view(request):
    if request.user.is_authenticated:
        ActivityLog.log('USER_LOGOUT', f"User {request.user.username} logged out.", user=request.user, ip=get_client_ip(request))
        logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('landing_page')


@login_required
def dashboard_dispatch(request):
    profile = getattr(request.user, 'profile', None)
    if request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN):
        return redirect('super_admin_dashboard')

    if profile and profile.role == UserRole.ORGANIZER:
        return redirect('organizer_dashboard')

    return redirect('landing_page')


@login_required
def organizer_apply_view(request):
    profile = request.user.profile
    # If already organizer, go to dashboard
    if profile.role == UserRole.ORGANIZER:
        return redirect('organizer_dashboard')

    latest_app = OrganizerApplication.objects.filter(applicant=request.user).first()

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip() or request.user.get_full_name() or request.user.username
        organization_name = request.POST.get('organization_name', '').strip()
        email = request.POST.get('email', '').strip() or request.user.email
        phone = request.POST.get('phone', '').strip() or profile.phone
        city = request.POST.get('city', '').strip()
        country = request.POST.get('country', 'United Kingdom').strip()
        experience_years = int(request.POST.get('experience_years', 1) or 1)
        experience_summary = request.POST.get('experience_summary', '').strip()
        proposed_leagues = request.POST.get('proposed_leagues', '').strip()

        if not organization_name or not city:
            messages.error(request, "Organization name and City are required.")
            return render(request, 'organizer_apply.html', {'latest_app': latest_app, 'profile': profile})

        app = OrganizerApplication.objects.create(
            applicant=request.user,
            full_name=full_name,
            organization_name=organization_name,
            email=email,
            phone=phone,
            city=city,
            country=country,
            experience_years=experience_years,
            experience_summary=experience_summary,
            proposed_leagues=proposed_leagues,
            status=OrganizerApplication.Status.PENDING
        )

        profile.role = UserRole.ORGANIZER
        profile.organization_name = organization_name
        profile.experience_years = experience_years
        profile.organizer_status = OrganizerStatus.PENDING
        profile.rejection_reason = ""
        profile.save()

        # Update user names
        if full_name:
            parts = full_name.split(None, 1)
            request.user.first_name = parts[0]
            if len(parts) > 1:
                request.user.last_name = parts[1]
            if email and not request.user.email:
                request.user.email = email
            request.user.save()

        ActivityLog.log('APPLICATION_SUBMITTED', f"{request.user.username} submitted application for {organization_name}.", user=request.user, ip=get_client_ip(request))

        Notification.objects.create(
            recipient=request.user,
            title="Application Submitted",
            message=f"Your organizer application for '{organization_name}' has been submitted and is under review by Super Admin.",
            notification_type="APPLICATION"
        )

        messages.success(request, "Your application has been submitted for Super Admin review.")
        return redirect('organizer_status')

    return render(request, 'organizer_apply.html', {'latest_app': latest_app, 'profile': profile})


@login_required
def organizer_status_view(request):
    profile = request.user.profile
    latest_app = OrganizerApplication.objects.filter(applicant=request.user).first()

    return render(request, 'organizer_status.html', {
        'profile': profile,
        'latest_app': latest_app,
        'status': profile.organizer_status
    })
