from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Count
from datetime import datetime, date, time
import json

from accounts.decorators import approved_organizer_required
from accounts.models import ActivityLog, Notification, UserProfile, UserRole, OrganizerStatus, OrganizerApplication
from leagues.models import Competition, CompetitionAssignment, CompetitionTeam, TournamentGroup, CompetitionStatus
from teams.models import Team, Player, PositionChoice
from matches.models import Match, MatchEvent, MatchEventType, MatchStatus
from standings.models import StandingEntry
from standings.services import recalculate_competition_standings
from fixtures.services import generate_round_robin_fixtures, advance_knockout_bracket
from matches.services import get_competition_statistics
from teams.views import delete_team_view


def get_organizer_competitions(user):
    """
    Returns all competitions this organizer is assigned to or created.
    Super admins see all competitions.
    """
    if user.is_superuser or (hasattr(user, 'profile') and user.profile.is_super_admin):
        return Competition.objects.all().order_by('-created_at')

    assigned_comp_ids = CompetitionAssignment.objects.filter(organizer=user).values_list('competition_id', flat=True)
    return Competition.objects.filter(
        Q(id__in=assigned_comp_ids) | Q(primary_organizer=user) | Q(created_by=user)
    ).distinct().order_by('-created_at')


@approved_organizer_required
def organizer_dashboard(request, comp_id=None):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        if comp_id:
            messages.info(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
            return redirect(f"/competition/{comp_id}/")
        return redirect('/super-admin/?tab=leagues')

    user_competitions = get_organizer_competitions(request.user)

    if comp_id:
        active_competition = get_object_or_404(Competition, id=comp_id)
        # Check permission unless super admin
        if not (request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin)):
            if active_competition not in user_competitions:
                messages.error(request, "You do not have permission to manage this competition.")
                return redirect('organizer_dashboard')
            if active_competition.status == CompetitionStatus.PENDING:
                messages.warning(request, f"'{active_competition.name}' is currently under review by platform administrators. Management tools will unlock once approved.")
                return redirect('organizer_dashboard')

        if request.method == 'POST':
            return update_competition_view(request, comp_id)

        tab = request.GET.get('tab', 'overview')

        # Data for the active competition
        comp_teams = active_competition.teams.all().prefetch_related('players')
        upcoming_matches = active_competition.matches.filter(
            status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED]
        ).select_related('home_team', 'away_team', 'group').order_by('match_date', 'kickoff_time')
        completed_matches = active_competition.matches.filter(
            status=MatchStatus.COMPLETED
        ).select_related('home_team', 'away_team', 'group').prefetch_related(
            'events', 'events__player', 'events__team'
        ).order_by('-match_date', '-kickoff_time')
        all_matches = active_competition.matches.all().select_related('home_team', 'away_team', 'group').order_by('round_number', 'match_date', 'kickoff_time')
        distinct_poster_dates = list(
            active_competition.matches.exclude(status=MatchStatus.CANCELLED)
            .order_by('match_date')
            .values_list('match_date', flat=True)
            .distinct()
        )
        poster_days = [
            {
                'day_number': idx + 1,
                'date': d,
                'iso_date': d.isoformat(),
                'display_date': d.strftime('%d %B %Y'),
            }
            for idx, d in enumerate(distinct_poster_dates)
        ]
        day_num_map = {d: idx + 1 for idx, d in enumerate(distinct_poster_dates)}
        upcoming_by_date = []
        date_bucket = {}
        for m in upcoming_matches:
            if m.match_date not in date_bucket:
                group_entry = {
                    'day_number': day_num_map.get(m.match_date, len(upcoming_by_date) + 1),
                    'date': m.match_date,
                    'iso_date': m.match_date.isoformat(),
                    'display_date': m.match_date.strftime('%d %B %Y'),
                    'header_date': m.match_date.strftime('%d-%m-%Y (%A)').upper(),
                    'short_date': m.match_date.strftime('%d-%m-%Y'),
                    'matches': [],
                }
                date_bucket[m.match_date] = group_entry
                upcoming_by_date.append(group_entry)
            date_bucket[m.match_date]['matches'].append(m)
        next_match = upcoming_matches.filter(home_team__isnull=False, away_team__isnull=False).first() or upcoming_matches.first()
        last_match = completed_matches.first()

        # Group filtering for fixtures & results
        selected_group = request.GET.get('group', 'all')
        if selected_group and selected_group != 'all':
            if selected_group.lower() == 'knockout':
                upcoming_matches = upcoming_matches.filter(group__isnull=True)
                completed_matches = completed_matches.filter(group__isnull=True)
                all_matches = all_matches.filter(group__isnull=True)
            elif selected_group.isdigit():
                upcoming_matches = upcoming_matches.filter(group_id=int(selected_group))
                completed_matches = completed_matches.filter(group_id=int(selected_group))
                all_matches = all_matches.filter(group_id=int(selected_group))
            else:
                upcoming_matches = upcoming_matches.filter(group__name__iexact=selected_group)
                completed_matches = completed_matches.filter(group__name__iexact=selected_group)
                all_matches = all_matches.filter(group__name__iexact=selected_group)

        if active_competition.is_pure_knockout:
            standings = []
            if tab == 'standings':
                tab = 'fixtures'
        else:
            standings = StandingEntry.objects.filter(competition=active_competition).select_related('team').order_by('position')
        stats = get_competition_statistics(active_competition)
        all_players = Player.objects.filter(team__in=comp_teams).select_related('team')
        groups = active_competition.groups.all().order_by('name')

        # Group stage specific data
        group_tables = {}
        group_status = None
        qualified_teams = []
        is_group_stage_completed = False

        if active_competition.is_group_stage or groups.exists():
            from leagues.group_service import (
                get_group_standings_data, get_group_distribution_status,
                check_group_stage_completed, update_qualified_teams
            )
            group_tables = get_group_standings_data(active_competition)
            group_status = get_group_distribution_status(active_competition)
            is_group_stage_completed = check_group_stage_completed(active_competition)
            if is_group_stage_completed:
                update_qualified_teams(active_competition)
                advance_knockout_bracket(active_competition)
            qualified_teams = list(active_competition.qualified_teams.select_related('team', 'group').order_by('group__name', 'rank_in_group'))
        elif active_competition.tournament_format in ['LEAGUE_KNOCKOUT', 'PAGE_MCINTYRE']:
            league_matches = active_competition.matches.filter(tournament_round__icontains='Matchweek')
            if league_matches.exists() and not league_matches.exclude(status=MatchStatus.COMPLETED).exists():
                advance_knockout_bracket(active_competition)

        # Eligible co-organizers to invite
        co_organizers = User.objects.filter(
            profile__role=UserRole.ORGANIZER,
            profile__organizer_status=OrganizerStatus.APPROVED
        ).exclude(id=request.user.id)

        # Activity logs for this competition
        logs = ActivityLog.objects.filter(details__icontains=active_competition.name).order_by('-created_at')[:20]

        context = {
            'has_competitions': True,
            'user_competitions': user_competitions,
            'active_competition': active_competition,
            'active_tab': tab,
            'selected_group': selected_group,
            'comp_teams': comp_teams,
            'upcoming_matches': upcoming_matches,
            'completed_matches': completed_matches,
            'all_matches': all_matches,
            'poster_days': poster_days,
            'upcoming_by_date': upcoming_by_date,
            'next_match': next_match,
            'last_match': last_match,
            'standings': standings,
            'group_tables': group_tables,
            'group_status': group_status,
            'qualified_teams': qualified_teams,
            'is_group_stage_completed': is_group_stage_completed,
            'stats': stats,
            'all_players': all_players,
            'groups': groups,
            'co_organizers': co_organizers,
            'logs': logs,
        }
        return render(request, 'organizer_index.html', context)

    # Hub view: Render organizer.html when organizer logs in or accesses /organizer/
    search_q = request.GET.get('q', '').strip()
    status_f = request.GET.get('status', 'all').strip()

    filtered_competitions = user_competitions
    if search_q:
        filtered_competitions = filtered_competitions.filter(
            Q(name__icontains=search_q) | Q(location__icontains=search_q) | Q(season__icontains=search_q)
        )
    if status_f and status_f != 'all':
        filtered_competitions = filtered_competitions.filter(status=status_f)

    status_counts = dict(user_competitions.values('status').annotate(cnt=Count('id')).values_list('status', 'cnt'))
    total_count = sum(status_counts.values())
    active_count = status_counts.get(CompetitionStatus.ACTIVE, 0)
    upcoming_count = status_counts.get(CompetitionStatus.UPCOMING, 0)
    completed_count = status_counts.get(CompetitionStatus.COMPLETED, 0)
    pending_count = status_counts.get(CompetitionStatus.PENDING, 0)
    total_teams = CompetitionTeam.objects.filter(competition__in=user_competitions).count()

    context = {
        'user_competitions': filtered_competitions,
        'search_query': search_q,
        'status_filter': status_f,
        'total_count': total_count,
        'active_count': active_count,
        'ongoing_count': active_count,
        'completed_count': completed_count,
        'upcoming_count': upcoming_count,
        'pending_count': pending_count,
        'total_teams': total_teams,
    }
    return render(request, 'organizer.html', context)


