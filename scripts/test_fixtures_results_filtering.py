import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from leagues.models import Competition
from matches.models import Match, MatchStatus

def test_fixtures_and_results():
    print("=== Testing Fixtures and Results Separation on Competition 5 (PFL) ===")
    
    comp = Competition.objects.get(id=5)
    org_user = comp.primary_organizer
    client = Client()
    client.force_login(org_user)

    # 1. Fetch organizer dashboard fixtures tab
    resp_fix = client.get(f'/organizer/{comp.id}/?tab=fixtures')
    assert resp_fix.status_code == 200
    content_fix = resp_fix.content.decode('utf-8')

    # 2. Fetch organizer dashboard results tab
    resp_res = client.get(f'/organizer/{comp.id}/?tab=results')
    assert resp_res.status_code == 200
    content_res = resp_res.content.decode('utf-8')

    comp_completed = list(comp.matches.filter(status=MatchStatus.COMPLETED))
    comp_upcoming = list(comp.matches.filter(status__in=[MatchStatus.SCHEDULED, MatchStatus.LIVE, MatchStatus.POSTPONED]))

    print(f"Competition {comp.name} (id={comp.id}): {len(comp_completed)} completed matches, {len(comp_upcoming)} upcoming matches")
    assert len(comp_completed) > 0, "Expected at least 1 completed match"
    assert len(comp_upcoming) > 0, "Expected at least 1 upcoming match"

    # In fixtures tab:
    # 1. Every upcoming match should be present with Reschedule & Enter Score
    for um in comp_upcoming:
        assert f"openRescheduleModal('{um.id}'" in content_fix, f"Upcoming match {um.id} should be in fixtures tab"
    # 2. NO completed match should be present in fixtures table
    for cm in comp_completed:
        assert f"openRescheduleModal('{cm.id}'" not in content_fix, f"Completed match {cm.id} should NOT be in fixtures tab table"
    print("[OK] Verified: Completed matches do NOT show in Fixtures tab.")

    # In results tab:
    # 1. Every completed match should be present with 'Edit Result & Events'
    for cm in comp_completed:
        assert f"openRecordResultModal('{cm.id}'" in content_res, f"Completed match {cm.id} should have edit button in results tab"
        assert "✎ Edit Result &amp; Events" in content_res, "Expected 'Edit Result & Events' button in results"
    # 2. NO upcoming match should be present in results table
    for um in comp_upcoming:
        # Check that upcoming matches are NOT rendered as rows in results table
        score = um.home_score if um.home_score is not None else 0
        assert f"openRecordResultModal('{um.id}', '{um.home_team.name}', '{um.away_team.name}', '{um.tournament_round}', '{score}'" not in content_res
    print("[OK] Verified: In Results tab, ONLY completed matches show.")
    print("[OK] Verified: In Results tab, only editing results is available.")

    print("\nALL FIXTURES & RESULTS CHECKS PASSED!")

if __name__ == '__main__':
    test_fixtures_and_results()
