from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
from accounts.models import UserRole, OrganizerStatus
from leagues.models import Competition, CompetitionCategory, CompetitionStatus
from teams.models import Team, Player
from matches.models import Match, MatchStatus
from standings.models import StandingEntry
from matches.services import get_competition_statistics


def landing_page(request):
    """
    Public landing page (front/list.html).
    Displays featured leagues, upcoming tournaments, search/filtering, and stats.
    Public viewers can see all tournaments without logging in.
    Logged in Organizers and Super Admins are sent directly to their management dashboards.
    """
    if request.user.is_authenticated and not request.GET.get('public'):
        profile = getattr(request.user, 'profile', None)
        if request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN):
            return redirect('super_admin_dashboard')
        elif profile and profile.role == UserRole.ORGANIZER:
            if profile.organizer_status == OrganizerStatus.APPROVED and profile.is_active_organizer:
                return redirect('organizer_dashboard')
            elif profile.organizer_status in [OrganizerStatus.PENDING, OrganizerStatus.REJECTED, OrganizerStatus.SUSPENDED]:
                return redirect('organizer_status')
            else:
                return redirect('organizer_apply')

    category = request.GET.get('category', 'all')
    search_query = request.GET.get('q', '').strip()

    competitions_qs = Competition.objects.filter(is_published=True).select_related('primary_organizer').prefetch_related('teams')

    if category != 'all':
        competitions_qs = competitions_qs.filter(category=category)

    if search_query:
        competitions_qs = competitions_qs.filter(
            Q(name__icontains=search_query) |
            Q(location__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    competitions = list(competitions_qs.order_by('-created_at'))

    # If no competitions in db yet, we handle gracefully
    featured_comp = competitions[0] if competitions else None

    # Global KPI stats
    total_leagues = Competition.objects.filter(is_published=True).count()
    total_teams = Team.objects.count()
    total_matches = Match.objects.count()

    context = {
        'competitions': competitions,
        'featured_comp': featured_comp,
        'selected_category': category,
        'search_query': search_query,
        'total_leagues': total_leagues,
        'total_teams': total_teams,
        'total_matches': total_matches,
    }
    return render(request, 'list.html', context)


def competition_viewer(request, comp_id):
    """
    Public viewer for a specific league or tournament (front/user_dashboard.html).
    Contains: Upcoming Matches, Results, Standings, Statistics, Teams.
    """
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        competition = get_object_or_404(Competition, id=comp_id)
    else:
        competition = get_object_or_404(Competition, id=comp_id, is_published=True)

    tab = request.GET.get('tab', 'upcoming')
    if tab == 'matches':
        tab = 'upcoming'

    teams = competition.teams.all().prefetch_related('players')
    fixture_filter = request.GET.get('fixture_filter', 'all')
    upcoming_matches = competition.matches.filter(
        status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED]
    ).order_by('match_date', 'kickoff_time')

    if fixture_filter == 'week':
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        end_of_week = today + timedelta(days=7)
        upcoming_matches = upcoming_matches.filter(match_date__gte=today, match_date__lte=end_of_week)

    completed_matches = competition.matches.filter(
        status=MatchStatus.COMPLETED
    ).order_by('-match_date', '-kickoff_time')

    next_match = upcoming_matches.first()
    last_match = completed_matches.first()

    standings = StandingEntry.objects.filter(competition=competition).select_related('team').order_by('position')
    stats = get_competition_statistics(competition)

    context = {
        'competition': competition,
        'active_tab': tab,
        'fixture_filter': fixture_filter,
        'teams': teams,
        'upcoming_matches': upcoming_matches,
        'completed_matches': completed_matches,
        'next_match': next_match,
        'last_match': last_match,
        'standings': standings,
        'stats': stats,
    }
    return render(request, 'user_dashboard.html', context)


def team_profile(request, team_id):
    """
    Public team profile view (front/team.html).
    Displays squad, manager, recent matches, upcoming matches, and team performance.
    """
    team = get_object_or_404(Team, id=team_id)
    players = team.players.filter(is_active=True).order_by('jersey_number')

    home_completed = team.home_matches.filter(status=MatchStatus.COMPLETED)
    away_completed = team.away_matches.filter(status=MatchStatus.COMPLETED)
    all_completed = list(home_completed) + list(away_completed)
    all_completed = sorted(all_completed, key=lambda m: (m.match_date, m.kickoff_time), reverse=True)

    home_upcoming = team.home_matches.filter(status=MatchStatus.SCHEDULED)
    away_upcoming = team.away_matches.filter(status=MatchStatus.SCHEDULED)
    all_upcoming = list(home_upcoming) + list(away_upcoming)
    all_upcoming = sorted(all_upcoming, key=lambda m: (m.match_date, m.kickoff_time))

    # Calculate overall team stats
    played = len(all_completed)
    won = 0
    drawn = 0
    lost = 0
    goals_for = 0
    goals_against = 0
    clean_sheets = 0

    for m in all_completed:
        is_home = (m.home_team_id == team.id)
        scored = m.home_score if is_home else m.away_score
        conceded = m.away_score if is_home else m.home_score
        scored = scored or 0
        conceded = conceded or 0

        goals_for += scored
        goals_against += conceded

        if conceded == 0:
            clean_sheets += 1

        if scored > conceded:
            won += 1
        elif scored < conceded:
            lost += 1
        else:
            drawn += 1

    points = (won * 3) + drawn
    goal_diff = goals_for - goals_against
    win_rate = round((won / played) * 100, 1) if played > 0 else 0

    # Recent form (last 5)
    form_results = []
    for m in all_completed[:5]:
        is_home = (m.home_team_id == team.id)
        sc = m.home_score if is_home else m.away_score
        cc = m.away_score if is_home else m.home_score
        sc = sc or 0
        cc = cc or 0
        if sc > cc:
            form_results.append('W')
        elif sc < cc:
            form_results.append('L')
        else:
            form_results.append('D')

    context = {
        'team': team,
        'players': players,
        'recent_matches': all_completed[:6],
        'upcoming_matches': all_upcoming[:6],
        'played': played,
        'won': won,
        'drawn': drawn,
        'lost': lost,
        'goals_for': goals_for,
        'goals_against': goals_against,
        'goal_diff': goal_diff,
        'points': points,
        'win_rate': win_rate,
        'clean_sheets': clean_sheets,
        'form_results': form_results,
    }
    return render(request, 'team.html', context)


def api_match_details(request, match_id):
    """
    JSON API for match details popup modal.
    """
    match = get_object_or_404(Match, id=match_id)
    events = match.events.select_related('player', 'team', 'assist_player').all()

    home_events = []
    away_events = []

    for ev in events:
        ev_data = {
            'minute': ev.minute,
            'player_name': ev.player.full_name,
            'jersey_number': ev.player.jersey_number,
            'event_type': ev.event_type,
            'assist_name': ev.assist_player.full_name if ev.assist_player else None,
            'description': ev.description
        }
        if ev.team_id == match.home_team_id:
            home_events.append(ev_data)
        else:
            away_events.append(ev_data)

    data = {
        'id': match.id,
        'competition_name': match.competition.name,
        'tournament_round': match.tournament_round,
        'match_date': match.match_date.strftime('%A, %d %b %Y'),
        'kickoff_time': match.kickoff_time.strftime('%H:%M'),
        'venue': match.venue,
        'status': match.get_status_display(),
        'is_completed': match.is_finished,
        'home_team': {
            'id': match.home_team.id,
            'name': match.home_team.name,
            'short_name': match.home_team.short_name,
            'logo_url': match.home_team.get_logo_url(),
            'score': match.home_score if match.home_score is not None else "-",
        },
        'away_team': {
            'id': match.away_team.id,
            'name': match.away_team.name,
            'short_name': match.away_team.short_name,
            'logo_url': match.away_team.get_logo_url(),
            'score': match.away_score if match.away_score is not None else "-",
        },
        'home_events': home_events,
        'away_events': away_events,
    }
    return JsonResponse(data)


def api_player_details(request, player_id):
    """
    JSON API for player profile popup modal.
    """
    player = get_object_or_404(Player, id=player_id)
    data = {
        'id': player.id,
        'full_name': player.full_name,
        'jersey_number': player.jersey_number,
        'position': player.get_position_display(),
        'team_id': player.team.id,
        'team_name': player.team.name,
        'photo_url': player.get_photo_url(),
        'age': player.age or "N/A",
        'nationality': player.nationality,
        'goals': player.total_goals,
        'assists': player.total_assists,
        'yellow_cards': player.yellow_cards,
        'red_cards': player.red_cards,
        'appearances': player.appearances,
        'clean_sheets': player.clean_sheets,
    }
    return JsonResponse(data)