@approved_organizer_required
def organizer_create_competition(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        comp_type = request.POST.get('competition_type', 'LEAGUE')
        tourn_format = request.POST.get('tournament_format', 'ROUND_ROBIN')
        category = request.POST.get('category', '11-a-side')
        season = request.POST.get('season', '2026/2027').strip()
        location = request.POST.get('location', 'London, UK').strip()
        max_teams_raw = request.POST.get('max_teams', '8')
        if max_teams_raw == 'custom':
            max_teams_raw = request.POST.get('custom_teams', '8')
        try:
            max_teams = int(max_teams_raw or 8)
        except (ValueError, TypeError):
            max_teams = 8

        description = request.POST.get('description', '').strip()
        organization_name = request.POST.get('organization_name', '').strip()
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        logo_url = request.POST.get('logo_url', '').strip()
        et_raw = request.POST.get('extra_time_before_penalties', '0')
        extra_time_before_penalties = et_raw in ['1', 'on', 'true', 'True', 'enabled', 'ENABLED']
        num_groups = int(request.POST.get('num_groups', 2) or 2)
        qualifiers_per_group = int(request.POST.get('qualifiers_per_group', 2) or 2)
        fixture_format = request.POST.get('fixture_format', 'single')
        distribution_method = request.POST.get('distribution_method', 'automatic')

        if not name:
            messages.error(request, "Competition name is required.")
            return redirect('organizer_dashboard')

        # Super admin creations are active immediately; organizer creations go under review
        is_admin = request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin)
        comp_status = CompetitionStatus.ACTIVE if is_admin else CompetitionStatus.PENDING
        is_published = True if is_admin else False

        comp = Competition.objects.create(
            name=name,
            competition_type=comp_type,
            tournament_format=tourn_format,
            category=category,
            season=season,
            location=location,
            max_teams=max_teams,
            description=description,
            primary_organizer=request.user,
            created_by=request.user,
            start_date=start_date,
            end_date=end_date,
            logo_url=logo_url,
            extra_time_before_penalties=extra_time_before_penalties,
            num_groups=num_groups,
            qualifiers_per_group=qualifiers_per_group,
            fixture_format=fixture_format,
            distribution_method=distribution_method,
            status=comp_status,
            is_published=is_published
        )

        if tourn_format == 'GROUP_KNOCKOUT':
            from leagues.group_service import create_or_sync_groups
            create_or_sync_groups(comp, num_groups)

        if 'logo' in request.FILES and request.FILES['logo']:
            try:
                comp.logo = request.FILES['logo']
                comp.save()
            except Exception as e:
                comp.logo = None
                comp.save()

        CompetitionAssignment.objects.create(
            competition=comp,
            organizer=request.user,
            assigned_by=request.user,
            role=CompetitionAssignment.Role.PRIMARY,
            can_edit_fixtures=True,
            can_enter_results=True,
            can_manage_teams=True,
            can_invite_organizers=True
        )

        # Create or update organizer application for Super Admin review
        org_name = organization_name or getattr(request.user.profile, 'organization_name', '') or f"{name} Committee"
        app = OrganizerApplication.objects.filter(applicant=request.user, status=OrganizerApplication.Status.PENDING).first()
        if not app:
            OrganizerApplication.objects.create(
                applicant=request.user,
                full_name=request.user.get_full_name() or request.user.username,
                organization_name=org_name,
                email=request.user.email or f"{request.user.username}@futbolix.local",
                phone=getattr(request.user.profile, 'phone', '') or request.user.username,
                city=location,
                country="United Kingdom",
                experience_years=getattr(request.user.profile, 'experience_years', 1) or 1,
                experience_summary=description or f"Organizer for {name}",
                proposed_leagues=f"League: {name} ({category}, {max_teams} teams, Venue: {location})",
                status=OrganizerApplication.Status.PENDING
            )
        else:
            app.organization_name = org_name
            app.proposed_leagues = (app.proposed_leagues + f"\nLeague: {name} ({category}, {max_teams} teams)").strip()
            app.save()

        if hasattr(request.user, 'profile'):
            profile = request.user.profile
            if profile.organizer_status != OrganizerStatus.APPROVED:
                profile.organization_name = org_name
                profile.organizer_status = OrganizerStatus.PENDING
                profile.save()

        ActivityLog.log('LEAGUE_SUBMITTED', f"Organizer {request.user.username} submitted league '{name}' for review.", user=request.user)

        if comp_status == CompetitionStatus.PENDING:
            messages.success(request, f"League '{name}' submitted successfully! It is now under review by platform administrators. You can track its status on your dashboard.")
            return redirect('organizer_dashboard')
        else:
            messages.success(request, f"Competition '{name}' created and activated successfully!")
            return redirect(f"/organizer/{comp.id}/")
    return redirect('organizer_dashboard')


