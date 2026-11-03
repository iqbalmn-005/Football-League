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
from matches.models import Match

print("=== STARTING STREAMLINED FIXTURE GENERATION TEST ===")

# 1. Setup user & competition
user, _ = User.objects.get_or_create(username='test_org', defaults={'email': 'testorg@test.com'})
profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': UserRole.ORGANIZER})
profile.role = UserRole.ORGANIZER
profile.organizer_status = OrganizerStatus.APPROVED
profile.is_active_organizer = True
profile.save()

comp = Competition.objects.filter(id=5).first() or Competition.objects.first()
comp.primary_organizer = user
comp.status = CompetitionStatus.ACTIVE
comp.save()

# Ensure 4 teams in competition
all_teams = list(Team.objects.all()[:4])
for t in all_teams:
    CompetitionTeam.objects.get_or_create(competition=comp, team=t)

client = Client()
client.force_login(user)

# 2. Test GET fixture_generator_page
url_gen = f"/organizer/{comp.id}/fixture-generator/"
resp_page = client.get(url_gen)
print(f"GET {url_gen} -> Status: {resp_page.status_code}")
assert resp_page.status_code == 200, f"Expected 200, got {resp_page.status_code}"
content = resp_page.content.decode('utf-8')

# Verify removed sections
assert "Blackout Dates" not in content, "Blackout dates must be removed"
assert "Official Match Duration" not in content, "Match duration must be removed"
assert "selected_teams" not in content, "Team selection checkboxes must be removed"
assert "Automatically Including All" not in content, "Club listing card must be removed"
assert "Select Available Venues / Pitches" not in content, "Venues selection must be removed"

# Verify new simplified fields
assert "How Many Matches in a Day?" in content, "Matches in a day must be present"
assert "Daily Kickoff Time Slots" in content, "Daily kickoff time slots must be present"
assert "Fixture End Date" in content, "Fixture End Date must be present"
print("✓ Verified: Venues selector, club listing, team checkboxes, match duration, and blackout exclusions removed!")
print("✓ Verified: End date, daily match slots, and equal group allocation present!")

# 3. Test POST api_generate_fixture_preview with custom matches per day and slot times
slot_times = ["15:00", "17:30"]
payload_preview = {
    'tournament_format': 'ROUND_ROBIN',
    'round_robin_type': 'single',
    'start_date': (date.today() + timedelta(days=7)).isoformat(),
    'end_date': (date.today() + timedelta(days=90)).isoformat(),
    'preferred_days': ['Saturday', 'Sunday'],
    'matches_per_day': 2,
    'daily_kickoff_times': slot_times,
    'venues': []
}

resp_api = client.post(
    f"/organizer/{comp.id}/api/generate-preview/",
    data=json.dumps(payload_preview),
    content_type="application/json"
)
print(f"POST api/generate-preview/ -> Status: {resp_api.status_code}")
assert resp_api.status_code == 200
preview_data = resp_api.json()
assert preview_data['success'] is True, f"Preview failed: {preview_data.get('errors')}"
assert len(preview_data['matches']) > 0, "Matches must be generated"

# Verify kickoff times match user slot times
match_times = {m['kickoff_time'] for m in preview_data['matches']}
print(f"Generated match kickoff times: {match_times}")
for mt in match_times:
    assert mt in slot_times, f"Kickoff time {mt} should match configured slot times {slot_times}"
print(f"✓ All matches scheduled precisely according to daily slot times {slot_times}!")

# Verify end_date is strictly never crossed
for m in preview_data['matches']:
    assert m['match_date'] <= payload_preview['end_date'], f"Match date {m['match_date']} crossed end_date {payload_preview['end_date']}"
print(f"✓ All round robin matches strictly fall on or before end_date {payload_preview['end_date']}!")

# 3b. Test tight end_date constraint (e.g. 14 days window)
tight_start = date.today() + timedelta(days=7)
tight_end = tight_start + timedelta(days=14)
payload_tight = {
    'tournament_format': 'ROUND_ROBIN',
    'round_robin_type': 'single',
    'start_date': tight_start.isoformat(),
    'end_date': tight_end.isoformat(),
    'preferred_days': ['Saturday', 'Sunday'],
    'matches_per_day': 2,
    'daily_kickoff_times': slot_times,
    'venues': []
}
resp_tight = client.post(
    f"/organizer/{comp.id}/api/generate-preview/",
    data=json.dumps(payload_tight),
    content_type="application/json"
)
tight_data = resp_tight.json()
assert tight_data['success'] is True
for m in tight_data['matches']:
    assert m['match_date'] <= tight_end.isoformat(), f"Match {m['temp_id']} date {m['match_date']} crossed tight end date {tight_end.isoformat()}"
print(f"✓ Tight end_date constraint respected: 100% of matches completed on or before {tight_end.isoformat()}!")

