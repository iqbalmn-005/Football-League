from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Count, Q

from accounts.decorators import super_admin_required
from accounts.models import (
    UserProfile, UserRole, OrganizerStatus, OrganizerApplication,
    ActivityLog, Notification, PlatformSetting
)
from leagues.models import Competition, CompetitionAssignment, TournamentGroup, CompetitionStatus
from teams.models import Team, Player
from matches.models import Match, MatchStatus


@super_admin_required
def super_admin_dashboard(request):
    tab = request.GET.get('tab', 'overview')

    # Metrics
    total_users = User.objects.count()
    total_organizers = UserProfile.objects.filter(role=UserRole.ORGANIZER).count()
    approved_organizers_count = UserProfile.objects.filter(
        role=UserRole.ORGANIZER, organizer_status=OrganizerStatus.APPROVED
    ).count()
    pending_applications = OrganizerApplication.objects.filter(status=OrganizerApplication.Status.PENDING)
    pending_count = pending_applications.count()

    active_competitions_count = Competition.objects.filter(status='ACTIVE').count()
    total_competitions_count = Competition.objects.count()
    total_teams_count = Team.objects.count()
    total_players_count = Player.objects.count()
    total_matches_count = Match.objects.count()
    completed_matches_count = Match.objects.filter(status=MatchStatus.COMPLETED).count()

    # Lists for tabs
    applications = OrganizerApplication.objects.select_related('applicant', 'applicant__profile').order_by('-created_at')
    competitions = Competition.objects.select_related('primary_organizer', 'created_by').prefetch_related('teams').all()
    organizers = User.objects.filter(profile__role=UserRole.ORGANIZER).select_related('profile').order_by('-date_joined')
    approved_organizers = User.objects.filter(
        profile__role=UserRole.ORGANIZER, profile__organizer_status=OrganizerStatus.APPROVED, profile__is_active_organizer=True
    ).select_related('profile')

    teams = Team.objects.prefetch_related('players', 'competitions').order_by('name')
    players = Player.objects.select_related('team').order_by('-created_at')[:50]
    activity_logs = ActivityLog.objects.select_related('user').order_by('-created_at')[:100]
    platform_settings = PlatformSetting.get_settings()

    context = {
        'active_tab': tab,
        'total_users': total_users,
        'total_organizers': total_organizers,
        'approved_organizers_count': approved_organizers_count,
        'pending_count': pending_count,
        'active_competitions_count': active_competitions_count,
        'total_competitions_count': total_competitions_count,
        'total_teams_count': total_teams_count,
        'total_players_count': total_players_count,
        'total_matches_count': total_matches_count,
        'completed_matches_count': completed_matches_count,
        'applications': applications,
        'competitions': competitions,
        'organizers': organizers,
        'approved_organizers': approved_organizers,
        'teams': teams,
        'players': players,
        'activity_logs': activity_logs,
        'platform_settings': platform_settings,
    }
    return render(request, 'super_admin.html', context)


@super_admin_required
def approve_application(request, app_id):
    if request.method == 'POST':
        app = get_object_or_404(OrganizerApplication, id=app_id)
        app.status = OrganizerApplication.Status.APPROVED
        app.reviewed_by = request.user
        app.reviewed_at = timezone.now()
        app.save()

        # Update applicant's profile
        profile = app.applicant.profile
        profile.role = UserRole.ORGANIZER
        profile.organizer_status = OrganizerStatus.APPROVED
        profile.is_active_organizer = True
        profile.organization_name = app.organization_name
        profile.experience_years = app.experience_years
        profile.rejection_reason = ""
        profile.save()

        # Activate any pending competitions submitted by this applicant
        Competition.objects.filter(
            created_by=app.applicant,
            status=CompetitionStatus.PENDING
        ).update(status=CompetitionStatus.ACTIVE, is_published=True)

        ActivityLog.log(
            'APPLICATION_APPROVED',
            f"Super Admin {request.user.username} approved organizer application for {app.organization_name} ({app.applicant.username}).",
            user=request.user
        )

        Notification.objects.create(
            recipient=app.applicant,
            title="Application Approved!",
            message=f"Congratulations! Your organizer application for '{app.organization_name}' has been approved by Super Admin. You can now access your Organizer Dashboard.",
            notification_type="SUCCESS",
            link="/organizer/"
        )

        messages.success(request, f"Application for '{app.organization_name}' approved successfully!")
    return redirect('/super-admin/?tab=approvals')