@approved_organizer_required
def generate_fixtures_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        if competition.is_completed:
            messages.error(request, f"'{competition.name}' is already completed. Fixtures cannot be generated.")
            return redirect(f"/organizer/{comp_id}/?tab=fixtures")
        teams_count = competition.teams.count()
        if teams_count < 2:
            messages.error(request, "Need at least 2 teams registered to generate fixtures.")
            return redirect(f"/organizer/{comp_id}/?tab=fixtures")

        double_round = 'double_round' in request.POST
        created_matches = generate_round_robin_fixtures(competition, double_round=double_round)

        # Initial standings table creation with 0s
        recalculate_competition_standings(competition)

        ActivityLog.log(
            'FIXTURES_GENERATED',
            f"Generated {len(created_matches)} fixtures for '{competition.name}'.",
            user=request.user
        )
        messages.success(request, f"Generated {len(created_matches)} fixtures successfully!")
    return redirect(f"/organizer/{comp_id}/?tab=fixtures")


@approved_organizer_required
def add_fixture_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        if competition.is_completed:
            messages.error(request, "Cannot add matches to a completed competition.")
            return redirect(f"/organizer/{comp_id}/?tab=fixtures")
        home_team_id = request.POST.get('home_team_id')
        away_team_id = request.POST.get('away_team_id')
        match_date_str = request.POST.get('match_date')
        kickoff_time_str = request.POST.get('kickoff_time', '15:00')
        venue = request.POST.get('venue', 'Central Stadium').strip()
        round_name = request.POST.get('tournament_round', 'Matchweek 1').strip()
        round_number = int(request.POST.get('round_number', 1) or 1)

        if home_team_id == away_team_id:
            messages.error(request, "Home team and Away team cannot be the same.")
            return redirect(f"/organizer/{comp_id}/?tab=fixtures")

        home_team = get_object_or_404(Team, id=home_team_id)
        away_team = get_object_or_404(Team, id=away_team_id)

        try:
            m_date = datetime.strptime(match_date_str, '%Y-%m-%d').date()
        except Exception:
            m_date = date.today()

        try:
            k_time = datetime.strptime(kickoff_time_str, '%H:%M').time()
        except Exception:
            k_time = time(15, 0)

        match_obj = Match.objects.create(
            competition=competition,
            tournament_round=round_name,
            round_number=round_number,
            home_team=home_team,
            away_team=away_team,
            match_date=m_date,
            kickoff_time=k_time,
            venue=venue or getattr(home_team, 'home_venue', '') or "Central Stadium",
            status=MatchStatus.SCHEDULED
        )

        ActivityLog.log('FIXTURE_ADDED', f"Added fixture: {home_team.name} vs {away_team.name} ({round_name}).", user=request.user)
        messages.success(request, f"Fixture {home_team.short_name} vs {away_team.short_name} added!")
    return redirect(f"/organizer/{comp_id}/?tab=fixtures")