# 4. Test Group Equal Division and Knockout according to Qualifiers Per Group with strict end_date
group_start = date.today() + timedelta(days=7)
group_end = group_start + timedelta(days=21)
payload_group = {
    'tournament_format': 'GROUP_KNOCKOUT',
    'num_groups': 2,
    'qualifiers_per_group': 2,
    'round_robin_type': 'single',
    'start_date': group_start.isoformat(),
    'end_date': group_end.isoformat(),
    'preferred_days': ['Saturday', 'Sunday'],
    'matches_per_day': 2,
    'daily_kickoff_times': ["16:00", "18:30"],
}
resp_grp = client.post(
    f"/organizer/{comp.id}/api/generate-preview/",
    data=json.dumps(payload_group),
    content_type="application/json"
)
grp_data = resp_grp.json()
assert grp_data['success'] is True
groups = grp_data['groups']
print(f"Group allocation (2 groups): Group A has {len(groups['Group A'])} teams, Group B has {len(groups['Group B'])} teams")
assert len(groups['Group A']) == len(groups['Group B']), "Teams must be divided equally between groups!"
print("✓ Teams divided equally between groups!")

for m in grp_data['matches']:
    assert m['match_date'] <= group_end.isoformat(), f"Group/KO Match {m['round_name']} on {m['match_date']} crossed end_date {group_end.isoformat()}"
print(f"✓ Group Stage + Knockout matches strictly conclude on or before end_date {group_end.isoformat()}!")

# Verify knockout fixtures match 2 qualifiers per group (4 qualifiers total -> 2 SFs + 1 Final)
grp_ko_matches = [m for m in grp_data['matches'] if m['is_knockout']]
sf_matches = [m for m in grp_ko_matches if m['round_name'] == 'Semi-Finals']
final_matches = [m for m in grp_ko_matches if m['round_name'] == 'Grand Championship Final']
assert len(sf_matches) == 2, f"Expected 2 Semi-Final matches, got {len(sf_matches)}"
assert len(final_matches) == 1, f"Expected 1 Final match, got {len(final_matches)}"
print("✓ Knockout fixtures accurately generated for 2 qualifiers/group: 2 Semi-Finals + 1 Final!")

# 4b. Test 1 Group with 2 qualifiers (total 2 -> straight to Grand Final)
payload_single_group = {
    'tournament_format': 'GROUP_KNOCKOUT',
    'num_groups': 1,
    'qualifiers_per_group': 2,
    'round_robin_type': 'single',
    'start_date': (date.today() + timedelta(days=7)).isoformat(),
    'preferred_days': ['Saturday'],
    'matches_per_day': 2,
    'daily_kickoff_times': ["16:00", "18:30"],
}
resp_single_grp = client.post(
    f"/organizer/{comp.id}/api/generate-preview/",
    data=json.dumps(payload_single_group),
    content_type="application/json"
)
single_grp_data = resp_single_grp.json()
assert single_grp_data['success'] is True
assert len(single_grp_data['groups']) == 1, "Must have exactly 1 group"
assert 'Group A' in single_grp_data['groups']
single_ko = [m for m in single_grp_data['matches'] if m['is_knockout']]
assert len(single_ko) == 1 and single_ko[0]['round_name'] == 'Grand Championship Final'
print(f"✓ 1 Group with 2 qualifiers: Correctly generated only Grand Championship Final!")

# 4c. Test 2 Groups with 1 qualifier each (total 2 -> straight to Grand Final 1A vs 1B)
payload_top1 = {
    'tournament_format': 'GROUP_KNOCKOUT',
    'num_groups': 2,
    'qualifiers_per_group': 1,
    'round_robin_type': 'single',
    'start_date': (date.today() + timedelta(days=7)).isoformat(),
    'preferred_days': ['Saturday'],
    'matches_per_day': 2,
    'daily_kickoff_times': ["16:00", "18:30"],
}
resp_top1 = client.post(
    f"/organizer/{comp.id}/api/generate-preview/",
    data=json.dumps(payload_top1),
    content_type="application/json"
)
top1_data = resp_top1.json()
assert top1_data['success'] is True
top1_ko = [m for m in top1_data['matches'] if m['is_knockout']]
assert len(top1_ko) == 1 and top1_ko[0]['round_name'] == 'Grand Championship Final'
assert '1st Group A' in top1_ko[0]['home_team_name']
assert '1st Group B' in top1_ko[0]['away_team_name']
print(f"✓ 2 Groups with Top 1 qualifier: Correctly generated 1A vs 1B Grand Championship Final!")

# 5. Test Publish
publish_payload = {
    'matches': preview_data['matches'],
    'groups': preview_data.get('groups', {})
}
resp_pub = client.post(
    f"/organizer/{comp.id}/api/publish-fixtures/",
    data=json.dumps(publish_payload),
    content_type="application/json"
)
print(f"POST api/publish-fixtures/ -> Status: {resp_pub.status_code}")
assert resp_pub.status_code == 200
assert resp_pub.json()['success'] is True

db_matches = Match.objects.filter(competition=comp, status='SCHEDULED')
print(f"✓ Successfully published {db_matches.count()} matches into database!")
print("=== ALL STREAMLINED FIXTURE GENERATOR TESTS PASSED! ===")
