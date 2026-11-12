import sys, os
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from accounts.models import UserProfile, UserRole, OrganizerStatus
from leagues.models import Competition, CompetitionStatus, TournamentFormat, CompetitionTeam
from teams.models import Team
from matches.models import Match, MatchStatus
from fixtures.services import (
    generate_smart_fixtures,
    commit_generated_fixtures,
    advance_knockout_bracket
)

print("=== STARTING PAGE-MCINTYRE PLAYOFF SYSTEM TESTS ===")

# 1. Verify TournamentFormat model choice
assert hasattr(TournamentFormat, 'PAGE_MCINTYRE'), "TournamentFormat.PAGE_MCINTYRE must exist"
assert TournamentFormat.PAGE_MCINTYRE == 'PAGE_MCINTYRE'
print("✓ Verified: TournamentFormat.PAGE_MCINTYRE is defined.")

# 2. Setup user, competition, and 4 teams
user, _ = User.objects.get_or_create(username='test_pm_org', defaults={'email': 'pmorg@test.com'})
profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': UserRole.ORGANIZER})
profile.role = UserRole.ORGANIZER
profile.organizer_status = OrganizerStatus.APPROVED
profile.is_active_organizer = True
profile.save()

comp, _ = Competition.objects.get_or_create(
    name="Test Page McIntyre League 2026",
    defaults={
        'tournament_format': TournamentFormat.PAGE_MCINTYRE,
        'status': CompetitionStatus.ACTIVE,
        'primary_organizer': user
    }
)
comp.primary_organizer = user
comp.status = CompetitionStatus.ACTIVE
comp.matches.all().delete()
comp.save()

all_teams = list(Team.objects.all()[:4])
while len(all_teams) < 4:
    idx = len(all_teams) + 1
    t = Team.objects.create(name=f"Playoff Team {idx}", short_name=f"PT{idx}")
    all_teams.append(t)

for idx, t in enumerate(all_teams[:4], 1):
    ct, _ = CompetitionTeam.objects.get_or_create(competition=comp, team=t)
    ct.seed = idx
    ct.save()

# 3. Test standalone Page-McIntyre fixture generation
config_pm = {
    'tournament_format': 'PAGE_MCINTYRE',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=35),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_pm = generate_smart_fixtures(comp, config_pm)
assert res_pm['success'], f"Expected success, got errors: {res_pm.get('errors')}"
matches_pm = res_pm['matches']
assert len(matches_pm) == 4, f"Expected exactly 4 matches for Page-McIntyre, got {len(matches_pm)}"

round_names = [m['round_name'] for m in matches_pm]
assert "Qualifying Final (1st vs 2nd)" in round_names[0], f"Match 1 must be Qualifying Final: {round_names[0]}"
assert "Elimination Final (3rd vs 4th)" in round_names[1], f"Match 2 must be Elimination Final: {round_names[1]}"
assert "Preliminary Final" in round_names[2], f"Match 3 must be Preliminary Final: {round_names[2]}"
assert "Grand Final" in round_names[3], f"Match 4 must be Grand Final: {round_names[3]}"
print("✓ Verified: Page-McIntyre generates exactly 4 matches in correct order:")
for m in matches_pm:
    print(f"   - {m['round_name']}: {m['home_team_name']} vs {m['away_team_name']} on {m['match_date']}")

# 4. Test committing fixtures to DB
created_matches = commit_generated_fixtures(comp, matches_pm, tournament_format='PAGE_MCINTYRE')
comp.refresh_from_db()
assert comp.tournament_format == TournamentFormat.PAGE_MCINTYRE
assert comp.matches.count() == 4
print(f"✓ Verified: Committed {len(created_matches)} matches to DB for competition '{comp.name}'")

# 5. Test automatic bracket advancement
# Match 1: Qualifying Final (Team 1 vs Team 2)
# Team 1 wins 2-1 against Team 2
qf_match = comp.matches.filter(tournament_round__icontains="Qualifying Final").first()
ef_match = comp.matches.filter(tournament_round__icontains="Elimination Final").first()
pf_match = comp.matches.filter(tournament_round__icontains="Preliminary Final").first()
gf_match = comp.matches.filter(tournament_round__icontains="Grand Final").first()

t1, t2, t3, t4 = all_teams[0], all_teams[1], all_teams[2], all_teams[3]

qf_match.home_score = 2
qf_match.away_score = 1
qf_match.status = MatchStatus.COMPLETED
qf_match.save()
advance_knockout_bracket(comp)