@approved_organizer_required
def update_match_view(request, match_id):
    match_obj = get_object_or_404(Match, id=match_id)
    comp_id = match_obj.competition_id
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        comp_id = match_obj.competition_id

        match_date_str = request.POST.get('match_date')
        kickoff_time_str = request.POST.get('kickoff_time')
        venue = request.POST.get('venue', '').strip()
        status = request.POST.get('status', match_obj.status)
        tournament_round = request.POST.get('tournament_round', match_obj.tournament_round)

        if match_date_str:
            try:
                match_obj.match_date = datetime.strptime(match_date_str, '%Y-%m-%d').date()
            except Exception:
                pass

        if kickoff_time_str:
            try:
                match_obj.kickoff_time = datetime.strptime(kickoff_time_str, '%H:%M').time()
            except Exception:
                pass

        if venue:
            match_obj.venue = venue

        match_obj.status = status
        match_obj.tournament_round = tournament_round
        match_obj.save()

        # Recalculate standings in case status changed
        recalculate_competition_standings(match_obj.competition)

        ActivityLog.log('MATCH_UPDATED', f"Updated match {match_obj}.", user=request.user)
        messages.success(request, f"Match {match_obj} updated successfully!")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    return redirect('organizer_dashboard')


@approved_organizer_required
def enter_match_result_view(request, match_id):
    match_obj = get_object_or_404(Match, id=match_id)
    comp_id = match_obj.competition_id
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")

    if not match_obj.home_team or not match_obj.away_team:
        messages.error(request, "Cannot record results for a match where participating teams are not yet determined.")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")

    if request.method == 'POST':
        with transaction.atomic():
            comp_id = match_obj.competition_id

            home_score = int(request.POST.get('home_score', 0))
            away_score = int(request.POST.get('away_score', 0))
            status = request.POST.get('status', MatchStatus.COMPLETED)

            match_obj.home_score = home_score
            match_obj.away_score = away_score
            match_obj.status = status
            match_obj.recorded_by = request.user
            match_obj.save()

            # Always clear existing events for this match before re-populating to guarantee zero duplicate events
            match_obj.events.all().delete()

            # Goal events recording
            home_scorers_text = request.POST.get('home_scorers', '').strip()
            away_scorers_text = request.POST.get('away_scorers', '').strip()

            # Parse and save goals if specified
            # Format example: "John Doe 12', Alex Smith 45'(P)"
            def parse_and_record_scorers(scorers_str, team, opp_team):
                if not scorers_str:
                    return
                items = [item.strip() for item in scorers_str.split(',') if item.strip()]
                for item in items:
                    # e.g. "Brooks 14'"
                    parts = item.split()
                    if not parts:
                        continue
                    min_part = parts[-1].replace("'", "").replace("min", "")
                    name_part = " ".join(parts[:-1]) if len(parts) > 1 else parts[0]

                    is_pen = '(P)' in item.upper() or '(PEN)' in item.upper()
                    name_part = name_part.replace('(P)', '').replace('(p)', '').replace('(PEN)', '').replace('(pen)', '').strip()

                    try:
                        minute = int("".join(filter(str.isdigit, min_part))) or 45
                    except Exception:
                        minute = 45

                    # Find player or create
                    player = Player.objects.filter(team=team, full_name__icontains=name_part).first()
                    if not player:
                        player = Player.objects.filter(team=team).first()

                    if player:
                        MatchEvent.objects.create(
                            match=match_obj,
                            team=team,
                            player=player,
                            event_type=MatchEventType.PENALTY if is_pen else MatchEventType.GOAL,
                            minute=min(minute, 120),
                            description=f"Goal by {player.full_name}"
                        )

            parse_and_record_scorers(home_scorers_text, match_obj.home_team, match_obj.away_team)
            parse_and_record_scorers(away_scorers_text, match_obj.away_team, match_obj.home_team)

            # Clean sheet events recording
            if away_score == 0:
                home_gks = list(match_obj.home_team.players.filter(position=PositionChoice.GK))
                home_cs_keeper_id = request.POST.get('home_clean_sheet_keeper')
                keeper = None
                if home_cs_keeper_id:
                    try:
                        keeper = match_obj.home_team.players.get(id=int(home_cs_keeper_id))
                    except (ValueError, Player.DoesNotExist):
                        keeper = None
                if not keeper and len(home_gks) == 1:
                    keeper = home_gks[0]
                if keeper:
                    MatchEvent.objects.create(
                        match=match_obj,
                        team=match_obj.home_team,
                        player=keeper,
                        event_type=MatchEventType.CLEAN_SHEET,
                        minute=90,
                        description=f"Clean sheet kept by {keeper.full_name}"
                    )

            if home_score == 0:
                away_gks = list(match_obj.away_team.players.filter(position=PositionChoice.GK))
                away_cs_keeper_id = request.POST.get('away_clean_sheet_keeper')
                keeper = None
                if away_cs_keeper_id:
                    try:
                        keeper = match_obj.away_team.players.get(id=int(away_cs_keeper_id))
                    except (ValueError, Player.DoesNotExist):
                        keeper = None
                if not keeper and len(away_gks) == 1:
                    keeper = away_gks[0]
                if keeper:
                    MatchEvent.objects.create(
                        match=match_obj,
                        team=match_obj.away_team,
                        player=keeper,
                        event_type=MatchEventType.CLEAN_SHEET,
                        minute=90,
                        description=f"Clean sheet kept by {keeper.full_name}"
                    )

            # Automatically recalculate standings!
            recalculate_competition_standings(match_obj.competition)

            # Automatically update qualified teams if group stage finishes
            if match_obj.competition.is_group_stage:
                from leagues.group_service import check_group_stage_completed, update_qualified_teams
                if check_group_stage_completed(match_obj.competition):
                    update_qualified_teams(match_obj.competition)

            # Automatically advance knockout brackets
            advance_knockout_bracket(match_obj.competition)

            ActivityLog.log(
                'MATCH_RESULT_ENTERED',
                f"Entered result: {match_obj.home_display_name} {home_score}-{away_score} {match_obj.away_display_name}.",
                user=request.user
            )

        messages.success(request, f"Result recorded: {match_obj.home_display_name} {home_score} - {away_score} {match_obj.away_display_name}. Points table updated!")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    return redirect('organizer_dashboard')


