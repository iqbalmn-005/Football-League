"""
Fixtures application views - Pure Django views for fixture generation, scheduling wizard, and preview API.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
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
    default_start_date = comp.start_date or (date.today() + timedelta(days=7))
    default_end_date = comp.end_date or (default_start_date + timedelta(days=90))

    # Collect team venues + defaults
    team_venues = [getattr(t, 'home_venue', '') for t in teams if getattr(t, 'home_venue', '')]
    venues_list = list(dict.fromkeys(team_venues + DEFAULT_VENUES))

    context = {
        'competition': comp,
        'comp_teams': teams,
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

        constraints = {
            'start_date': parse_date_safe(data.get('start_date')) if data.get('start_date') else None,
            'end_date': parse_date_safe(data.get('end_date')) if data.get('end_date') else None,
            'matches_per_day': int(data.get('matches_per_day', 1) or 1),
            'max_matches_per_team_per_day': max(1, int(data.get('max_matches_per_team_per_day', 1) or 1)),
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
        constraints = {
            'start_date': parse_date_safe(data.get('start_date')) if data.get('start_date') else None,
            'end_date': parse_date_safe(data.get('end_date')) if data.get('end_date') else None,
            'matches_per_day': int(data.get('matches_per_day', 1) or 1),
            'max_matches_per_team_per_day': max(1, int(data.get('max_matches_per_team_per_day', 1) or 1)),
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
