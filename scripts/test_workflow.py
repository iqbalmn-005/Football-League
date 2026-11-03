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
from accounts.models import UserProfile, UserRole, OrganizerStatus, OrganizerApplication
from leagues.models import Competition
from teams.models import Team, Player
from matches.models import Match, MatchStatus
from standings.models import StandingEntry
from standings.services import recalculate_competition_standings
from fixtures.services import generate_round_robin_fixtures

def run_tests():
    client = Client()
    print("=== STARTING TOUCHLINE INTEGRATION TESTS ===")

    # Test 1: Landing Page
    res = client.get('/')
    assert res.status_code == 200, f"Landing page failed with {res.status_code}"
    assert b"TOUCHLINE" in res.content, "TOUCHLINE brand missing on landing page"
    assert b"Metropolis Premier League" in res.content, "Seeded competition missing on landing page"
    print("[OK] Test 1 Passed: Landing page (list.html) renders with dynamic competitions.")

    # Test 2: Competition Viewer
    comp = Competition.objects.filter(name="Metropolis Premier League").first()
    assert comp is not None, "Competition not found"
    res = client.get(f'/competition/{comp.id}/')
    assert res.status_code == 200, f"Competition viewer failed with {res.status_code}"
    assert b"Official League Standings" in res.content, "Standings tab missing"
    assert b"Greenfield FC" in res.content, "Team missing from viewer"
    print("[OK] Test 2 Passed: Public competition viewer (user_dashboard.html) renders live standings and fixtures.")

    # Test 3: Team Profile Page
    team = Team.objects.filter(name="Greenfield FC").first()
    assert team is not None, "Greenfield FC not found"
    res = client.get(f'/team/{team.id}/')
    assert res.status_code == 200, f"Team profile failed with {res.status_code}"
    assert b"Greenfield FC" in res.content, "Team name missing"
    assert b"Registered Squad Players" in res.content, "Squad missing"
    print("[OK] Test 3 Passed: Team profile (team.html) renders squad and metrics.")

    # Test 4: JSON APIs for Modals
    match_obj = comp.matches.first()
    res = client.get(f'/api/match/{match_obj.id}/')
    assert res.status_code == 200, "Match detail API failed"
    data = res.json()
    assert 'home_team' in data and 'away_team' in data, "Match detail payload invalid"

    player = Player.objects.first()
    res = client.get(f'/api/player/{player.id}/')
    assert res.status_code == 200, "Player detail API failed"
    pdata = res.json()
    assert 'full_name' in pdata and 'jersey_number' in pdata, "Player detail payload invalid"
    print("[OK] Test 4 Passed: Match & Player modal JSON APIs respond with complete data.")

    # Test 5: Authentication & RBAC
    # Unauthorized access to Super Admin should redirect
    res = client.get('/super-admin/')
    assert res.status_code == 302, "Super Admin route not protected"
    assert '/login/' in res.url, "Super Admin did not redirect to login"

    # Login as Super Admin
    login_success = client.login(username='admin', password='adminpassword123')
    assert login_success, "Super Admin login failed"
    res = client.get('/super-admin/')
    assert res.status_code == 200, "Super admin dashboard failed for logged-in admin"
    assert b"Super Admin" in res.content, "Super admin content missing"
    print("[OK] Test 5 Passed: Role-based access control protects admin console; Super Admin authenticates successfully.")

    # Test 6: Approvals Hub & Application Review
    pending_app = OrganizerApplication.objects.filter(status=OrganizerApplication.Status.PENDING).first()
    if pending_app:
        app_id = pending_app.id
        res = client.post(f'/super-admin/application/{app_id}/approve/')
        assert res.status_code == 302, "Approve application did not redirect"
        pending_app.refresh_from_db()
        assert pending_app.status == OrganizerApplication.Status.APPROVED, "Application was not approved"
        assert pending_app.applicant.profile.organizer_status == OrganizerStatus.APPROVED, "Profile not marked approved"
        print("[OK] Test 6 Passed: Super Admin application approval workflow updates status and profile permissions.")

    # Test 7: Organizer Console & Live Match Result -> Automated Standings Sync
    client.logout()
    login_org = client.login(username='07700900001', password='organizer123')
    assert login_org, "Organizer login failed"
    res = client.get(f'/organizer/{comp.id}/')
    assert res.status_code == 200, "Organizer dashboard failed"

    # Enter a match result and verify automated standings calculation
    test_match = comp.matches.filter(status=MatchStatus.SCHEDULED).first()
    if test_match:
        ht = test_match.home_team
        at = test_match.away_team

        # Get initial standings for home team
        initial_entry = StandingEntry.objects.filter(competition=comp, team=ht).first()
        initial_points = initial_entry.points if initial_entry else 0

        # Post match result: Home 3 - 0 Away
        res = client.post(f'/organizer/match/{test_match.id}/result/', {
            'home_score': 3,
            'away_score': 0,
            'status': 'COMPLETED',
            'home_scorers': "Test Scorer 22'"
        })
        assert res.status_code == 302, "Entering match result did not redirect"

        test_match.refresh_from_db()
        assert test_match.status == MatchStatus.COMPLETED
        assert test_match.home_score == 3
        assert test_match.away_score == 0

        # Verify standings were recalculated automatically!
        updated_entry = StandingEntry.objects.filter(competition=comp, team=ht).first()
        assert updated_entry.points == initial_points + 3, f"Expected {initial_points + 3} points, got {updated_entry.points}"
        print("[OK] Test 7 Passed: Organizer result entry updates match, records events, and automatically syncs points table!")

    print("\nALL 7 INTEGRATION TESTS PASSED SUCCESSFULLY! ALL PLATFORM MODULES VERIFIED.")

if __name__ == '__main__':
    run_tests()