@approved_organizer_required
def add_team_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/")
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        if competition.is_completed:
            messages.error(request, "This competition is already completed. New teams cannot be added.")
            return redirect(f"/organizer/{comp_id}/?tab=teams")

        team_name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        manager_name = request.POST.get('manager_name', '').strip()
        contact_email = request.POST.get('contact_email', '').strip()
        contact_phone = request.POST.get('contact_phone', '').strip()
        home_venue = request.POST.get('home_venue', '').strip()
        city = request.POST.get('city', 'London').strip()
        group_id = request.POST.get('group_id')
        logo_url = request.POST.get('logo_url', '').strip()

        if not team_name:
            messages.error(request, "Team name is required.")
            return redirect(f"/organizer/{comp_id}/?tab=teams")

        # Get or create team using valid Team model fields
        team = Team.objects.filter(name__iexact=team_name).first()
        created = False
        if not team:
            create_kwargs = {
                'name': team_name,
                'short_name': short_name or team_name[:3].upper(),
                'manager_name': manager_name,
                'created_by': request.user
            }
            if contact_phone:
                create_kwargs['contact_phone'] = contact_phone
            team = Team.objects.create(**create_kwargs)
            created = True

        if 'logo' in request.FILES and request.FILES['logo']:
            try:
                team.logo = request.FILES['logo']
                team.save()
            except Exception:
                pass

        # Associate team to this competition
        group_obj = None
        if group_id:
            group_obj = TournamentGroup.objects.filter(id=group_id, competition=competition).first()

        ct, ct_created = CompetitionTeam.objects.get_or_create(
            competition=competition,
            team=team,
            defaults={'group': group_obj}
        )

        # Add default squad players if this is a newly created team
        if created:
            default_players = [
                ("Oliver Smith", 1, "GK"),
                ("Harry Jones", 4, "DEF"),
                ("Liam Taylor", 5, "DEF"),
                ("Jack Davies", 3, "DEF"),
                ("Noah Brown", 6, "MID"),
                ("James Wilson", 8, "MID"),
                ("Leo Evans", 10, "MID"),
                ("Ethan Brooks", 9, "FWD"),
                ("Lucas Thomas", 11, "FWD"),
                ("Mason Roberts", 7, "FWD"),
                ("Logan Walker", 2, "DEF"),
            ]
            for pname, pnum, ppos in default_players:
                Player.objects.create(
                    team=team,
                    full_name=pname,
                    jersey_number=pnum,
                    position=ppos,
                    photo_url=f"/static/img/players/p{(pnum % 6) + 1}.jpg"
                )

        # Recalculate standings so team appears in table
        recalculate_competition_standings(competition)

        ActivityLog.log('TEAM_ADDED', f"Added team '{team.name}' to competition '{competition.name}'.", user=request.user)
        messages.success(request, f"Team '{team.name}' added to {competition.name}!")
    return redirect(f"/organizer/{comp_id}/?tab=teams")