pf_match.refresh_from_db()
gf_match.refresh_from_db()
assert pf_match.home_team_id == t2.id, f"Preliminary Final home team should be loser of QF (Team 2: {t2.name}), got {pf_match.home_team.name}"
assert gf_match.home_team_id == t1.id, f"Grand Final home team should be winner of QF (Team 1: {t1.name}), got {gf_match.home_team.name}"
print("✓ Verified: Qualifying Final result correctly advanced Winner to Grand Final and Loser to Preliminary Final!")

# Match 2: Elimination Final (Team 3 vs Team 4)
# Team 4 wins 3-1 against Team 3
ef_match.home_score = 1
ef_match.away_score = 3
ef_match.status = MatchStatus.COMPLETED
ef_match.save()
advance_knockout_bracket(comp)

pf_match.refresh_from_db()
assert pf_match.away_team_id == t4.id, f"Preliminary Final away team should be winner of EF (Team 4: {t4.name}), got {pf_match.away_team.name}"
print("✓ Verified: Elimination Final result correctly advanced Winner to Preliminary Final!")

# Match 3: Preliminary Final (Team 2 vs Team 4)
# Team 2 wins 1-0 against Team 4
pf_match.home_score = 1
pf_match.away_score = 0
pf_match.status = MatchStatus.COMPLETED
pf_match.save()
advance_knockout_bracket(comp)

gf_match.refresh_from_db()
assert gf_match.away_team_id == t2.id, f"Grand Final away team should be winner of Preliminary Final (Team 2: {t2.name}), got {gf_match.away_team.name}"
print("✓ Verified: Preliminary Final result correctly advanced Winner to Grand Final!")

# Match 4: Grand Final (Team 1 vs Team 2)
# Team 1 wins 3-2 against Team 2 -> Champion is Team 1!
gf_match.home_score = 3
gf_match.away_score = 2
gf_match.status = MatchStatus.COMPLETED
gf_match.save()

comp.refresh_from_db()
assert comp.is_completed, "Competition should be marked completed when all matches finished"
assert comp.winner.id == t1.id, f"Champion should be Grand Final winner (Team 1: {t1.name}), got {comp.winner.name}"
print(f"✓ Verified: Grand Final concluded! Competition is completed with Champion: {comp.winner.name}")

# 6. Test League + Tournament with Page-McIntyre playoff choice
config_league_pm = {
    'tournament_format': 'LEAGUE_KNOCKOUT',
    'tournament_type': 'page_mcintyre',
    'num_groups': 1,
    'qualifiers_per_group': 4,
    'round_robin_type': 'single',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=60),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_league_pm = generate_smart_fixtures(comp, config_league_pm)
assert res_league_pm['success'], f"Expected success for league+pm, got {res_league_pm.get('errors')}"
l_matches = res_league_pm['matches']
# 4 teams in single round-robin = 6 league matches + 4 Page-McIntyre playoff matches = 10 matches total
assert len(l_matches) == 10, f"Expected 10 matches (6 league + 4 playoff), got {len(l_matches)}"
l_rounds = [m['round_name'] for m in l_matches]
assert any("Qualifying Final" in r for r in l_rounds)
assert any("Elimination Final" in r for r in l_rounds)
assert any("Preliminary Final" in r for r in l_rounds)
assert any("Grand Final" in r for r in l_rounds)
print(f"✓ Verified: League + Tournament (Page-McIntyre) generated {len(l_matches)} matches (6 league + 4 Page-McIntyre playoff matches)!")

# 7. Test League + Tournament with Single-Elimination (Single Leg)
config_league_se_single = {
    'tournament_format': 'LEAGUE_KNOCKOUT',
    'tournament_type': 'single_elimination',
    'knockout_legs': 'single',
    'num_groups': 1,
    'qualifiers_per_group': 4,
    'round_robin_type': 'single',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=60),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_league_se_single = generate_smart_fixtures(comp, config_league_se_single)
assert res_league_se_single['success']
# 6 league matches + 3 playoff matches (2 SF + 1 Final) = 9 matches total
assert len(res_league_se_single['matches']) == 9, f"Expected 9 matches, got {len(res_league_se_single['matches'])}"
print("✓ Verified: League + Tournament (Single Elimination Single Leg) generated 9 matches (6 league + 3 playoff)!")

# 8. Test League + Tournament with Single-Elimination (Double Leg)
config_league_se_double = {
    'tournament_format': 'LEAGUE_KNOCKOUT',
    'tournament_type': 'single_elimination',
    'knockout_legs': 'double',
    'num_groups': 1,
    'qualifiers_per_group': 4,
    'round_robin_type': 'single',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=60),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_league_se_double = generate_smart_fixtures(comp, config_league_se_double)