@super_admin_required
def reject_application(request, app_id):
    if request.method == 'POST':
        app = get_object_or_404(OrganizerApplication, id=app_id)
        reason = request.POST.get('rejection_reason', 'Criteria not met or incomplete details provided.').strip()

        app.status = OrganizerApplication.Status.REJECTED
        app.rejection_reason = reason
        app.reviewed_by = request.user
        app.reviewed_at = timezone.now()
        app.save()

        profile = app.applicant.profile
        profile.organizer_status = OrganizerStatus.REJECTED
        profile.rejection_reason = reason
        profile.save()

        ActivityLog.log(
            'APPLICATION_REJECTED',
            f"Super Admin rejected organizer application for {app.organization_name}. Reason: {reason}",
            user=request.user
        )

        Notification.objects.create(
            recipient=app.applicant,
            title="Application Update",
            message=f"Your organizer application for '{app.organization_name}' was not approved. Reason: {reason}",
            notification_type="WARNING",
            link="/organizer/status/"
        )

        messages.info(request, f"Application for '{app.organization_name}' has been rejected.")
    return redirect('/super-admin/?tab=approvals')


@super_admin_required
def toggle_organizer_status(request, user_id):
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        profile = target_user.profile

        if profile.organizer_status == OrganizerStatus.SUSPENDED:
            profile.organizer_status = OrganizerStatus.APPROVED
            profile.is_active_organizer = True
            action_desc = "reactivated"
        else:
            profile.organizer_status = OrganizerStatus.SUSPENDED
            profile.is_active_organizer = False
            action_desc = "suspended"

        profile.save()

        ActivityLog.log(
            f"ORGANIZER_{action_desc.upper()}",
            f"Organizer {target_user.username} was {action_desc} by Super Admin.",
            user=request.user
        )

        messages.success(request, f"Organizer {target_user.username} has been {action_desc}.")
    return redirect('/super-admin/?tab=organizers')