@approved_organizer_required
def add_player_view(request, team_id):
    comp_id = request.POST.get('comp_id')
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp_id}/" if comp_id else '/super-admin/?tab=leagues')
    if request.method == 'POST':
        team = get_object_or_404(Team, id=team_id)
        comp_id = request.POST.get('comp_id')

        full_name = request.POST.get('full_name', '').strip()
        jersey_number = int(request.POST.get('jersey_number', 0))
        position = request.POST.get('position', '').strip()
        dob_str = request.POST.get('date_of_birth')
        nationality = request.POST.get('nationality', 'United Kingdom').strip()
        photo_url = request.POST.get('photo_url', '').strip()

        if not full_name or jersey_number <= 0:
            messages.error(request, "Player name and positive jersey number are required.")
            return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')

        if not position:
            messages.error(request, "Please select a player position.")
            return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')

        if Player.objects.filter(team=team, jersey_number=jersey_number).exists():
            messages.error(request, f"Jersey #{jersey_number} is already taken in {team.name}. Player not submitted.")
            return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')

        dob = None
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except Exception:
                pass

        player = Player.objects.create(
            team=team,
            full_name=full_name,
            jersey_number=jersey_number,
            position=position,
            date_of_birth=dob,
            nationality=nationality,
            photo_url=photo_url or f"/static/img/players/p{(jersey_number % 6) + 1}.jpg"
        )

        if 'photo' in request.FILES and request.FILES['photo']:
            try:
                player.photo = request.FILES['photo']
                player.save()
            except Exception:
                pass

        ActivityLog.log('PLAYER_ADDED', f"Added player #{jersey_number} {full_name} to {team.name}.", user=request.user)
        messages.success(request, f"Player #{jersey_number} {full_name} added to {team.name}!")
        return redirect(f"/organizer/{comp_id}/?tab=teams" if comp_id else 'organizer_dashboard')
    return redirect('organizer_dashboard')


@approved_organizer_required
def recalculate_standings_view(request, comp_id):
    competition = get_object_or_404(Competition, id=comp_id)
    if competition.is_pure_knockout:
        StandingEntry.objects.filter(competition=competition).delete()
        messages.info(request, f"{competition.name} is a knockout tournament; points table is not applicable.")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    if request.method == 'POST':
        recalculate_competition_standings(competition)
        messages.success(request, f"Points table and goal difference recalculated for {competition.name}!")
    return redirect(f"/organizer/{comp_id}/?tab=standings")


@approved_organizer_required
def invite_co_organizer_view(request, comp_id):
    if request.method == 'POST':
        competition = get_object_or_404(Competition, id=comp_id)
        organizer_id = request.POST.get('organizer_id')
        co_organizer = get_object_or_404(User, id=organizer_id)

        CompetitionAssignment.objects.update_or_create(
            competition=competition,
            organizer=co_organizer,
            defaults={
                'assigned_by': request.user,
                'role': CompetitionAssignment.Role.CO_ORGANIZER,
                'can_edit_fixtures': True,
                'can_enter_results': True,
                'can_manage_teams': True,
                'can_invite_organizers': False
            }
        )

        ActivityLog.log(
            'ORGANIZER_INVITED',
            f"{request.user.username} invited {co_organizer.username} to co-organize '{competition.name}'.",
            user=request.user
        )

        Notification.objects.create(
            recipient=co_organizer,
            title="Co-Organizer Invitation",
            message=f"{request.user.username} added you as a Co-Organizer for '{competition.name}'.",
            notification_type="COMPETITION",
            link=f"/organizer/{competition.id}/"
        )

        messages.success(request, f"{co_organizer.username} added as co-organizer for {competition.name}!")
    return redirect(f"/organizer/{comp_id}/?tab=overview")


@approved_organizer_required
def update_competition_view(request, comp_id):
    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit league details directly.")
        return redirect(f"/competition/{comp_id}/")
    competition = get_object_or_404(Competition, id=comp_id)
    user_comps = get_organizer_competitions(request.user)
    if not (request.user.is_superuser or competition in user_comps):
        messages.error(request, "Permission denied to update this competition.")
        return redirect('organizer_dashboard')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        location = request.POST.get('location', '').strip()
        season = request.POST.get('season', '').strip()
        category = request.POST.get('category', '').strip()
        description = request.POST.get('description', '').strip()
        logo_url = request.POST.get('logo_url', '').strip()

        if name:
            competition.name = name
        if location:
            competition.location = location
        if season:
            competition.season = season
        if category:
            competition.category = category
        if description is not None:
            competition.description = description
        if 'max_teams' in request.POST:
            try:
                new_max = int(request.POST.get('max_teams'))
                if new_max >= 2:
                    competition.max_teams = new_max
            except (ValueError, TypeError):
                pass
        if not competition.is_completed:
            if 'extra_time_before_penalties' in request.POST:
                et_val = request.POST.get('extra_time_before_penalties')
                competition.extra_time_before_penalties = et_val in ['1', 'on', 'true', 'True', 'enabled', 'ENABLED']
            if 'tournament_format' in request.POST:
                competition.tournament_format = request.POST.get('tournament_format')
            if 'num_groups' in request.POST:
                try:
                    new_num_groups = int(request.POST.get('num_groups') or 2)
                    competition.num_groups = new_num_groups
                    if competition.is_group_stage:
                        from leagues.group_service import create_or_sync_groups
                        create_or_sync_groups(competition, new_num_groups)
                except (ValueError, TypeError):
                    pass
            if 'qualifiers_per_group' in request.POST:
                try:
                    competition.qualifiers_per_group = int(request.POST.get('qualifiers_per_group') or 2)
                except (ValueError, TypeError):
                    pass
            if 'fixture_format' in request.POST:
                competition.fixture_format = request.POST.get('fixture_format')
            if 'distribution_method' in request.POST:
                competition.distribution_method = request.POST.get('distribution_method')

        if 'logo' in request.FILES and request.FILES['logo']:
            try:
                competition.logo = request.FILES['logo']
                competition.logo_url = ""
                competition.save()
            except Exception as e:
                competition.logo = None
                if logo_url:
                    competition.logo_url = logo_url
                competition.save()
        elif logo_url:
            competition.logo_url = logo_url
            competition.save()

        # Also update organizer user/profile fields if provided in request
        org_user = competition.primary_organizer or competition.created_by
        if org_user:
            profile = getattr(org_user, 'profile', None)
            if 'organization_name' in request.POST and profile:
                profile.organization_name = request.POST.get('organization_name', '').strip()
                profile.save()
            if 'phone' in request.POST and profile:
                profile.phone = request.POST.get('phone', '').strip()
                profile.save()
            if 'email' in request.POST:
                org_user.email = request.POST.get('email', '').strip()
                org_user.save()
            if 'full_name' in request.POST or 'organizer_name' in request.POST:
                fname = (request.POST.get('full_name') or request.POST.get('organizer_name') or '').strip()
                if fname:
                    parts = fname.split(None, 1)
                    org_user.first_name = parts[0]
                    org_user.last_name = parts[1] if len(parts) > 1 else ""
                    org_user.save()

        ActivityLog.log('LEAGUE_UPDATED', f"Organizer {request.user.username} updated league '{competition.name}'.", user=request.user)
        messages.success(request, "Organizer details updated successfully!")
        return redirect('/organizer/')
    return redirect('/organizer/')