assert res_league_se_double['success']
# 6 league matches + 5 playoff matches (2 SF Leg 1 + 2 SF Leg 2 + 1 Final) = 11 matches total
assert len(res_league_se_double['matches']) == 11, f"Expected 11 matches, got {len(res_league_se_double['matches'])}"
se_rounds = [m['round_name'] for m in res_league_se_double['matches']]
assert any("Semi-Finals (Leg 1)" in r for r in se_rounds)
assert any("Semi-Finals (Leg 2)" in r for r in se_rounds)
assert any("Grand Championship Final" in r for r in se_rounds)
print("✓ Verified: League + Tournament (Single Elimination Double Leg) generated 11 matches (6 league + 4 SF legs + 1 Final)!")

# 9. Test Group Mode + Tournament with Page-McIntyre
config_group_pm = {
    'tournament_format': 'GROUP_KNOCKOUT',
    'tournament_type': 'page_mcintyre',
    'num_groups': 2,
    'qualifiers_per_group': 2,
    'round_robin_type': 'single',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=60),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_group_pm = generate_smart_fixtures(comp, config_group_pm)
assert res_group_pm['success']
# 4 teams in 2 groups of 2: 1 match per group = 2 group matches + 4 Page-McIntyre = 6 matches total
assert len(res_group_pm['matches']) == 6, f"Expected 6 matches, got {len(res_group_pm['matches'])}"
print("✓ Verified: Group Mode + Tournament (Page-McIntyre) generated 6 matches (2 group + 4 Page-McIntyre)!")

# 10. Test Group Mode + Tournament with Double Leg Single-Elimination
config_group_double = {
    'tournament_format': 'GROUP_KNOCKOUT',
    'tournament_type': 'single_elimination',
    'knockout_legs': 'double',
    'num_groups': 2,
    'qualifiers_per_group': 2,
    'round_robin_type': 'single',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=60),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_group_double = generate_smart_fixtures(comp, config_group_double)
assert res_group_double['success']
# 2 group matches + 5 knockout matches (2 SF Leg 1 + 2 SF Leg 2 + 1 Final) = 7 matches total
assert len(res_group_double['matches']) == 7, f"Expected 7 matches, got {len(res_group_double['matches'])}"
print("✓ Verified: Group Mode + Tournament (Double Leg Knockout) generated 7 matches (2 group + 5 knockout)!")

# 11. Test Knockout format with Page-McIntyre choice
config_ko_pm = {
    'tournament_format': 'KNOCKOUT',
    'tournament_type': 'page_mcintyre',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=30),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_ko_pm = generate_smart_fixtures(comp, config_ko_pm)
assert res_ko_pm['success']
assert len(res_ko_pm['matches']) == 4
print("✓ Verified: Knockout format with tournament_type='page_mcintyre' generates 4 Page-McIntyre matches!")

# 12. Test Knockout format with Single-Elimination Single Leg
config_ko_single = {
    'tournament_format': 'KNOCKOUT',
    'tournament_type': 'single_elimination',
    'knockout_legs': 'single',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=30),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_ko_single = generate_smart_fixtures(comp, config_ko_single)
assert res_ko_single['success']
# 4 teams in pure single elimination = 2 SF + 1 Final = 3 matches
assert len(res_ko_single['matches']) == 3, f"Expected 3 matches, got {len(res_ko_single['matches'])}"
print("✓ Verified: Knockout format with single leg generates 3 matches (2 SF + 1 Final)!")

# 13. Test Knockout format with Single-Elimination Double Leg
config_ko_double = {
    'tournament_format': 'KNOCKOUT',
    'tournament_type': 'single_elimination',
    'knockout_legs': 'double',
    'start_date': date.today() + timedelta(days=7),
    'end_date': date.today() + timedelta(days=30),
    'matches_per_day': 2,
    'daily_kickoff_times': ["15:00", "17:30"],
    'preferred_days': ['Saturday', 'Sunday'],
}
res_ko_double = generate_smart_fixtures(comp, config_ko_double)
assert res_ko_double['success']
# 4 teams in double leg elimination = 2 SF Leg 1 + 2 SF Leg 2 + 1 Final = 5 matches
assert len(res_ko_double['matches']) == 5, f"Expected 5 matches, got {len(res_ko_double['matches'])}"
print("✓ Verified: Knockout format with double leg generates 5 matches (4 SF legs + 1 Final)!")

print("=== ALL PAGE-MCINTYRE & TOURNAMENT TYPE TESTS PASSED SUCCESSFULLY! ===")
