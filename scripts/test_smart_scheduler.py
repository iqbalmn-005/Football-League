import sys, os
from datetime import date, timedelta, time

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from teams.models import Team
from leagues.models import Competition, TournamentFormat
from fixtures.services import generate_smart_fixtures, commit_generated_fixtures

comp = Competition.objects.first()
teams = list(Team.objects.all()[:8])
print(f"Testing scheduler with competition: {comp.name}, {len(teams)} teams.")

# Test 1: Round Robin (Double)
cfg1 = {
    'tournament_format': TournamentFormat.ROUND_ROBIN,
    'selected_team_ids': [t.id for t in teams[:4]],
    'round_robin_type': 'double',
    'start_date': date(2026, 11, 14),
    'preferred_days': ['Saturday', 'Sunday'],
    'kickoff_times': ['14:00', '16:30', '19:00'],
    'max_matches_per_day': 2,
    'min_rest_days': 3,
    'prevent_same_day': True,
    'fixed_home_grounds': True,
}
res1 = generate_smart_fixtures(comp, cfg1)
assert res1['success'], f"Round robin failed: {res1.get('errors')}"
print(f"✓ Round Robin Generated {len(res1['matches'])} matches over {res1['summary']['total_rounds']} matchweeks.")
for m in res1['matches'][:4]:
    print(f"  {m['round_name']} | {m['match_date']} {m['kickoff_time']} | {m['home_team_name']} vs {m['away_team_name']} @ {m['venue']}")

# Test 2: Group Stage + Knockout
cfg2 = {
    'tournament_format': TournamentFormat.GROUP_KNOCKOUT,
    'selected_team_ids': [t.id for t in teams[:6]],
    'num_groups': 2,
    'group_allocation': 'automatic',
    'round_robin_type': 'single',
    'start_date': date(2026, 11, 14),
    'preferred_days': ['Saturday'],
    'kickoff_times': ['15:00', '18:00'],
}
res2 = generate_smart_fixtures(comp, cfg2)
assert res2['success'], f"Group knockout failed: {res2.get('errors')}"
print(f"✓ Group + Knockout Generated {len(res2['matches'])} matches. Groups: {list(res2['groups'].keys())}")
for m in res2['matches'][:4]:
    print(f"  {m['round_name']} ({m['group_name']}) | {m['match_date']} {m['kickoff_time']} | {m['home_team_name']} vs {m['away_team_name']}")

# Test 3: Knockout
cfg3 = {
    'tournament_format': TournamentFormat.SINGLE_ELIMINATION,
    'selected_team_ids': [t.id for t in teams[:4]],
    'start_date': date(2026, 11, 21),
    'preferred_days': ['Saturday'],
    'kickoff_times': ['16:00'],
}
res3 = generate_smart_fixtures(comp, cfg3)
assert res3['success'], f"Knockout failed: {res3.get('errors')}"
print(f"✓ Knockout Generated {len(res3['matches'])} bracket matches.")
for m in res3['matches']:
    print(f"  {m['round_name']} | {m['match_date']} {m['kickoff_time']} | {m['home_team_name']} vs {m['away_team_name']}")

print("ALL SCHEDULER ENGINE TESTS PASSED!")
