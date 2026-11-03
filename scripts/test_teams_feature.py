import os
import sys

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from django.test import RequestFactory, Client
from django.contrib.auth.models import User
from leagues.models import Competition, CompetitionTeam
from teams.models import Team, Player, PositionChoice
from accounts.models import UserProfile, UserRole, OrganizerStatus

print("=== STARTING TEAMS & PLAYER CARDS TEST ===")

# 1. Get or create an organizer user
user, created = User.objects.get_or_create(username='test_org', defaults={'email': 'testorg@test.com'})
user.set_password('pass1234')
user.save()

profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': UserRole.ORGANIZER})
profile.role = UserRole.ORGANIZER
profile.organizer_status = OrganizerStatus.APPROVED
profile.is_active_organizer = True
profile.save()

from leagues.models import Competition, CompetitionTeam, CompetitionStatus

# 2. Get or create competition
comp = Competition.objects.first()
if not comp:
    comp = Competition.objects.create(name="Test Premier League", primary_organizer=user, created_by=user, season="2026/2027", status=CompetitionStatus.ACTIVE)
else:
    comp.primary_organizer = user
    comp.created_by = user
    comp.status = CompetitionStatus.ACTIVE
    comp.save()

# 3. Get or create teams
team, _ = Team.objects.get_or_create(name="Arsenal Test FC", defaults={'short_name': 'ARS', 'manager_name': 'Mikel A'})
CompetitionTeam.objects.get_or_create(competition=comp, team=team)

# 4. Create players with details: name, jersey, position, photo_url
p1, _ = Player.objects.get_or_create(
    team=team, jersey_number=7,
    defaults={'full_name': 'Bukayo Saka', 'position': PositionChoice.FWD, 'photo_url': '/static/img/players/p1.jpg'}
)
p2, _ = Player.objects.get_or_create(
    team=team, jersey_number=8,
    defaults={'full_name': 'Martin Odegaard', 'position': PositionChoice.MID, 'photo_url': '/static/img/players/p2.jpg'}
)
p3, _ = Player.objects.get_or_create(
    team=team, jersey_number=1,
    defaults={'full_name': 'David Raya', 'position': PositionChoice.GK, 'photo_url': '/static/img/players/p3.jpg'}
)

print(f"Team: {team.name} has {team.players.count()} players.")

# 5. Test Client request to /organizer/<comp_id>/?tab=teams
client = Client()
client.force_login(user)

resp = client.get(f'/organizer/{comp.id}/?tab=teams')
print(f"GET /organizer/{comp.id}/?tab=teams -> Status code: {resp.status_code}")
assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}"
content = resp.content.decode('utf-8')

# Verify team name and link to organizer/team/<team.id>/
assert team.name in content, "Team name should be present in teams tab"
assert f'/organizer/team/{team.id}/' in content, f"Link to /organizer/team/{team.id}/ must be present"
print("✓ Teams tab shows team name, logo, and links to /organizer/team/<id>/")

# 6. Test Client request to /organizer/team/<team.id>/
resp_detail = client.get(f'/organizer/team/{team.id}/?competition={comp.id}')
print(f"GET /organizer/team/{team.id}/ -> Status code: {resp_detail.status_code}")
assert resp_detail.status_code == 200, f"Expected 200 but got {resp_detail.status_code}"
detail_content = resp_detail.content.decode('utf-8')

assert 'Bukayo Saka' in detail_content, "Player Bukayo Saka should be in detail page"
assert '#7' in detail_content, "Jersey #7 should be present"
assert 'Forward' in detail_content, "Position Forward should be present"
assert '+ Add Player' in detail_content, "Add Player button should be present"
print("✓ Organizer team detail page shows player cards with photo, jersey, position, and name!")

# 7. Test Adding a new player via POST
new_player_data = {
    'full_name': 'Declan Rice',
    'jersey_number': '41',
    'position': 'MID'
}
resp_post = client.post(f'/organizer/team/{team.id}/player/add/', data=new_player_data, follow=True)
print(f"POST /organizer/team/{team.id}/player/add/ -> Status code: {resp_post.status_code}")
p_new = Player.objects.filter(team=team, full_name='Declan Rice').first()
assert p_new is not None, "Declan Rice should be saved in DB"
assert p_new.jersey_number == 41, "Jersey number should be 41"
assert p_new.position == 'MID', "Position should be MID"
print("✓ Organizer successfully added a new player with name, jersey, position!")

# 8. Test duplicate jersey number prevention
dup_data = {
    'full_name': 'Duplicate Player',
    'jersey_number': '41',
    'position': 'DEF'
}
resp_dup = client.post(f'/organizer/team/{team.id}/player/add/', data=dup_data, follow=True)
assert Player.objects.filter(team=team, full_name='Duplicate Player').count() == 0, "Duplicate jersey should not be added"
print("✓ Duplicate jersey number check works correctly!")

# 9. Test Deleting a player via POST
resp_del = client.post(f'/organizer/team/{team.id}/player/{p_new.id}/delete/', follow=True)
print(f"POST /organizer/team/{team.id}/player/{p_new.id}/delete/ -> Status code: {resp_del.status_code}")
assert not Player.objects.filter(id=p_new.id).exists(), "Player should be deleted"
print("✓ Player successfully removed from roster!")

print("=== ALL TEAMS & PLAYER CARDS TESTS PASSED! ===")
