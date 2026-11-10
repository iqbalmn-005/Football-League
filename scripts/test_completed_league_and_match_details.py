import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Setup Django
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from leagues.models import Competition, CompetitionTeam, TournamentFormat, CompetitionStatus, CompetitionType
from teams.models import Team, Player
from matches.models import Match, MatchStatus, MatchEvent, MatchEventType
from standings.models import StandingEntry
from standings.services import recalculate_competition_standings
from django.template.loader import render_to_string
from leagues.organizer_views import get_competition_statistics

def run_tests():
    print("--- Starting League Completion & Match Details Tests ---")

    # 1. Setup test user & teams
    user, _ = User.objects.get_or_create(username="test_league_owner", defaults={"email": "owner@example.com"})
    team_a, _ = Team.objects.get_or_create(name="Alpha United", defaults={"short_name": "ALF"})
    team_b, _ = Team.objects.get_or_create(name="Beta City", defaults={"short_name": "BTC"})

    # Setup players
    player_a1, _ = Player.objects.get_or_create(team=team_a, full_name="Alice Striker", defaults={"jersey_number": 9, "position": "FWD"})
    player_a2, _ = Player.objects.get_or_create(team=team_a, full_name="Alan Defender", defaults={"jersey_number": 4, "position": "DEF"})
    player_b1, _ = Player.objects.get_or_create(team=team_b, full_name="Bob Winger", defaults={"jersey_number": 11, "position": "MID"})

    # 2. Setup competition
    comp, _ = Competition.objects.get_or_create(
        name="Test Championship League",
        defaults={
            "tournament_format": TournamentFormat.ROUND_ROBIN,
            "competition_type": CompetitionType.LEAGUE,
            "status": CompetitionStatus.ACTIVE,
            "max_teams": 2,
            "created_by": user,
            "primary_organizer": user
        }
    )
    # Ensure fresh state
    comp.status = CompetitionStatus.ACTIVE
    comp.save()
    comp.matches.all().delete()
    comp.standings.all().delete()
    CompetitionTeam.objects.filter(competition=comp).delete()

    CompetitionTeam.objects.create(competition=comp, team=team_a)
    CompetitionTeam.objects.create(competition=comp, team=team_b)

    import datetime
    from django.utils import timezone
    today = timezone.localdate()

    # 3. Create 2 matches: 1 scheduled, 1 completed
    m1 = Match.objects.create(
        competition=comp,
        home_team=team_a,
        away_team=team_b,
        match_date=today,
        kickoff_time=datetime.time(15, 0),
        tournament_round="Round 1",
        status=MatchStatus.SCHEDULED,
        home_score=None,
        away_score=None
    )
    m2 = Match.objects.create(
        competition=comp,
        home_team=team_b,
        away_team=team_a,
        match_date=today + datetime.timedelta(days=7),
        kickoff_time=datetime.time(15, 0),
        tournament_round="Round 2",
        status=MatchStatus.SCHEDULED,
        home_score=None,
        away_score=None
    )

    recalculate_competition_standings(comp)
    comp.refresh_from_db()
    assert not comp.is_completed, "Competition should NOT be completed when scheduled matches exist"
    assert comp.status == CompetitionStatus.ACTIVE, f"Expected ACTIVE, got {comp.status}"
    assert comp.winner is None, "Winner should be None while competition is ongoing"
    print("✓ Scheduled competition state verified (not completed, winner is None)")

    # 4. Complete match 1: Alpha 2 - 0 Beta
    m1.home_score = 2
    m1.away_score = 0
    m1.status = MatchStatus.COMPLETED
    m1.save()

    # Add events to m1: Goal by Alice Striker, Red Card to Alan Defender, Yellow card (should be ignored in highlights), Assist (ignored)
    MatchEvent.objects.create(match=m1, team=team_a, player=player_a1, event_type=MatchEventType.GOAL, minute=23)
    MatchEvent.objects.create(match=m1, team=team_a, player=player_a1, event_type=MatchEventType.GOAL, minute=65)
    MatchEvent.objects.create(match=m1, team=team_a, player=player_a2, event_type=MatchEventType.RED_CARD, minute=88)
    MatchEvent.objects.create(match=m1, team=team_a, player=player_a1, event_type=MatchEventType.YELLOW_CARD, minute=12) # Should NOT be in highlights

    # Test match highlights property
    home_hl = m1.home_highlights
    away_hl = m1.away_highlights
    print("Home highlights:", home_hl)
    print("Away highlights:", away_hl)
    assert len(home_hl) == 2, f"Expected 2 highlights (goal and red card), got {len(home_hl)}"
    assert home_hl[0]['icon'] == '⚽' and 'Alice Striker' in home_hl[0]['text'] and "23'" in home_hl[0]['text'] and "65'" in home_hl[0]['text']
    assert home_hl[1]['icon'] == '🟥' and 'Alan Defender' in home_hl[1]['text'] and "88'" in home_hl[1]['text']
    assert len(away_hl) == 0, "Beta should have no highlights"
    print("✓ Match highlights correctly format goal scorers and red cards (excluding yellow cards)")

    recalculate_competition_standings(comp)
    comp.refresh_from_db()
    assert not comp.is_completed, "Competition should NOT be completed with m2 still scheduled"
    assert comp.status == CompetitionStatus.ACTIVE
    print("✓ Partial completion correctly keeps competition ACTIVE")

    # 5. Complete match 2: Beta 1 - 1 Alpha
    m2.home_score = 1
    m2.away_score = 1
    m2.status = MatchStatus.COMPLETED
    m2.save()
    MatchEvent.objects.create(match=m2, team=team_b, player=player_b1, event_type=MatchEventType.GOAL, minute=10)
    MatchEvent.objects.create(match=m2, team=team_a, player=player_a1, event_type=MatchEventType.GOAL, minute=50)

    # Recalculate standings
    recalculate_competition_standings(comp)
    comp.refresh_from_db()

    assert comp.status == CompetitionStatus.COMPLETED, f"Expected COMPLETED status, got {comp.status}"
    assert comp.is_completed, "comp.is_completed should be True"
    assert comp.winner == team_a, f"Expected Alpha United as winner, got {comp.winner}"
    assert comp.winner_entry is not None and comp.winner_entry.team == team_a
    assert comp.winner_entry.points == 4, f"Expected Alpha United to have 4 points, got {comp.winner_entry.points}"
    print(f"✓ Competition automatically marked COMPLETED! Winner: {comp.winner.name} ({comp.winner_entry.points} pts)")

    # 6. Test template rendering
    factory = RequestFactory()
    req = factory.get(f'/competition/{comp.id}/')
    req.user = user

    completed_matches = comp.matches.filter(status=MatchStatus.COMPLETED).select_related('home_team', 'away_team', 'group').prefetch_related('events', 'events__player', 'events__team').order_by('-match_date')
    standings = StandingEntry.objects.filter(competition=comp).select_related('team').order_by('position')
    stats = get_competition_statistics(comp)

    # Render user_dashboard.html
    context_user = {
        'competition': comp,
        'active_tab': 'table',
        'teams': [team_a, team_b],
        'upcoming_matches': [],
        'completed_matches': completed_matches,
        'next_match': None,
        'last_match': completed_matches.first(),
        'standings': standings,
        'stats': stats,
    }
    rendered_user = render_to_string('user_dashboard.html', context_user, request=req)
    assert 'LEAGUE CHAMPION' in rendered_user
    assert 'Alpha United' in rendered_user
    assert '🏆 WINNER' in rendered_user
    assert 'Alice Striker' in rendered_user
    print("✓ user_dashboard.html renders champions banner, WINNER badge, and match scorer details successfully")

    # Render organizer_index.html
    context_org = {
        'has_competitions': True,
        'user_competitions': [comp],
        'active_competition': comp,
        'comp_teams': [team_a, team_b],
        'upcoming_matches': [],
        'completed_matches': completed_matches,
        'all_matches': list(completed_matches),
        'next_match': None,
        'last_match': completed_matches.first(),
        'standings': standings,
        'stats': stats,
        'all_players': [player_a1, player_a2, player_b1],
        'groups': [],
        'active_tab': 'standings',
        'user': user,
    }
    rendered_org = render_to_string('organizer_index.html', context_org, request=req)
    assert 'LEAGUE CHAMPION' in rendered_org
    assert 'Alpha United' in rendered_org
    assert '🏆 WINNER' in rendered_org
    assert 'Alice Striker' in rendered_org
    print("✓ organizer_index.html renders champions banner, WINNER badge, and match scorer details successfully")

    # 7. Test reversion if a match becomes uncompleted
    m2.status = MatchStatus.SCHEDULED
    m2.home_score = None
    m2.away_score = None
    m2.save()
    recalculate_competition_standings(comp)
    comp.refresh_from_db()
    assert comp.status == CompetitionStatus.ACTIVE, f"Expected reverted status to ACTIVE, got {comp.status}"
    assert not comp.is_completed
    assert comp.winner is None
    print("✓ Reverting a match to SCHEDULED properly reverts competition status back to ACTIVE")

    # Clean up test data
    comp.matches.all().delete()
    comp.standings.all().delete()
    comp.delete()
    team_a.delete()
    team_b.delete()
    user.delete()
    print("--- ALL TESTS PASSED SUCCESSFULLY! ---")

if __name__ == '__main__':
    run_tests()
