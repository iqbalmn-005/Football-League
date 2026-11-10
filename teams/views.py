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
from standings.models import StandingEntry


def _get_team_stats(team, active_competition=None):
    """
    Helper function to get or compute standing stats and recent/upcoming matches for a team.
    """
    standing = None
    if active_competition:
        standing = StandingEntry.objects.filter(competition=active_competition, team=team).first()
    else:
        standing = StandingEntry.objects.filter(team=team).first()

    if standing:
        played = standing.played
        points = standing.points
        position = standing.position
        goals_for = standing.goals_for
        goals_against = standing.goals_against
        goal_diff = standing.goal_difference
        won = standing.won
        drawn = standing.drawn
        lost = standing.lost
    else:
        if active_competition:
            h_matches = team.home_matches.filter(competition=active_competition, status=MatchStatus.COMPLETED)
            a_matches = team.away_matches.filter(competition=active_competition, status=MatchStatus.COMPLETED)
        else:
            h_matches = team.home_matches.filter(status=MatchStatus.COMPLETED)
            a_matches = team.away_matches.filter(status=MatchStatus.COMPLETED)

        played = h_matches.count() + a_matches.count()
        won = sum(1 for m in h_matches if m.home_score > m.away_score) + sum(1 for m in a_matches if m.away_score > m.home_score)
        drawn = sum(1 for m in h_matches if m.home_score == m.away_score) + sum(1 for m in a_matches if m.away_score == m.home_score)
        lost = played - won - drawn
        goals_for = sum(m.home_score for m in h_matches) + sum(m.away_score for m in a_matches)
        goals_against = sum(m.away_score for m in h_matches) + sum(m.home_score for m in a_matches)
        goal_diff = goals_for - goals_against
        points = (won * 3) + drawn
        position = "-"

    win_rate = round((won / played * 100), 1) if played > 0 else 0

    if active_competition:
        h_completed = team.home_matches.filter(competition=active_competition, status=MatchStatus.COMPLETED)
        a_completed = team.away_matches.filter(competition=active_competition, status=MatchStatus.COMPLETED)
        clean_sheets = sum(1 for m in h_completed if m.away_score == 0) + sum(1 for m in a_completed if m.home_score == 0)
        recent_matches = (h_completed | a_completed).order_by('-match_date', '-kickoff_time')[:5]
        upcoming_matches = (team.home_matches.filter(competition=active_competition, status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED]) |
                            team.away_matches.filter(competition=active_competition, status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED])).order_by('match_date', 'kickoff_time')[:5]
    else:
        h_completed = team.home_matches.filter(status=MatchStatus.COMPLETED)
        a_completed = team.away_matches.filter(status=MatchStatus.COMPLETED)
        clean_sheets = sum(1 for m in h_completed if m.away_score == 0) + sum(1 for m in a_completed if m.home_score == 0)
        recent_matches = (h_completed | a_completed).order_by('-match_date', '-kickoff_time')[:5]
        upcoming_matches = (team.home_matches.filter(status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED]) |
                            team.away_matches.filter(status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED])).order_by('match_date', 'kickoff_time')[:5]

    return {
        'standing': standing,
        'played': played,
        'points': points,
        'position': position,
        'goals_for': goals_for,
        'goals_against': goals_against,
        'goal_diff': goal_diff,
        'won': won,
        'drawn': drawn,
        'lost': lost,
        'win_rate': win_rate,
        'clean_sheets': clean_sheets,
        'recent_matches': recent_matches,
        'upcoming_matches': upcoming_matches,
    }


def team_profile(request, team_id):
    """
    Django backend view: Renders dedicated team profile page with stats, recent matches and fixtures.
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

    players = team.players.filter(is_active=True).order_by('jersey_number')
    stats = _get_team_stats(team, active_competition)

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
        **stats,
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

    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(f"/competition/{comp.id}/")

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

        # Get or create team using valid Team model fields
        team = Team.objects.filter(name__iexact=name).first()
        if not team:
            create_kwargs = {
                'name': name,
                'short_name': short_name or name[:3].upper(),
                'manager_name': manager,
                'created_by': request.user
            }
            if logo_file:
                create_kwargs['logo'] = logo_file
            team = Team.objects.create(**create_kwargs)
        else:
            if logo_file and not team.logo:
                team.logo = logo_file
                team.save()

        # Check if already registered in this competition
        if CompetitionTeam.objects.filter(competition=comp, team=team).exists():
            messages.info(request, f"Team '{team.name}' is already registered in {comp.name}.")
        else:
            CompetitionTeam.objects.create(competition=comp, team=team)
            messages.success(request, f"✓ Team '{team.name}' registered to {comp.name} successfully!")

        try:
            from standings.services import recalculate_competition_standings
            recalculate_competition_standings(comp)
        except Exception:
            pass

    return redirect(f"/organizer/{comp.id}/?tab=teams")


@approved_organizer_required
def organizer_team_detail(request, team_id):
    """
    Django backend view: Renders organizer team detail view with standings stats and match schedule.
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
    stats = _get_team_stats(team, active_competition)

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
        **stats,
    }
    return render(request, 'organizer_team_detail.html', context)


@approved_organizer_required
def add_player_view(request, team_id):
    """
    Django backend view: Registers a new player to a team roster.
    """
    team = get_object_or_404(Team, id=team_id)

    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(request.META.get('HTTP_REFERER', '/super-admin/?tab=leagues'))

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

    if request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_super_admin):
        messages.error(request, "Administrators have oversight access only and cannot edit tournament fixtures, teams, or players.")
        return redirect(request.META.get('HTTP_REFERER', '/super-admin/?tab=leagues'))

    if request.method == 'POST':
        name = player.full_name
        num = player.jersey_number
        player.delete()
        messages.success(request, f"✓ Player '{name}' (#{num}) removed from {team.name}.")

    return redirect(request.META.get('HTTP_REFERER', f'/organizer/team/{team.id}/'))
