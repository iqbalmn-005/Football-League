import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

def test_banner_only_in_dashboard():
    with open(os.path.join(BASE_DIR, 'front', 'organizer_index.html'), 'r', encoding='utf-8') as f:
        html = f.read()

    overview_start = html.find('id="overview"')
    assert overview_start != -1, "id='overview' not found in organizer_index.html!"
    
    fixtures_start = html.find('id="fixtures"')
    assert fixtures_start != -1, "id='fixtures' not found in organizer_index.html!"

    banner_start = html.find('class="league-banner"')
    assert banner_start != -1, "class='league-banner' not found in organizer_index.html!"

    # Verify banner is INSIDE the overview / dashboard section (before fixtures)
    assert overview_start < banner_start < fixtures_start, (
        f"Expected league-banner to be inside overview section! "
        f"overview_start={overview_start}, banner_start={banner_start}, fixtures_start={fixtures_start}"
    )

    print("[OK] Verified: league-banner is strictly inside the dashboard (#overview) tab.")

if __name__ == '__main__':
    test_banner_only_in_dashboard()

