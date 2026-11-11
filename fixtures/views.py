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
    DEFAULT_VENUES,
    DEFAULT_KICKOFF_TIMES
)


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
    comp = get_object_or_404(Competition, id=comp_id)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        return JsonResponse({'success': False, 'errors': [f"Invalid request data: {str(e)}"]}, status=400)

    result = generate_smart_fixtures(competition=comp, config=data)
    return JsonResponse(result)


@approved_organizer_required
@require_POST
def api_publish_fixtures(request, comp_id):
    """
    Django JSON API endpoint: Finalizes and atomically commits generated (and edited) fixtures to DB.
    """
    comp = get_object_or_404(Competition, id=comp_id)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        return JsonResponse({'success': False, 'errors': [f"Invalid request data: {str(e)}"]}, status=400)

    matches_data = data.get('matches', [])
    groups_data = data.get('groups', {})
    tournament_format = data.get('tournament_format')

    if not matches_data:
        return JsonResponse({'success': False, 'errors': ["No fixtures to publish. Please generate fixtures first."]}, status=400)

    created_matches = commit_generated_fixtures(
        competition=comp,
        matches_data=matches_data,
        groups_data=groups_data,
        tournament_format=tournament_format
    )

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

    team_count = comp.teams.count()
    if team_count < 2:
        messages.error(request, "At least 2 teams are required to generate round-robin fixtures.")
        return redirect('organizer_competition_dashboard', comp_id=comp.id)

    double_round = request.POST.get('double_round') == 'on' or request.POST.get('double_round') == 'true'

    created_matches = generate_round_robin_fixtures(
        competition=comp,
        start_date=comp.start_date or date.today(),
        double_round=double_round
    )

    messages.success(request, f"✓ Successfully generated {len(created_matches)} match fixtures for {comp.name}!")
    return redirect(f"/organizer/{comp.id}/?tab=fixtures")


@approved_organizer_required
def add_fixture_view(request, comp_id):
    """
    Django backend view: Adds a single fixture scheduled between two teams.
    """
    comp = get_object_or_404(Competition, id=comp_id)

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