@super_admin_required
def create_competition(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        comp_type = request.POST.get('competition_type', 'LEAGUE')
        tourn_format = request.POST.get('tournament_format', 'ROUND_ROBIN')
        category = request.POST.get('category', '11-a-side')
        season = request.POST.get('season', '2026/2027').strip()
        location = request.POST.get('location', 'London, UK').strip()
        max_teams = int(request.POST.get('max_teams', 8) or 8)
        description = request.POST.get('description', '').strip()
        organizer_id = request.POST.get('organizer_id')
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        logo_url = request.POST.get('logo_url', '').strip()

        if not name:
            messages.error(request, "Competition name is required.")
            return redirect('/super-admin/?tab=leagues')

        assigned_organizer = None
        if organizer_id:
            assigned_organizer = User.objects.filter(id=organizer_id).first()

        comp = Competition.objects.create(
            name=name,
            competition_type=comp_type,
            tournament_format=tourn_format,
            category=category,
            season=season,
            location=location,
            max_teams=max_teams,
            description=description,
            primary_organizer=assigned_organizer,
            created_by=request.user,
            start_date=start_date,
            end_date=end_date,
            logo_url=logo_url or "/static/img/mfl.jpeg",
            status='ACTIVE',
            is_published=True
        )

        # Handle logo upload if provided
        if 'logo' in request.FILES:
            comp.logo = request.FILES['logo']
            comp.save()

        if assigned_organizer:
            CompetitionAssignment.objects.get_or_create(
                competition=comp,
                organizer=assigned_organizer,
                defaults={'assigned_by': request.user, 'role': CompetitionAssignment.Role.PRIMARY}
            )

        ActivityLog.log('LEAGUE_CREATED', f"Created competition '{name}' ({season}).", user=request.user)
        messages.success(request, f"Competition '{name}' created successfully!")
    return redirect('/super-admin/?tab=leagues')


@super_admin_required
def assign_competition(request, comp_id):
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        organizer_id = request.POST.get('organizer_id')
        role = request.POST.get('role', CompetitionAssignment.Role.PRIMARY)

        organizer = get_object_or_404(User, id=organizer_id)

        assignment, created = CompetitionAssignment.objects.update_or_create(
            competition=competition,
            organizer=organizer,
            defaults={
                'assigned_by': request.user,
                'role': role,
                'can_edit_fixtures': True,
                'can_enter_results': True,
                'can_manage_teams': True
            }
        )

        if role == CompetitionAssignment.Role.PRIMARY:
            competition.primary_organizer = organizer
            competition.save()

        ActivityLog.log(
            'COMPETITION_ASSIGNED',
            f"Assigned competition '{competition.name}' to organizer {organizer.username} ({role}).",
            user=request.user
        )

        Notification.objects.create(
            recipient=organizer,
            title="Competition Assigned",
            message=f"You have been assigned as {role} for '{competition.name}'.",
            notification_type="COMPETITION",
            link=f"/organizer/{competition.id}/"
        )

        messages.success(request, f"Assigned '{competition.name}' to {organizer.username} successfully!")
    return redirect('/super-admin/?tab=leagues')


@super_admin_required
def transfer_competition(request, comp_id):
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        new_organizer_id = request.POST.get('new_organizer_id')
        new_organizer = get_object_or_404(User, id=new_organizer_id)

        old_organizer = competition.primary_organizer

        # Update primary organizer
        competition.primary_organizer = new_organizer
        competition.save()

        # Update assignments
        CompetitionAssignment.objects.filter(competition=competition, role=CompetitionAssignment.Role.PRIMARY).delete()
        CompetitionAssignment.objects.update_or_create(
            competition=competition,
            organizer=new_organizer,
            defaults={'assigned_by': request.user, 'role': CompetitionAssignment.Role.PRIMARY}
        )

        old_name = old_organizer.username if old_organizer else "None"
        ActivityLog.log(
            'COMPETITION_TRANSFERRED',
            f"Transferred '{competition.name}' from {old_name} to {new_organizer.username}.",
            user=request.user
        )

        Notification.objects.create(
            recipient=new_organizer,
            title="Competition Transferred to You",
            message=f"'{competition.name}' management has been transferred to you by Super Admin.",
            notification_type="COMPETITION",
            link=f"/organizer/{competition.id}/"
        )

        messages.success(request, f"Competition '{competition.name}' transferred to {new_organizer.username}!")
    return redirect('/super-admin/?tab=organizers')


@super_admin_required
def update_platform_settings(request):
    if request.method == 'POST':
        settings_obj = PlatformSetting.get_settings()
        settings_obj.platform_name = request.POST.get('platform_name', settings_obj.platform_name).strip()
        settings_obj.tagline = request.POST.get('tagline', settings_obj.tagline).strip()
        settings_obj.contact_email = request.POST.get('contact_email', settings_obj.contact_email).strip()
        settings_obj.allow_organizer_registration = 'allow_organizer_registration' in request.POST
        settings_obj.auto_publish_fixtures = 'auto_publish_fixtures' in request.POST
        settings_obj.save()

        ActivityLog.log('SETTINGS_UPDATED', "Platform settings were updated by Super Admin.", user=request.user)
        messages.success(request, "Platform settings updated successfully!")
    return redirect('/super-admin/?tab=settings')


@super_admin_required
def approve_competition(request, comp_id):
    if request.method == 'POST':
        comp = get_object_or_404(Competition, id=comp_id)
        comp.status = CompetitionStatus.ACTIVE
        comp.is_published = True
        comp.save()

        if comp.created_by and hasattr(comp.created_by, 'profile'):
            comp.created_by.profile.role = UserRole.ORGANIZER
            comp.created_by.profile.organizer_status = OrganizerStatus.APPROVED
            comp.created_by.profile.is_active_organizer = True
            comp.created_by.profile.save()

        # Mark any pending application as approved
        OrganizerApplication.objects.filter(
            applicant=comp.created_by,
            status=OrganizerApplication.Status.PENDING
        ).update(status=OrganizerApplication.Status.APPROVED, reviewed_by=request.user, reviewed_at=timezone.now())

        ActivityLog.log('LEAGUE_APPROVED', f"Super Admin {request.user.username} approved league '{comp.name}'.", user=request.user)
        messages.success(request, f"League '{comp.name}' approved and activated successfully!")
    return redirect('/super-admin/?tab=competitions')


