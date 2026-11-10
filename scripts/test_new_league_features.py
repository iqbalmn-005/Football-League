import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from leagues.models import Competition, TournamentFormat
from teams.models import Team, Player
from matches.models import Match, MatchStatus
from fixtures.services import generate_smart_fixtures

def run_tests():
    print("=== TESTING NEW FIXTURE, SCORE, TOP SCORER, AND REDIRECT FEATURES ===")
    client = Client()

    # Authenticate as superuser or organizer
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        user = User.objects.create_superuser('admin_tester', 'admin@touchline.football', 'password123')
    client.force_login(user)

    comp = Competition.objects.first()
    assert comp is not None, "No competition found in database"

    # TEST 1: League + Knockout in Fixture Making (Single League Group)
    print("\n[TEST 1] Testing 'League + Knockout' Fixture Generation (1 Group)...")
    config = {
        'tournament_format': TournamentFormat.LEAGUE_KNOCKOUT,
        'round_robin_type': 'single',
        'start_date': '2026-12-01',
        'matches_per_day': 2,
        'daily_kickoff_times': ['15:00', '17:30'],
        'preferred_days': ['Saturday', 'Sunday'],
        'num_groups': 1,
        'qualifiers_per_group': 4,
    }
    res = generate_smart_fixtures(comp, config)
    assert res['success'] is True, f"Fixture generation failed: {res.get('errors')}"
    matches = res['matches']
    assert len(matches) > 0, "No matches generated"

    # Verify that there's a league stage and a knockout stage
    league_matches = [m for m in matches if not m['is_knockout']]
    ko_matches = [m for m in matches if m['is_knockout']]
    print(f"  Total matches generated: {len(matches)} ({len(league_matches)} League + {len(ko_matches)} Knockout)")
    assert len(league_matches) > 0, "No league matches generated"
    assert len(ko_matches) > 0, "No knockout matches generated"

    ko_rounds = set(m['round_name'] for m in ko_matches)
    print(f"  Knockout rounds: {ko_rounds}")
    assert any("Final" in r for r in ko_rounds), "Championship Final missing from Knockout stage"
    print("  ✓ 'League + Knockout' single group engine verified!")

    # TEST 2: Score enter area without minute & Result Save redirect to ?tab=fixtures
    print("\n[TEST 2] Testing Score Enter without minute and Redirect to ?tab=fixtures...")
    # Find or create a match
    match_obj = comp.matches.first()
    if not match_obj:
        teams = list(comp.teams.all()[:2])
        match_obj = Match.objects.create(
            competition=comp,
            home_team=teams[0],
            away_team=teams[1],
            match_date='2026-12-01',
            kickoff_time='15:00',
            round_name='Matchweek 01',
            status=MatchStatus.SCHEDULED
        )

    home_player = match_obj.home_team.players.first()
    away_player = match_obj.away_team.players.first()

    # Post score result with NO minute fields provided
    post_data = {
        'home_score': 2,
        'away_score': 1,
        'home_goal_scorer': [str(home_player.id), str(home_player.id)] if home_player else [],
        'home_goal_assist': ['', ''],
        # Notice: home_goal_minute is completely omitted!
        'away_goal_scorer': [str(away_player.id)] if away_player else [],
        'away_goal_assist': [''],
        # away_goal_minute is completely omitted!
    }

    res_post = client.post(f'/organizer/match/{match_obj.id}/result/', post_data)
    print(f"  Redirect location: {res_post.url if hasattr(res_post, 'url') else res_post.headers.get('Location')}")
    redirect_url = res_post.url if hasattr(res_post, 'url') else res_post.headers.get('Location')
    assert "?tab=fixtures" in redirect_url, f"Expected redirect to ?tab=fixtures, got {redirect_url}"
    assert "?tab=results" not in redirect_url, "Still redirecting to ?tab=results!"
    print("  ✓ Saving result successfully redirects to and stays on '?tab=fixtures'!")

    # Check match updated
    match_obj.refresh_from_db()
    assert match_obj.home_score == 2
    assert match_obj.away_score == 1
    assert match_obj.status == MatchStatus.COMPLETED
    print("  ✓ Match scores and events successfully recorded without minute input!")

    # Check highlights rendering without minute
    highlights = match_obj.home_highlights
    print(f"  Home highlights: {highlights}")
    for h in highlights:
        assert "'" not in h['text'] or h['text'].endswith(")'"), f"Unexpected minute quote in text: {h['text']}"
    print("  ✓ Highlights render cleanly without minute errors!")

    # TEST 3: Template checks for minute removal and penalties removal from top scorers
    print("\n[TEST 3] Verifying organizer_index.html template changes...")
    with open('front/organizer_index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    assert '<th>PENALTIES</th>' not in html, "PENALTIES column still present in Top Scorers table"
    assert '<td>{{ s.penalties }}</td>' not in html, "s.penalties still present in Top Scorers table"
    assert 'name="${side}_goal_minute"' not in html, "goal_minute input still found in score entry!"
    assert 'name="card_minute"' not in html, "card_minute input still found in score entry!"
    assert 'value="LEAGUE_KNOCKOUT"' in html, "LEAGUE_KNOCKOUT missing from competition format options"
    print("  ✓ Template organizer_index.html verified clean!")

    # TEST 4: Template checks for fixture_generator.html
    print("\n[TEST 4] Verifying fixture_generator.html template changes...")
    with open('front/fixture_generator.html', 'r', encoding='utf-8') as f:
        fg_html = f.read()

    assert 'id="cardLeagueKnockout"' in fg_html, "cardLeagueKnockout missing in fixture_generator.html"
    assert 'value="LEAGUE_KNOCKOUT"' in fg_html, "LEAGUE_KNOCKOUT value missing in fixture_generator.html"
    assert 'League + Knockout' in fg_html, "League + Knockout text missing in fixture_generator.html"
    assert 'singleGroupInfoContainer' in fg_html, "singleGroupInfoContainer missing in fixture_generator.html"
    print("  ✓ Template fixture_generator.html verified clean!")

    print("\nALL 4 NEW REQUIREMENTS TESTED AND VERIFIED SUCCESSFULLY! ✓✓✓")

if __name__ == '__main__':
    run_tests()
