import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from django.test import Client
from leagues.models import Competition
from matches.services import get_competition_statistics

def test_cards_separated():
    print("=== Testing Separated Yellow & Red Cards in Statistics ===")
    
    comp = Competition.objects.filter(primary_organizer__isnull=False).first()
    assert comp is not None

    stats = get_competition_statistics(comp)
    assert 'yellow_cards' in stats, "stats should have 'yellow_cards'"
    assert 'red_cards' in stats, "stats should have 'red_cards'"
    print(f"[OK] get_competition_statistics returned {len(stats['yellow_cards'])} yellow card entries and {len(stats['red_cards'])} red card entries.")

    client = Client()
    client.force_login(comp.primary_organizer)

    # 1. Organizer dashboard statistics tab
    resp_org = client.get(f'/organizer/{comp.id}/?tab=statistics')
    assert resp_org.status_code == 200
    content_org = resp_org.content.decode('utf-8')
    assert "Yellow Cards" in content_org, "Expected Yellow Cards in organizer statistics"
    assert "Red Cards" in content_org, "Expected Red Cards in organizer statistics"
    assert "Disciplinary Records" not in content_org, "Old combined disciplinary heading should be gone"
    print("[OK] Verified organizer statistics has separate Yellow Cards and Red Cards tables.")

    # 2. Public competition viewer statistics tab
    resp_pub = client.get(f'/competition/{comp.id}/?tab=stats')
    assert resp_pub.status_code == 200
    content_pub = resp_pub.content.decode('utf-8')
    assert "Yellow Cards" in content_pub, "Expected Yellow Cards in public viewer statistics"
    assert "Red Cards" in content_pub, "Expected Red Cards in public viewer statistics"
    assert "Disciplinary Records" not in content_pub, "Old combined disciplinary heading should be gone from public viewer"
    assert "modalPlayerYellowCards" in content_pub, "Expected separate modalPlayerYellowCards element"
    assert "modalPlayerRedCards" in content_pub, "Expected separate modalPlayerRedCards element"
    print("[OK] Verified public viewer statistics has separate Yellow Cards and Red Cards tables.")

    print("\nALL SEPARATED CARDS STATISTICS TESTS PASSED!")

if __name__ == '__main__':
    test_cards_separated()
