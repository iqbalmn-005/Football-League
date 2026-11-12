import os
import sys
import django
from datetime import date
from collections import Counter

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from leagues.models import Competition, TournamentFormat, CompetitionStatus
from teams.models import Team
from fixtures.services import generate_smart_fixtures

def test_user_scenario():
    print("Testing user scenario (8 teams, 2 matches/day, Sundays only)...")
    comp, _ = Competition.objects.get_or_create(
        name="User Scenario League",
        defaults={
            'tournament_format': TournamentFormat.SINGLE_ELIMINATION,
            'status': CompetitionStatus.UPCOMING,
            'start_date': date(2026, 11, 20),
            'end_date': date(2026, 12, 13)
        }
    )
    comp.tournament_format = TournamentFormat.SINGLE_ELIMINATION
    comp.start_date = date(2026, 11, 20)
    comp.end_date = date(2026, 12, 13)
    comp.save()

    # Create 8 teams
    teams = []
    for i in range(8):
        t, _ = Team.objects.get_or_create(short_name=f"T{i+1}", defaults={'name': f"Team {i+1}"})
        teams.append(t)
        if not comp.teams.filter(id=t.id).exists():
            comp.teams.add(t)

    config = {
        'tournament_format': TournamentFormat.SINGLE_ELIMINATION,
        'tournament_type': 'single_elimination',
        'knockout_legs': 'single',
        'start_date': '2026-11-20',
        'end_date': '2026-12-13',
        'matches_per_day': 2,
        'daily_kickoff_times': ['15:00', '17:30'],
        'preferred_days': ['Sunday'],
        'venues': ['Central Stadium', 'Metropolis Arena', 'Riverside Sports Complex', 'Emirates Field']
    }

    res = generate_smart_fixtures(comp, config)
    assert res['success'], f"Error: {res.get('errors')}"
    matches = res['matches']

    print(f"\nTotal matches generated: {len(matches)}")
    date_counts = Counter(m['match_date'] for m in matches)
    for d, count in sorted(date_counts.items()):
        print(f"Date {d}: {count} matches")
        for m in matches:
            if m['match_date'] == d:
                print(f"   [{m['round_name']}] {m['kickoff_time']} | {m['home_team_name']} vs {m['away_team_name']} @ {m['venue']}")

    for d, count in date_counts.items():
        assert count <= 2, f"FAILED: Date {d} has {count} matches (max expected 2)"

    print("\nSUCCESS: All days have at most 2 matches as requested by user!")

if __name__ == '__main__':
    test_user_scenario()