@approved_organizer_required
def api_distribute_teams(request, comp_id):
    """
    JSON API / Form POST endpoint: Distributes registered teams across groups.
    Supports both 'automatic' and 'manual' distribution.
    """
    competition = get_object_or_404(Competition, id=comp_id)
    if competition.is_completed:
        return JsonResponse({'success': False, 'error': "This competition is already completed. Teams and groups cannot be modified."}, status=400)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from leagues.group_service import (
        distribute_teams_automatically, distribute_teams_manually,
        get_group_distribution_status
    )

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    method = data.get('method', 'automatic').lower()
    num_groups = data.get('num_groups')
    if num_groups:
        try:
            num_groups = int(num_groups)
        except (ValueError, TypeError):
            num_groups = competition.num_groups

    if method == 'automatic':
        res = distribute_teams_automatically(competition, num_groups=num_groups)
    elif method == 'manual':
        assignments = data.get('assignments', {})
        if isinstance(assignments, str):
            try:
                assignments = json.loads(assignments)
            except Exception:
                assignments = {}
        res = distribute_teams_manually(competition, assignments)
    else:
        return JsonResponse({'success': False, 'error': f"Unknown distribution method '{method}'."}, status=400)

    if not res.get('success'):
        return JsonResponse(res, status=400)

    status = get_group_distribution_status(competition)
    return JsonResponse({
        'success': True,
        'message': f"Teams successfully distributed via {method} method.",
        'status': status
    })


@approved_organizer_required
def api_confirm_groups(request, comp_id):
    """
    JSON API endpoint: Confirms group assignments.
    Prevents confirmation while teams remain unassigned.
    """
    competition = get_object_or_404(Competition, id=comp_id)
    if competition.is_completed:
        return JsonResponse({'success': False, 'error': "This competition is already completed. Group assignments cannot be modified."}, status=400)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from leagues.group_service import confirm_group_assignments, get_group_distribution_status
    res = confirm_group_assignments(competition)
    if not res.get('success'):
        return JsonResponse(res, status=400)

    status = get_group_distribution_status(competition)
    return JsonResponse({
        'success': True,
        'message': "Group assignments confirmed successfully!",
        'status': status
    })


@approved_organizer_required
def api_generate_group_fixtures(request, comp_id):
    """
    JSON API / Form POST endpoint: Generates independent group-wise fixtures
    (single or double round-robin with BYE handling for odd team counts).
    """
    competition = get_object_or_404(Competition, id=comp_id)
    if competition.is_completed:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'success': False, 'error': "This competition is already completed. Group fixtures cannot be generated."}, status=400)
        messages.error(request, "This competition is already completed. Group fixtures cannot be generated.")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    double_round = str(data.get('double_round', '')).lower() in ['1', 'true', 'on', 'double']
    matches_per_day = int(data.get('matches_per_day', 1) or 1)

    from leagues.group_service import generate_group_fixtures
    res = generate_group_fixtures(competition, double_round=double_round, matches_per_day=matches_per_day)

    if not res.get('success'):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse(res, status=400)
        messages.error(request, res.get('error', 'Failed generating group fixtures.'))
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")

    msg = f"✓ Successfully generated {res['matches_count']} group fixtures for {competition.name}!"
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'success': True, 'message': msg, 'matches_count': res['matches_count']})

    messages.success(request, msg)
    return redirect(f"/organizer/{comp_id}/?tab=fixtures")


