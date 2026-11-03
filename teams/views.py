"""
Teams application views - Pure Django views for club profiles, rosters, squads, and players.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from accounts.decorators import approved_organizer_required
from leagues.models import Competition, CompetitionTeam
from teams.models import Team, Player, PositionChoice
from matches.models import MatchStatus


def team_profile(request, team_id):
    """
    Django backend view: Renders dedicated team profile page with squad, manager, and recent matches.
    """
    team = get_object_or_404(Team, id=team_id)
    players = team.players.filter(is_active=True).order_by('jersey_number')

    home_matches = team.home_matches.filter(status=MatchStatus.COMPLETED)
    away_matches = team.away_matches.filter(status=MatchStatus.COMPLETED)
    total_played = home_matches.count() + away_matches.count()

    wins = sum(1 for m in home_matches if m.home_score > m.away_score) + \
           sum(1 for m in away_matches if m.away_score > m.home_score)
    win_pct = round((wins / total_played * 100), 1) if total_played > 0 else 0

    recent_matches = (home_matches | away_matches).order_by('-match_date')[:5]

    context = {
        'team': team,
        'players': players,
        'total_played': total_played,
        'wins': wins,
        'win_pct': win_pct,
        'recent_matches': recent_matches,
    }
    return render(request, 'team.html', context)


def api_player_details(request, player_id):
    """
    Django JSON API endpoint: Returns player stats, headshot, goals, assists, and disciplinary cards.
    """
    player = get_object_or_404(Player, id=player_id)
    return JsonResponse({
        'id': player.id,
        'full_name': player.full_name,
        'jersey_number': player.jersey_number,
        'position': player.get_position_display(),
        'position_code': player.position,
        'team_id': player.team.id,
        'team_name': player.team.name,
        'team_short': player.team.short_name,
        'goals': player.total_goals,
        'assists': player.total_assists,
        'yellow_cards': player.yellow_cards,
        'red_cards': player.red_cards,
        'appearances': player.appearances,
        'clean_sheets': player.clean_sheets,
        'photo_url': player.get_photo_url(),
        'nationality': player.nationality,
        'is_captain': player.is_captain,
        'age': player.age or "N/A",
    })


@approved_organizer_required
def add_team_view(request, comp_id):
    """
    Django backend view: Registers a new team into the competition.
    """
    comp = get_object_or_404(Competition, id=comp_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        manager = request.POST.get('manager_name', '').strip()
        venue = request.POST.get('home_venue', '').strip()
        city = request.POST.get('city', '').strip()
        logo_url = request.POST.get('logo_url', '').strip()
        logo_file = request.FILES.get('logo')

        if not name:
            messages.error(request, "Team name is required.")
            return redirect(f"/organizer/{comp.id}/?tab=teams")

        if comp.teams.count() >= comp.max_teams:
            messages.error(request, f"Cannot add team. Maximum capacity of {comp.max_teams} teams reached.")
            return redirect(f"/organizer/{comp.id}/?tab=teams")

        team = Team.objects.create(
            name=name,
            short_name=short_name or name[:3].upper(),
            manager_name=manager,
            home_venue=venue,
            city=city,
            logo_url=logo_url,
            logo=logo_file
        )

        CompetitionTeam.objects.create(competition=comp, team=team)
        messages.success(request, f"✓ Team '{team.name}' registered to {comp.name} successfully!")

    return redirect(f"/organizer/{comp.id}/?tab=teams")


@approved_organizer_required
def organizer_team_detail(request, team_id):
    """
    Django backend view: Renders organizer squad & player cards view with player management.
    """
    team = get_object_or_404(Team, id=team_id)
    comp_id = request.GET.get('competition')
    active_competition = None
    if comp_id:
        active_competition = Competition.objects.filter(id=comp_id).first()
    if not active_competition:
        comp_team = CompetitionTeam.objects.filter(team=team).select_related('competition').first()
        if comp_team:
            active_competition = comp_team.competition

    players = team.players.all().order_by('jersey_number')

    gk_count = players.filter(position=PositionChoice.GK).count()
    def_count = players.filter(position=PositionChoice.DEF).count()
    mid_count = players.filter(position=PositionChoice.MID).count()
    fwd_count = players.filter(position=PositionChoice.FWD).count()

    context = {
        'team': team,
        'active_competition': active_competition,
        'players': players,
        'gk_count': gk_count,
        'def_count': def_count,
        'mid_count': mid_count,
        'fwd_count': fwd_count,
        'positions': PositionChoice.choices,
    }
    return render(request, 'organizer_team_detail.html', context)


@approved_organizer_required
def add_player_view(request, team_id):
    """
    Django backend view: Registers a new player to a team roster.
    """
    team = get_object_or_404(Team, id=team_id)

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        jersey_number = request.POST.get('jersey_number', 0)
        position = request.POST.get('position', PositionChoice.FWD)
        photo_file = request.FILES.get('photo')
        photo_url = request.POST.get('photo_url', '').strip()

        if not full_name:
            messages.error(request, "Player name is required.")
            return redirect(request.META.get('HTTP_REFERER', f'/organizer/team/{team.id}/'))

        try:
            jersey_number = int(jersey_number)
        except ValueError:
            jersey_number = 1

        # Check if jersey number already exists in this team
        if Player.objects.filter(team=team, jersey_number=jersey_number).exists():
            messages.error(request, f"Jersey #{jersey_number} is already taken in {team.name}. Please select a different number.")
            return redirect(request.META.get('HTTP_REFERER', f'/organizer/team/{team.id}/'))

        Player.objects.create(
            team=team,
            full_name=full_name,
            jersey_number=jersey_number,
            position=position,
            photo=photo_file,
            photo_url=photo_url
        )
        messages.success(request, f"✓ Player '{full_name}' (#{jersey_number}) added to {team.name} successfully!")

    return redirect(request.META.get('HTTP_REFERER', f'/organizer/team/{team.id}/'))


@approved_organizer_required
def delete_player_view(request, team_id, player_id):
    """
    Django backend view: Removes a player from a team roster.
    """
    team = get_object_or_404(Team, id=team_id)
    player = get_object_or_404(Player, id=player_id, team=team)

    if request.method == 'POST':
        name = player.full_name
        num = player.jersey_number
        player.delete()
        messages.success(request, f"✓ Player '{name}' (#{num}) removed from {team.name}.")

    return redirect(request.META.get('HTTP_REFERER', f'/organizer/team/{team.id}/'))
