import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from django.test import Client
from leagues.models import Competition
from matches.models import Match, MatchEvent, MatchEventType, MatchStatus
from matches.services import get_competition_statistics

def test_result_entry():
    print("=== Testing Result Entry with Multiple Goals, Penalties, Assists, and Cards ===")
    
    # 1. Find a match with teams that have players
    match = None
    for m in Match.objects.all():
        if m.home_team.players.count() >= 3 and m.away_team.players.count() >= 2:
            match = m
            break

    assert match is not None, "No suitable match found with squad players"
    comp = match.competition
    org_user = comp.primary_organizer
    assert org_user is not None, "No organizer on competition"

    home_players = list(match.home_team.players.filter(is_active=True))
    away_players = list(match.away_team.players.filter(is_active=True))

    print(f"Match: {match.home_team.name} vs {match.away_team.name} (Competition: {comp.name})")

    client = Client()
    client.force_login(org_user)

    # 2. Test API match details returns players
    resp_api = client.get(f'/api/match/{match.id}/')
    assert resp_api.status_code == 200
    data = resp_api.json()
    assert 'players' in data['home_team']
    assert len(data['home_team']['players']) >= 3
    assert 'players' in data['away_team']
    print(f"[OK] /api/match/{match.id}/ returned {len(data['home_team']['players'])} home players and {len(data['away_team']['players'])} away players.")

    # 3. Simulate submitting 3 home goals and 1 away goal:
    # - Home Goal 1: scorer=P0, assist=P1, regular
    # - Home Goal 2: scorer=P1, assist=None, regular
    # - Home Goal 3: scorer=P2, assist=None, penalty!
    # - Away Goal 1: scorer=A0, assist=A1, regular
    # - Cards: Yellow card for Home P0, Red card for Away A0
    post_data = {
        'home_score': 3,
        'away_score': 1,
        # Home goals
        'home_goal_scorer': [str(home_players[0].id), str(home_players[1].id), str(home_players[2].id)],
        'home_goal_assist': [str(home_players[1].id), '', ''],
        'home_goal_minute': ['14', '35', '78'],
        'home_goal_penalty_2': '1', # 3rd goal is penalty
        # Away goals
        'away_goal_scorer': [str(away_players[0].id)],
        'away_goal_assist': [str(away_players[1].id)],
        'away_goal_minute': ['55'],
        # Cards
        'card_team': ['home', 'away'],
        'card_player': [str(home_players[0].id), str(away_players[0].id)],
        'card_type': ['YELLOW_CARD', 'RED_CARD'],
        'card_minute': ['42', '89'],
    }

    resp_post = client.post(f'/organizer/match/{match.id}/result/', post_data, follow=True)
    assert resp_post.status_code == 200
    print("[OK] Submitted result form successfully.")

    # 4. Verify match status and score in DB
    match.refresh_from_db()
    assert match.home_score == 3
    assert match.away_score == 1
    assert match.status == MatchStatus.COMPLETED
    print(f"[OK] Match updated in DB: {match.display_score}, status: {match.status}")

    # 5. Verify MatchEvents in DB
    events = list(match.events.all().order_by('minute'))
    assert len(events) == 6, f"Expected 6 events (4 goals + 2 cards), found {len(events)}"

    home_goals = [e for e in events if e.team == match.home_team and e.event_type in [MatchEventType.GOAL, MatchEventType.PENALTY]]
    assert len(home_goals) == 3, f"Expected 3 home goals, got {len(home_goals)}"

    # Check 1st goal: regular with assist
    assert home_goals[0].event_type == MatchEventType.GOAL
    assert home_goals[0].player == home_players[0]
    assert home_goals[0].assist_player == home_players[1]
    assert home_goals[0].minute == 14

    # Check 2nd goal: regular without assist
    assert home_goals[1].event_type == MatchEventType.GOAL
    assert home_goals[1].player == home_players[1]
    assert home_goals[1].assist_player is None

    # Check 3rd goal: penalty without assist
    assert home_goals[2].event_type == MatchEventType.PENALTY
    assert home_goals[2].player == home_players[2]
    assert home_goals[2].assist_player is None

    # Check away goal: regular with assist
    away_goals = [e for e in events if e.team == match.away_team and e.event_type == MatchEventType.GOAL]
    assert len(away_goals) == 1
    assert away_goals[0].player == away_players[0]
    assert away_goals[0].assist_player == away_players[1]

    # Check cards
    yellow_cards = [e for e in events if e.event_type == MatchEventType.YELLOW_CARD]
    assert len(yellow_cards) == 1
    assert yellow_cards[0].player == home_players[0]

    red_cards = [e for e in events if e.event_type == MatchEventType.RED_CARD]
    assert len(red_cards) == 1
    assert red_cards[0].player == away_players[0]

    print("[OK] Verified in DB: 3 home goals (2 regular, 1 penalty, optional assists handled), 1 away goal, 1 yellow card, 1 red card.")

    # 6. Verify competition statistics
    stats = get_competition_statistics(comp)
    scorers = {s['id']: s for s in stats['top_scorers']}
    assert home_players[0].id in scorers or home_players[1].id in scorers or home_players[2].id in scorers
    print("[OK] Verified: Competition top scorers and statistics reflect the recorded goals and penalties.")

    # 7. Verify API reflects the new events
    resp_api2 = client.get(f'/api/match/{match.id}/')
    data2 = resp_api2.json()
    assert len(data2['home_events']) == 4 # 3 goals + 1 yellow card
    assert len(data2['away_events']) == 2 # 1 goal + 1 red card
    print("[OK] Verified: /api/match/<id>/ returns complete events timeline.")

    print("\nALL RESULT ENTRY TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    test_result_entry()