@approved_organizer_required
def api_update_qualification_settings(request, comp_id):
    """
    JSON API: Updates the number of qualifying teams per group.
    Validates that qualification count does not exceed group size.
    """
    competition = get_object_or_404(Competition, id=comp_id)
    if competition.is_completed:
        return JsonResponse({'success': False, 'error': "This competition is already completed. Qualification settings cannot be modified."}, status=400)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    try:
        q_count = int(data.get('qualifiers_per_group', 2))
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': "Invalid qualifiers count."}, status=400)

    groups = list(competition.groups.all())
    if groups:
        min_size = min((g.group_teams.count() for g in groups), default=0)
        if q_count > min_size and min_size > 0:
            return JsonResponse({
                'success': False,
                'error': f"Qualifying teams per group ({q_count}) cannot exceed the smallest group size ({min_size} teams)."
            }, status=400)

    competition.qualifiers_per_group = q_count
    competition.save(update_fields=['qualifiers_per_group'])

    return JsonResponse({
        'success': True,
        'message': f"Qualification updated to {q_count} teams per group.",
        'qualifiers_per_group': q_count
    })


@approved_organizer_required
def api_generate_knockout_stage(request, comp_id):
    """
    JSON API endpoint: Generates the knockout stage from qualified teams
    after the group stage is completed.
    """
    competition = get_object_or_404(Competition, id=comp_id)
    if competition.is_completed:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'success': False, 'error': "This tournament is already completed. Knockout fixtures cannot be generated."}, status=400)
        messages.error(request, "This tournament is already completed. Knockout fixtures cannot be generated.")
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    from leagues.group_service import generate_knockout_from_qualified_teams
    res = generate_knockout_from_qualified_teams(competition)

    if not res.get('success'):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse(res, status=400)
        messages.error(request, res.get('error', 'Failed generating knockout stage.'))
        return redirect(f"/organizer/{comp_id}/?tab=fixtures")

    msg = f"✓ Knockout Stage generated with {res['knockout_matches_count']} matches using qualified teams!"
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'success': True, 'message': msg, 'matches_count': res['knockout_matches_count']})

    messages.success(request, msg)
    return redirect(f"/organizer/{comp_id}/?tab=fixtures")


def api_group_status(request, comp_id):
    """
    JSON API endpoint: Returns live group distribution, standings, and qualification status.
    """
    competition = get_object_or_404(Competition, id=comp_id)
    from leagues.group_service import (
        get_group_distribution_status, get_group_standings_data,
        check_group_stage_completed
    )

    dist_status = get_group_distribution_status(competition)
    standings_data = get_group_standings_data(competition)
    is_completed = check_group_stage_completed(competition)

    serialized_tables = {}
    for grp, entries in standings_data.items():
        serialized_tables[grp.name] = [
            {
                'position': e['position'],
                'team_id': e['team'].id,
                'team_name': e['team'].name,
                'played': e['played'],
                'won': e['won'],
                'drawn': e['drawn'],
                'lost': e['lost'],
                'goals_for': e['goals_for'],
                'goals_against': e['goals_against'],
                'goal_difference': e['goal_difference'],
                'points': e['points'],
                'is_qualified': e['is_qualified_position']
            }
            for e in entries
        ]

    qualified = [
        {
            'team_id': qt.team.id,
            'team_name': qt.team.name,
            'group_name': qt.group.name,
            'rank': qt.rank_in_group
        }
        for qt in competition.qualified_teams.all()
    ]

    return JsonResponse({
        'competition_id': competition.id,
        'format': competition.tournament_format,
        'num_groups': competition.num_groups,
        'qualifiers_per_group': competition.qualifiers_per_group,
        'fixture_format': competition.fixture_format,
        'distribution': dist_status,
        'standings': serialized_tables,
        'is_group_stage_completed': is_completed,
        'qualified_teams': qualified,
        'knockout_generated': competition.knockout_generated
    })


@login_required
def delete_competition_view(request, comp_id):
    """
    Deletes a competition/tournament permanently.
    - Super Admins can delete any competition.
    - Approved Organizers can delete competitions they own/created or are assigned to.
    - Other users receive HTTP 403 Forbidden.
    """
    competition = get_object_or_404(Competition, id=comp_id)
    user = request.user
    is_admin = user.is_superuser or (hasattr(user, 'profile') and user.profile.is_super_admin)

    if not is_admin:
        if not (hasattr(user, 'profile') and user.profile.is_approved_organizer):
            messages.error(request, "Permission denied. Only approved organizers and administrators can delete competitions.")
            return HttpResponseForbidden("Permission denied.")

        user_comps = get_organizer_competitions(user)
        if competition not in user_comps:
            messages.error(request, "Permission denied: you cannot delete a competition you do not manage.")
            return HttpResponseForbidden("Permission denied.")

    comp_name = competition.name

    if request.method == 'POST':
        # Log deletion in ActivityLog
        ActivityLog.log(
            'COMPETITION_DELETED',
            f"{user.username} deleted competition '{comp_name}' (ID {comp_id}).",
            user=user
        )
        competition.delete()
        messages.success(request, f"✓ Competition '{comp_name}' has been permanently deleted.")
        if is_admin:
            return redirect('/super-admin/?tab=leagues')
        return redirect('organizer_dashboard')

    messages.warning(request, "Deletion requires POST confirmation.")
    if is_admin:
        return redirect('/super-admin/?tab=leagues')
    return redirect(f"/organizer/{comp_id}/?tab=settings")




