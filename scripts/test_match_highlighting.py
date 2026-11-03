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

def test_match_posters():
    print("=== Testing Match Fixture Posters (Brand Color #B4F56B) ===")
    
    # 1. Check organizer_index.html
    with open(os.path.join(BASE_DIR, 'front', 'organizer_index.html'), 'r', encoding='utf-8') as f:
        html_org = f.read()

    assert "match-fixture-poster" in html_org, "match-fixture-poster not found in organizer_index.html"
    assert "poster-title" in html_org, "poster-title not found in organizer_index.html"
    assert "poster-matchup" in html_org, "poster-matchup not found in organizer_index.html"
    assert "poster-crest-wrap" in html_org, "poster-crest-wrap not found in organizer_index.html"
    assert "poster-info-pill" in html_org, "poster-info-pill not found in organizer_index.html"
    assert "poster-btn-primary" in html_org, "poster-btn-primary not found in organizer_index.html"
    assert "badge-next-match" in html_org, "badge-next-match not found in organizer_index.html"
    assert "badge-last-match" in html_org, "badge-last-match not found in organizer_index.html"
    assert "#B4F56B" in html_org, "Brand color #B4F56B not found in organizer_index.html"
    assert "#dc2626" not in html_org, "Old red #dc2626 found in organizer_index.html"
    assert "#0284c7" not in html_org, "Old blue #0284c7 found in organizer_index.html"
    print("[OK] organizer_index.html verified with fixture poster & #B4F56B brand accent.")

    # 2. Check user_dashboard.html
    with open(os.path.join(BASE_DIR, 'front', 'user_dashboard.html'), 'r', encoding='utf-8') as f:
        html_user = f.read()

    assert "match-fixture-poster" in html_user, "match-fixture-poster not found in user_dashboard.html"
    assert "poster-title" in html_user, "poster-title not found in user_dashboard.html"
    assert "poster-matchup" in html_user, "poster-matchup not found in user_dashboard.html"
    assert "poster-info-pill" in html_user, "poster-info-pill not found in user_dashboard.html"
    assert "#B4F56B" in html_user, "Brand color #B4F56B not found in user_dashboard.html"
    assert "#dc2626" not in html_user, "Old red #dc2626 found in user_dashboard.html"
    assert "#0284c7" not in html_user, "Old blue #0284c7 found in user_dashboard.html"
    print("[OK] user_dashboard.html verified with fixture poster & #B4F56B brand accent.")

    # 3. Check team.html
    with open(os.path.join(BASE_DIR, 'front', 'team.html'), 'r', encoding='utf-8') as f:
        html_team = f.read()

    assert "NEXT MATCH" in html_team, "NEXT MATCH not found in team.html"
    assert "LATEST RESULT" in html_team, "LATEST RESULT not found in team.html"
    assert "#B4F56B" in html_team, "Brand color #B4F56B not found in team.html"
    assert "#dc2626" not in html_team, "Old red #dc2626 found in team.html"
    assert "#0284c7" not in html_team, "Old blue #0284c7 found in team.html"
    print("[OK] team.html verified with #B4F56B brand accent.")

    # 4. Render organizer endpoint
    c = Client()
    u5 = User.objects.filter(username='test_org').first()
    if u5:
        c.force_login(u5)
        res_org = c.get('/organizer/5/')
        assert res_org.status_code == 200, f"Organizer dashboard failed: {res_org.status_code}"
        print(f"[OK] Rendered organizer_dashboard successfully (status=200, length={len(res_org.content)} bytes).")

    # 5. Render public competition viewer
    comp = Competition.objects.filter(is_published=True).first()
    if comp:
        res_pub = c.get(f'/competition/{comp.id}/?tab=upcoming')
        assert res_pub.status_code == 200, f"Failed GET /competition/{comp.id}/: {res_pub.status_code}"
        content = res_pub.content.decode('utf-8')
        assert "NEXT MATCH" in content, "Expected NEXT MATCH in upcoming tab response"
        print(f"[OK] Rendered competition_viewer successfully (status=200, length={len(content)} bytes).")

    print("\nALL POSTER & #B4F56B CHECKS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_match_posters()
