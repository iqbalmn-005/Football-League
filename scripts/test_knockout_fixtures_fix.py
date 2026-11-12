import os
import sys
import django
from datetime import date, time, timedelta

# Setup django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from leagues.models import Competition, TournamentFormat, CompetitionStatus
from teams.models import Team
from matches.models import Match, MatchStatus
from fixtures.services import generate_smart_fixtures, commit_generated_fixtures, advance_knockout_bracket

def run_tests():
    print("=== STARTING KNOCKOUT FIXTURE & UI LOGIC TESTS ===")

    # Test 1: Generate fixtures for Single Elimination (4 teams)
    # Ensure at least 4 test teams exist
    comp, _ = Competition.objects.get_or_create(
        name="Test Knockout Championship",
        defaults={
            'tournament_format': TournamentFormat.SINGLE_ELIMINATION,
            'status': CompetitionStatus.UPCOMING,
            'start_date': date(2026, 11, 26),
            'end_date': date(2026, 11, 28)
        }
    )
    comp.tournament_format = TournamentFormat.SINGLE_ELIMINATION
    comp.start_date = date(2026, 11, 26)
    comp.end_date = date(2026, 11, 28)
    comp.save()

    # Clear existing matches
    comp.matches.all().delete()

    teams = []
    for code, name in [('FD', 'Fortaleza Dragons'), ('VF', 'Vanguard FC'), ('FF', 'Falcon FC'), ('RR', 'Rapid Rovers')]:
        t, _ = Team.objects.get_or_create(short_name=code, defaults={'name': name, 'home_venue': 'Central Stadium'})
        teams.append(t)
        if not comp.teams.filter(id=t.id).exists():
            comp.teams.add(t)

    config = {
        'tournament_format': TournamentFormat.SINGLE_ELIMINATION,
        'tournament_type': 'single_elimination',
        'knockout_legs': 'single',
        'start_date': '2026-11-26',
        'end_date': '2026-11-28',
        'matches_per_day': 2,
        'daily_kickoff_times': ['15:00', '17:30'],
        'preferred_days': ['Thursday', 'Friday', 'Saturday'],
        'venues': ['Central Stadium', 'Metropolis Arena']
    }

    res = generate_smart_fixtures(comp, config)
    assert res['success'], f"Fixture generation failed: {res.get('errors')}"
    matches = res['matches']
    print(f"Generated {len(matches)} preview matches.")

    # REQUIREMENT 1: Use Placeholders for the Final (no real club names pre-assigned)
    sf_matches = [m for m in matches if 'Semi-Final' in m['round_name']]
    final_matches = [m for m in matches if 'Final' in m['round_name'] and 'Semi' not in m['round_name']]

    assert len(sf_matches) == 2, f"Expected 2 SF matches, got {len(sf_matches)}"
    assert len(final_matches) == 1, f"Expected 1 Final match, got {len(final_matches)}"

    final_preview = final_matches[0]
    print(f"Final preview: '{final_preview['home_team_name']}' vs '{final_preview['away_team_name']}'")
    assert final_preview['home_team_id'] is None, f"Final home team id should be None, got {final_preview['home_team_id']}"
    assert final_preview['away_team_id'] is None, f"Final away team id should be None, got {final_preview['away_team_id']}"
    assert 'Winner of Semi-Final 1' in final_preview['home_team_name'], f"Unexpected home name: {final_preview['home_team_name']}"
    assert 'Winner of Semi-Final 2' in final_preview['away_team_name'], f"Unexpected away name: {final_preview['away_team_name']}"
    print("PASS: Final uses placeholders before Semi-Finals are played.")

    # REQUIREMENT 2: Sequential Match Scheduling (Final date > SF date when possible)
    sf_date_1 = sf_matches[0]['match_date']
    sf_date_2 = sf_matches[1]['match_date']
    final_date = final_preview['match_date']
    print(f"SF Dates: {sf_date_1}, {sf_date_2} | Final Date: {final_date}")
    assert final_date > sf_date_1, f"Final date ({final_date}) should be after SF date ({sf_date_1})"
    print("PASS: Sequential scheduling across dates verified.")

    # REQUIREMENT 3: Prevent Venue Double-Booking
    slot_set = set()
    for m in matches:
        key = (m['match_date'], m['kickoff_time'], m['venue'])
        assert key not in slot_set, f"Venue double-booking detected: {key}"
        slot_set.add(key)
    print(f"PASS: No venue double-booking among all {len(matches)} matches.")

    # Test Single-Day Tournament Sequential Scheduling (compressed to 1 day)
    config_1day = dict(config)
    config_1day['start_date'] = '2026-11-26'
    config_1day['end_date'] = '2026-11-26'
    res_1day = generate_smart_fixtures(comp, config_1day)
    assert res_1day['success']
    matches_1day = res_1day['matches']
    sf_1day = [m for m in matches_1day if 'Semi-Final' in m['round_name']]
    final_1day = [m for m in matches_1day if 'Final' in m['round_name'] and 'Semi' not in m['round_name']][0]
    sf_latest_kickoff = max(m['kickoff_time'] for m in sf_1day)
    print(f"Single-day tournament - SF kickoff: {sf_latest_kickoff}, Final kickoff: {final_1day['kickoff_time']}")
    assert final_1day['kickoff_time'] > sf_latest_kickoff, "Final must kick off after Semi-Finals on single-day event!"
    # Check no double booking on 1-day tournament
    slot_set_1day = set()
    for m in matches_1day:
        key = (m['match_date'], m['kickoff_time'], m['venue'])
        assert key not in slot_set_1day, f"Venue double-booking on single-day event: {key}"
        slot_set_1day.add(key)
    print("PASS: Single-day tournament has sequential kickoff times and no venue double-booking.")

    # REQUIREMENT 4: Test Commit & Database Persistence of Placeholders + Dynamic Advancement
    saved_matches = commit_generated_fixtures(comp, matches, tournament_format='SINGLE_ELIMINATION')
    assert len(saved_matches) == 3, f"Expected 3 saved matches, got {len(saved_matches)}"

    db_final = comp.matches.filter(tournament_round__icontains='Final').exclude(tournament_round__icontains='Semi').first()
    assert db_final is not None
    assert db_final.home_team is None, f"db_final.home_team should be None, got {db_final.home_team}"
    assert db_final.away_team is None, f"db_final.away_team should be None, got {db_final.away_team}"
    assert db_final.placeholder_home == 'Winner of Semi-Final 1'
    assert db_final.placeholder_away == 'Winner of Semi-Final 2'
    assert db_final.home_display_name == 'Winner of Semi-Final 1'
    assert db_final.away_display_name == 'Winner of Semi-Final 2'
    assert 'Winner of Semi-Final 1 vs Winner of Semi-Final 2' in str(db_final)
    print(f"PASS: Database Match saved with placeholders: {db_final}")

    # Now play Semi-Final 1
    db_sfs = list(comp.matches.filter(tournament_round__icontains='Semi-Final').order_by('match_date', 'kickoff_time', 'id'))
    sf1 = db_sfs[0]
    sf2 = db_sfs[1]

    sf1.home_score = 2
    sf1.away_score = 1
    sf1.status = MatchStatus.COMPLETED
    sf1.save()
    advance_knockout_bracket(comp)

    db_final.refresh_from_db()
    print(f"After SF1 finished: Final is now '{db_final.home_display_name}' vs '{db_final.away_display_name}'")
    assert db_final.home_team == sf1.home_team, f"Expected {sf1.home_team}, got {db_final.home_team}"
    assert db_final.away_team is None, "Away team should still be placeholder"
    assert db_final.away_display_name == 'Winner of Semi-Final 2'

    # Now play Semi-Final 2
    sf2.home_score = 0
    sf2.away_score = 3
    sf2.status = MatchStatus.COMPLETED
    sf2.save()
    advance_knockout_bracket(comp)

    db_final.refresh_from_db()
    print(f"After SF2 finished: Final is now '{db_final.home_display_name}' vs '{db_final.away_display_name}'")
    assert db_final.home_team == sf1.home_team
    assert db_final.away_team == sf2.away_team
    assert db_final.home_display_name == sf1.home_team.name
    assert db_final.away_display_name == sf2.away_team.name
    print("PASS: Dynamic bracket advancement into Final successfully updated teams!")

    print("\nALL KNOCKOUT LOGIC & WORKFLOW TESTS PASSED!")

if __name__ == '__main__':
    run_tests()
