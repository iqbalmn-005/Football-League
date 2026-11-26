"""
Fixtures application views - Pure Django views for fixture generation, scheduling wizard, and preview API.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
import math
from datetime import datetime, date, time, timedelta

from accounts.decorators import approved_organizer_required
from leagues.models import Competition, CompetitionStatus, TournamentFormat
from matches.models import Match, MatchStatus
from fixtures.services import (
    generate_round_robin_fixtures,
    generate_smart_fixtures,
    commit_generated_fixtures,
    parse_date_safe,
    DEFAULT_VENUES,
    DEFAULT_KICKOFF_TIMES,
    WEEKDAY_MAP,
)
from fixtures.scheduling_engine import validate_complete_schedule


@approved_organizer_required
def fixture_generator_page(request, comp_id):
    """
    Dedicated Fixture Generation Form page for league organizers.
    Interactive 6-section configuration wizard with real-time preview and editing.
    """
    comp = get_object_or_404(Competition, id=comp_id)

    if comp.status == CompetitionStatus.PENDING:
        messages.error(request, "Fixtures cannot be generated while competition is under review.")
        return redirect('organizer_competition_dashboard', comp_id=comp.id)

    if comp.is_completed:
        messages.error(request, f"'{comp.name}' is concluded and completed. Fixtures cannot be generated or modified.")
        return redirect(f"/organizer/{comp.id}/?tab=fixtures")

    teams = list(comp.teams.all())
    ct_group_map = {
        ct.team_id: ct.group.name
        for ct in comp.competitionteam_set.filter(group__isnull=False).select_related('group')
    }
    comp_teams_json = json.dumps([
        {'id': t.id, 'name': t.name, 'short_name': t.short_name, 'group': ct_group_map.get(t.id, '')}
        for t in teams
    ])
    default_start_date = comp.start_date or (date.today() + timedelta(days=7))
    default_end_date = comp.end_date or (default_start_date + timedelta(days=90))

    # Collect team venues + defaults
    team_venues = [getattr(t, 'home_venue', '') for t in teams if getattr(t, 'home_venue', '')]
    venues_list = list(dict.fromkeys(team_venues + DEFAULT_VENUES))

    context = {
        'competition': comp,
        'comp_teams': teams,
        'comp_teams_json': comp_teams_json,
        'default_start_date': default_start_date.isoformat(),
        'default_end_date': default_end_date.isoformat(),
        'default_venues': venues_list,
        'default_kickoff_times': DEFAULT_KICKOFF_TIMES,
        'tournament_formats': TournamentFormat.choices,
    }
    return render(request, 'fixture_generator.html', context)


@approved_organizer_required
@require_POST
def api_generate_fixture_preview(request, comp_id):
    """
    Django JSON API endpoint: Runs the SmartFixtureGenerator algorithm and returns
    calculated fixtures for preview and inline editing without persisting to DB yet.
    """
    try:
        comp = Competition.objects.filter(id=comp_id).first()
        if not comp:
            return JsonResponse({'success': False, 'errors': [f"Competition (ID {comp_id}) not found."]}, status=404)

        if comp.is_completed:
            return JsonResponse({'success': False, 'errors': ["This competition is already completed. Fixtures cannot be generated."]}, status=400)

        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception as e:
            return JsonResponse({'success': False, 'errors': [f"Invalid request data: {str(e)}"]}, status=400)

        result = generate_smart_fixtures(competition=comp, config=data)
        status_code = 200 if result.get('success', False) else 400
        return JsonResponse(result, status=status_code)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'errors': [f"Fixture generation failed: {str(exc)}"],
            'matches': [],
            'summary': {}
        }, status=500)


@approved_organizer_required
@require_POST
def api_revalidate_fixtures(request, comp_id):
    """
    Django JSON API endpoint: Revalidates manually edited draft fixtures against all
    scheduling constraints (daily limit, rest days, date range, team conflicts, venue slots).
    """
    try:
        comp = Competition.objects.filter(id=comp_id).first()
        if not comp:
            return JsonResponse({'success': False, 'errors': [f"Competition (ID {comp_id}) not found."]}, status=404)
        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception as e:
            return JsonResponse({'success': False, 'errors': [f"Invalid request data: {str(e)}"]}, status=400)

        matches_data = data.get('matches', [])
        preferred_days = data.get('preferred_days', [])
        preferred_weekdays = [WEEKDAY_MAP[d] for d in preferred_days if d in WEEKDAY_MAP] or None

        raw_excl = data.get('excluded_dates', [])
        if isinstance(raw_excl, str):
            raw_excl = [s.strip() for s in raw_excl.split(',') if s.strip()]
        excluded_dates = [d for d in (parse_date_safe(x) for x in raw_excl) if d is not None]

        mpd_val = int(data.get('matches_per_day', 1) or 1)
        t_count = comp.teams.count() or 2
        auto_team_mpd = 1 if mpd_val <= max(1, t_count // 2) else max(2, math.ceil((2 * mpd_val) / max(2, t_count)))
        constraints = {
            'start_date': parse_date_safe(data.get('start_date')) if data.get('start_date') else None,
            'end_date': parse_date_safe(data.get('end_date')) if data.get('end_date') else None,
            'matches_per_day': mpd_val,
            'max_matches_per_team_per_day': max(1, int(data.get('max_matches_per_team_per_day') or auto_team_mpd)),
            'min_rest_days': int(data.get('min_rest_days', 0) or 0),
            'excluded_dates': excluded_dates,
            'preferred_weekdays': preferred_weekdays,
        }
        report = validate_complete_schedule(matches_data, constraints)
        return JsonResponse({
            'success': True,
            'validation': report,
        })
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'errors': [f"Revalidation error: {str(exc)}"]}, status=500)


@approved_organizer_required
@require_POST
def api_publish_fixtures(request, comp_id):
    """
    Django JSON API endpoint: Finalizes and atomically commits generated (and edited) fixtures to DB.
    """
    comp = get_object_or_404(Competition, id=comp_id)

    if comp.is_completed:
        return JsonResponse({'success': False, 'errors': ["Cannot publish fixtures for a completed competition."]}, status=400)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        return JsonResponse({'success': False, 'errors': [f"Invalid request data: {str(e)}"]}, status=400)

    matches_data = data.get('matches', [])
    groups_data = data.get('groups', {})
    tournament_format = data.get('tournament_format')
    tournament_type = data.get('tournament_type') or data.get('knockout_system')
    overwrite_locked = bool(data.get('overwrite_locked', False))
    strategy = data.get('scheduling_strategy', 'optimized')

    if tournament_format == 'KNOCKOUT':
        if tournament_type == 'page_mcintyre':
            tournament_format = TournamentFormat.PAGE_MCINTYRE
        else:
            tournament_format = TournamentFormat.SINGLE_ELIMINATION
    elif tournament_format == 'LEAGUE_KNOCKOUT':
        tournament_format = TournamentFormat.LEAGUE_KNOCKOUT
    elif tournament_format == 'GROUP_KNOCKOUT':
        tournament_format = TournamentFormat.GROUP_KNOCKOUT

    if not matches_data:
        return JsonResponse({'success': False, 'errors': ["No fixtures to publish. Please generate fixtures first."]}, status=400)

    constraints = None
    if data.get('matches_per_day') or data.get('start_date') or data.get('end_date'):
        raw_excl = data.get('excluded_dates', [])
        if isinstance(raw_excl, str):
            raw_excl = [s.strip() for s in raw_excl.split(',') if s.strip()]
        mpd_val = int(data.get('matches_per_day', 1) or 1)
        t_count = comp.teams.count() or 2
        auto_team_mpd = 1 if mpd_val <= max(1, t_count // 2) else max(2, math.ceil((2 * mpd_val) / max(2, t_count)))
        constraints = {
            'start_date': parse_date_safe(data.get('start_date')) if data.get('start_date') else None,
            'end_date': parse_date_safe(data.get('end_date')) if data.get('end_date') else None,
            'matches_per_day': mpd_val,
            'max_matches_per_team_per_day': max(1, int(data.get('max_matches_per_team_per_day') or auto_team_mpd)),
            'min_rest_days': int(data.get('min_rest_days', 0) or 0),
            'excluded_dates': [d for d in (parse_date_safe(x) for x in raw_excl) if d is not None],
        }

    try:
        created_matches = commit_generated_fixtures(
            competition=comp,
            matches_data=matches_data,
            groups_data=groups_data,
            tournament_format=tournament_format,
            constraints=constraints,
            overwrite_locked=overwrite_locked,
            user=request.user if request.user.is_authenticated else None,
            strategy=strategy,
            config_snapshot=data.get('config_snapshot') or {}
        )
    except ValueError as ve:
        return JsonResponse({'success': False, 'errors': [str(ve)]}, status=400)

    messages.success(request, f"✓ Successfully generated and published {len(created_matches)} fixtures for {comp.name}!")
    return JsonResponse({
        'success': True,
        'matches_count': len(created_matches),
        'redirect_url': f"/organizer/{comp.id}/?tab=fixtures"
    })


@approved_organizer_required
def generate_fixtures_view(request, comp_id):
    """
    Django backend view: Quick 1-click round-robin generator shortcut.
    """
    comp = get_object_or_404(Competition, id=comp_id)

    if comp.status == CompetitionStatus.PENDING:
        messages.error(request, "Fixtures cannot be generated while competition is under review.")
        return redirect('organizer_competition_dashboard', comp_id=comp.id)

    if comp.is_completed:
        messages.error(request, f"'{comp.name}' is concluded and completed. Fixtures cannot be generated or modified.")
        return redirect(f"/organizer/{comp.id}/?tab=fixtures")

    team_count = comp.teams.count()
    if team_count < 2:
        messages.error(request, "At least 2 teams are required to generate round-robin fixtures.")
        return redirect('organizer_competition_dashboard', comp_id=comp.id)

    double_round = request.POST.get('double_round') == 'on' or request.POST.get('double_round') == 'true'
    matches_per_day = int(request.POST.get('matches_per_day', 1) or 1)

    created_matches = generate_round_robin_fixtures(
        competition=comp,
        start_date=comp.start_date or date.today(),
        double_round=double_round,
        matches_per_day=matches_per_day
    )

    messages.success(request, f"✓ Successfully generated {len(created_matches)} match fixtures for {comp.name}!")
    return redirect(f"/organizer/{comp.id}/?tab=fixtures")


@approved_organizer_required
def add_fixture_view(request, comp_id):
    """
    Django backend view: Adds a single fixture scheduled between two teams.
    """
    comp = get_object_or_404(Competition, id=comp_id)

    if comp.is_completed:
        messages.error(request, "Cannot add matches to a completed competition.")
        return redirect(f"/organizer/{comp.id}/?tab=fixtures")

    if request.method == 'POST':
        home_id = request.POST.get('home_team_id')
        away_id = request.POST.get('away_team_id')
        match_date_str = request.POST.get('match_date')
        kickoff_str = request.POST.get('kickoff_time')
        venue = request.POST.get('venue', '').strip()
        round_name = request.POST.get('round_name', 'Regular Fixture').strip()

        if home_id == away_id:
            messages.error(request, "Home team and away team cannot be the same.")
            return redirect(f"/organizer/{comp.id}/?tab=fixtures")

        m_date = datetime.strptime(match_date_str, '%Y-%m-%d').date() if match_date_str else date.today()
        k_time = datetime.strptime(kickoff_str, '%H:%M').time() if kickoff_str else time(15, 0)

        Match.objects.create(
            competition=comp,
            home_team_id=home_id,
            away_team_id=away_id,
            match_date=m_date,
            kickoff_time=k_time,
            venue=venue or "Metropolis Arena",
            tournament_round=round_name,
            status=MatchStatus.SCHEDULED
        )

        messages.success(request, f"✓ Match fixture added successfully!")
        return redirect(f"/organizer/{comp.id}/?tab=fixtures")

    return redirect(f"/organizer/{comp.id}/?tab=fixtures")


def api_fixture_poster_data(request, comp_id):
    """
    Read-only JSON API endpoint for Day-wise Fixture Poster generation:
    GET /api/leagues/<comp_id>/fixtures/poster/?date=YYYY-MM-DD
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required.'}, status=401)

    from accounts.models import UserRole, OrganizerStatus
    from leagues.organizer_views import get_organizer_competitions

    profile = getattr(request.user, 'profile', None)
    is_admin = request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN)
    is_approved_org = bool(
        profile
        and profile.role == UserRole.ORGANIZER
        and profile.organizer_status == OrganizerStatus.APPROVED
    )
    if not (is_admin or is_approved_org):
        return JsonResponse({'success': False, 'error': 'Access denied: League Organizer privileges required.'}, status=403)

    comp = Competition.objects.filter(id=comp_id).first()
    if not comp:
        return JsonResponse({'success': False, 'error': 'League not found.'}, status=404)

    if not is_admin and not get_organizer_competitions(request.user).filter(id=comp.id).exists():
        return JsonResponse({'success': False, 'error': 'You do not have permission to access this league.'}, status=403)

    date_str = (request.GET.get('date') or '').strip()
    if not date_str:
        return JsonResponse({'success': False, 'error': 'Missing date parameter. Expected YYYY-MM-DD.'}, status=400)

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date format. Expected YYYY-MM-DD.'}, status=400)

    mode = (request.GET.get('mode') or 'fixtures').strip().lower()
    if mode not in ('fixtures', 'results'):
        mode = 'fixtures'

    base_qs = comp.matches.filter(match_date=target_date)
    if mode == 'results':
        matches_qs = base_qs.filter(status=MatchStatus.COMPLETED)
    else:
        matches_qs = base_qs.exclude(status=MatchStatus.CANCELLED)

    matches_qs = matches_qs.select_related('home_team', 'away_team', 'group').order_by('kickoff_time', 'id')
    if not matches_qs.exists():
        label = 'completed results' if mode == 'results' else 'published fixtures'
        return JsonResponse({'success': False, 'error': f'No {label} found for {date_str}.'}, status=404)

    distinct_dates = list(
        comp.matches.exclude(status=MatchStatus.CANCELLED)
        .order_by('match_date')
        .values_list('match_date', flat=True)
        .distinct()
    )
    day_number = distinct_dates.index(target_date) + 1 if target_date in distinct_dates else 1

    matches_payload = []
    for m in matches_qs:
        kickoff_display = m.kickoff_time.strftime('%I:%M %p') if m.kickoff_time else 'TBA'
        matches_payload.append({
            'id': m.id,
            'kickoff_time': kickoff_display,
            'kickoff_time_24': m.kickoff_time.strftime('%H:%M') if m.kickoff_time else '',
            'tournament_round': (m.tournament_round or '').strip(),
            'group_name': m.group.name if m.group else '',
            'home_team_name': m.home_display_name,
            'home_team_logo': m.home_team.get_logo_url() if m.home_team else '',
            'away_team_name': m.away_display_name,
            'away_team_logo': m.away_team.get_logo_url() if m.away_team else '',
            'home_score': m.home_score,
            'away_score': m.away_score,
            'display_score': m.display_score,
            'is_completed': m.status == MatchStatus.COMPLETED,
        })

    resp = JsonResponse({
        'success': True,
        'mode': mode,
        'league': {
            'id': comp.id,
            'name': comp.name,
            'season': comp.season,
            'logo_url': comp.get_logo_url() or '',
        },
        'date': target_date.isoformat(),
        'formatted_date': target_date.strftime('%d %b %Y').upper(),
        'filename_date': target_date.strftime('%d-%b-%Y'),
        'day_number': day_number,
        'matches': matches_payload,
    })
    resp['Cache-Control'] = 'no-store'
    return resp
