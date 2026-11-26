import os
import sys
import django
from datetime import date, time, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from django.contrib.auth.models import User
from django.test import Client
from accounts.models import UserProfile, UserRole, OrganizerStatus
from leagues.models import Competition, CompetitionStatus
from teams.models import Team
from matches.models import Match, MatchStatus


def run_tests():
    print("=== STARTING DAY-WISE FIXTURE POSTER TESTS ===")

    # Create test organizer 1 (owner), organizer 2 (unauthorized), and regular user
    org1, _ = User.objects.get_or_create(username='poster_test_org1', defaults={'email': 'org1@test.local'})
    org1.set_password('pass1234')
    org1.save()
    UserProfile.objects.update_or_create(
        user=org1,
        defaults={'role': UserRole.ORGANIZER, 'organizer_status': OrganizerStatus.APPROVED}
    )

    org2, _ = User.objects.get_or_create(username='poster_test_org2', defaults={'email': 'org2@test.local'})
    org2.set_password('pass1234')
    org2.save()
    UserProfile.objects.update_or_create(
        user=org2,
        defaults={'role': UserRole.ORGANIZER, 'organizer_status': OrganizerStatus.APPROVED}
    )

    fan, _ = User.objects.get_or_create(username='poster_test_fan', defaults={'email': 'fan@test.local'})
    fan.set_password('pass1234')
    fan.save()
    UserProfile.objects.update_or_create(
        user=fan,
        defaults={'role': UserRole.VIEWER}
    )

    comp = Competition.objects.create(
        name='London Sunday Poster Test League',
        season='2026/2027',
        status=CompetitionStatus.ACTIVE,
        primary_organizer=org1,
        created_by=org1,
    )

    t1, _ = Team.objects.get_or_create(name='Rovers Athletic Poster FC')
    t2, _ = Team.objects.get_or_create(name='Strikers United Very Long Club Name FC')
    t3, _ = Team.objects.get_or_create(name='Galaxy Wanderers Poster FC')
    t4, _ = Team.objects.get_or_create(name='Phoenix Legends Poster FC')
    comp.teams.add(t1, t2, t3, t4)

    d1 = date(2026, 12, 21)
    d2 = date(2026, 12, 22)

    # Create matches on d1 with out-of-order insertion and mixed matchweeks
    m_late = Match.objects.create(
        competition=comp,
        home_team=t3,
        away_team=t4,
        match_date=d1,
        kickoff_time=time(16, 30),
        tournament_round='Matchweek 2',
        venue='Hidden Stadium Should Not Appear',
        status=MatchStatus.SCHEDULED,
    )
    m_early = Match.objects.create(
        competition=comp,
        home_team=t1,
        away_team=t2,
        match_date=d1,
        kickoff_time=time(10, 0),
        tournament_round='Matchweek 1',
        venue='Another Hidden Venue',
        status=MatchStatus.SCHEDULED,
    )
    m_day2 = Match.objects.create(
        competition=comp,
        home_team=t1,
        away_team=t3,
        match_date=d2,
        kickoff_time=time(14, 0),
        tournament_round='Matchweek 2',
        status=MatchStatus.SCHEDULED,
    )

    try:
        client = Client()

        # 1. Unauthenticated -> 401
        r_unauth = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date={d1.isoformat()}')
        assert r_unauth.status_code == 401, f"Expected 401, got {r_unauth.status_code}"
        print("✓ Unauthenticated request rejected with 401")

        # 2. Fan user -> 403
        client.force_login(fan)
        r_fan = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date={d1.isoformat()}')
        assert r_fan.status_code == 403, f"Expected 403 for fan, got {r_fan.status_code}"
        print("✓ Non-organizer user rejected with 403")

        # 3. Unauthorized organizer -> 403
        client.force_login(org2)
        r_other = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date={d1.isoformat()}')
        assert r_other.status_code == 403, f"Expected 403 for other organizer, got {r_other.status_code}"
        print("✓ Unauthorized organizer rejected with 403")

        # 4. Authorized organizer checks
        client.force_login(org1)

        # Missing/invalid date -> 400
        r_bad_date = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date=21-12-2026')
        assert r_bad_date.status_code == 400, f"Expected 400 for invalid date, got {r_bad_date.status_code}"
        print("✓ Invalid date rejected with 400")

        # Non-existent league -> 404
        r_no_league = client.get(f'/api/leagues/9999999/fixtures/poster/?date={d1.isoformat()}')
        assert r_no_league.status_code == 404, f"Expected 404 for missing league, got {r_no_league.status_code}"
        print("✓ Missing league rejected with 404")

        # Date with no fixtures -> 404
        r_empty = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date=2026-12-30')
        assert r_empty.status_code == 404, f"Expected 404 for empty date, got {r_empty.status_code}"
        print("✓ Empty date rejected with 404")

        # Valid Day 1 request
        r_d1 = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date={d1.isoformat()}')
        assert r_d1.status_code == 200, f"Expected 200, got {r_d1.status_code}: {r_d1.content}"
        data1 = r_d1.json()
        assert data1['success'] is True
        assert data1['day_number'] == 1
        assert data1['league']['name'] == comp.name
        assert data1['formatted_date'] == '21 DEC 2026'
        assert len(data1['matches']) == 2
        # Sorted ascending by kickoff_time
        assert data1['matches'][0]['id'] == m_early.id
        assert data1['matches'][0]['kickoff_time'] == '10:00 AM'
        assert data1['matches'][0]['tournament_round'] == 'Matchweek 1'
        assert data1['matches'][1]['id'] == m_late.id
        assert data1['matches'][1]['kickoff_time'] == '04:30 PM'
        assert data1['matches'][1]['tournament_round'] == 'Matchweek 2'
        assert 'venue' not in data1['matches'][0]
        assert 'total_matches' not in data1
        print("✓ Day 1 poster API returned sorted matches, mixed matchweeks, and excluded venue/count")

        # Valid Day 2 request
        r_d2 = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date={d2.isoformat()}')
        assert r_d2.status_code == 200
        assert r_d2.json()['day_number'] == 2
        print("✓ Day 2 poster API returned day_number=2")

        # Organizer dashboard HTML check
        r_dash = client.get(f'/organizer/{comp.id}/?tab=fixtures')
        assert r_dash.status_code == 200
        html = r_dash.content.decode('utf-8')
        assert 'DAY 1' in html
        assert 'DAY 2' in html
        assert '21 December 2026' in html
        assert '22 December 2026' in html
        assert f'downloadDayPoster({comp.id}, \'{d1.isoformat()}\', this)' in html
        print("✓ Organizer Fixtures page renders day-wise grouped schedule with inline Download Poster buttons")

        # Republish / update kickoff time -> fresh data returned
        m_early.kickoff_time = time(11, 15)
        m_early.save(update_fields=['kickoff_time'])
        r_d1_updated = client.get(f'/api/leagues/{comp.id}/fixtures/poster/?date={d1.isoformat()}')
        assert r_d1_updated.json()['matches'][0]['kickoff_time'] == '11:15 AM'
        assert r_d1_updated['Cache-Control'] == 'no-store'
        print("✓ Updated fixture reflects immediately with Cache-Control: no-store")

        print("=== ALL DAY-WISE FIXTURE POSTER TESTS PASSED! ===")
    finally:
        comp.delete()
        org1.delete()
        org2.delete()
        fan.delete()


if __name__ == '__main__':
    run_tests()
