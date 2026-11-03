from django.core.management.base import BaseCommand
from django.test import Client
from django.contrib.auth.models import User
from accounts.models import UserProfile, UserRole, OrganizerStatus, OrganizerApplication
from leagues.models import Competition
from teams.models import Team, Player
from matches.models import Match, MatchStatus
from standings.models import StandingEntry


class Command(BaseCommand):
    help = 'Executes end-to-end integration tests for all TOUCHLINE workflows'

    def handle(self, *args, **options):
        client = Client()
        self.stdout.write("=== STARTING TOUCHLINE DJANGO INTEGRATION TESTS ===")

        # Test 1: Landing Page
        res = client.get('/')
        assert res.status_code == 200, f"Landing page failed with {res.status_code}"
        assert b"TOUCHLINE" in res.content, "TOUCHLINE brand missing on landing page"
        self.stdout.write(self.style.SUCCESS("[OK] Test 1 Passed: Landing page renders dynamically."))

        # Test 2: Competition Viewer
        comp = Competition.objects.filter(is_published=True).first()
        if comp:
            res = client.get(f'/competition/{comp.id}/')
            assert res.status_code == 200, f"Competition viewer failed with {res.status_code}"
            self.stdout.write(self.style.SUCCESS("[OK] Test 2 Passed: Public competition viewer renders."))

        # Test 3: Team Profile Page
        team = Team.objects.first()
        if team:
            res = client.get(f'/team/{team.id}/')
            assert res.status_code == 200, f"Team profile failed with {res.status_code}"
            self.stdout.write(self.style.SUCCESS("[OK] Test 3 Passed: Team profile renders."))

        # Test 4: JSON APIs for Modals
        if comp:
            match_obj = comp.matches.first()
            if match_obj:
                res = client.get(f'/api/match/{match_obj.id}/')
                assert res.status_code == 200, "Match detail API failed"
                data = res.json()
                assert 'home_team' in data and 'away_team' in data, "Match detail payload invalid"

        player = Player.objects.first()
        if player:
            res = client.get(f'/api/player/{player.id}/')
            assert res.status_code == 200, "Player detail API failed"
            pdata = res.json()
            assert 'full_name' in pdata and 'jersey_number' in pdata, "Player detail payload invalid"
            self.stdout.write(self.style.SUCCESS("[OK] Test 4 Passed: Match & Player modal JSON APIs respond with complete data."))

        # Test 5: Authentication & RBAC
        res = client.get('/super-admin/')
        assert res.status_code == 302, "Super Admin route not protected"
        assert '/login/' in res.url, "Super Admin did not redirect to login"

        # Login as Super Admin
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            client.force_login(admin_user)
            res = client.get('/super-admin/')
            assert res.status_code == 200, "Super admin dashboard failed for logged-in admin"
            self.stdout.write(self.style.SUCCESS("[OK] Test 5 Passed: Role-based access control protects admin console."))

        self.stdout.write(self.style.SUCCESS("ALL DJANGO WORKFLOW TESTS PASSED SUCCESSFULLY!"))

