import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

import json
from django.test import Client
from django.contrib.auth import get_user_model
from teams.models import Team, Player, PositionChoice
from leagues.models import Competition

User = get_user_model()

def test_team_player_detail_feature():
    print("=== Testing Team Player View & Player Modal Feature ===")
    
    # 1. Check template text
    with open(os.path.join(BASE_DIR, 'front', 'organizer_team_detail.html'), 'r', encoding='utf-8') as f:
        html = f.read()

    grid_start = html.find('id="playersGrid"')
    grid_end = html.find('<!-- MODAL: ADD PLAYER -->')
    assert grid_start != -1 and grid_end != -1, "playersGrid or addPlayerModal boundary not found!"
    cards_section = html[grid_start:grid_end]
    assert "✕ Remove Player" not in cards_section, "ERROR: '✕ Remove Player' button still found on cards in playersGrid!"

    assert "openPlayerDetailModal" in html, "ERROR: openPlayerDetailModal not found in organizer_team_detail.html!"
    assert "modalCleanSheetsCard" in html, "ERROR: modalCleanSheetsCard not found in organizer_team_detail.html!"
    assert "modalGoals" in html, "ERROR: modalGoals not found in organizer_team_detail.html!"
    assert "modalAssists" in html, "ERROR: modalAssists not found in organizer_team_detail.html!"
    assert "modalYellowCards" in html, "ERROR: modalYellowCards not found in organizer_team_detail.html!"
    assert "modalRedCards" in html, "ERROR: modalRedCards not found in organizer_team_detail.html!"
    
    # Verify remove player is present in stats modal
    modal_start = html.find('id="playerDetailModal"')
    modal_end = html.find('<!-- JAVASCRIPT: MODAL & POSITION FILTER -->')
    assert modal_start != -1 and modal_end != -1, "ERROR: playerDetailModal boundary not found!"
    modal_part = html[modal_start:modal_end]
    assert "modalRemovePlayerForm" in modal_part, "ERROR: modalRemovePlayerForm not found in playerDetailModal!"
    assert "Remove Player" in modal_part, "ERROR: 'Remove Player' button not found in stats modal!"
    
    # Verify no appearance in the player detail modal
    assert "appearance" not in modal_part.lower(), "ERROR: 'appearance' found in playerDetailModal!"

    print("[OK] Template checks passed: 'Remove Player' removed from cards, added to stats modal, no appearance.")

    # 2. Test API endpoint /api/player/<id>/
    gk = Player.objects.filter(position=PositionChoice.GK).first()
    fwd = Player.objects.filter(position=PositionChoice.FWD).first()

    client = Client()

    if gk:
        res_gk = client.get(f'/api/player/{gk.id}/')
        assert res_gk.status_code == 200, f"Failed GET /api/player/{gk.id}/: {res_gk.status_code}"
        data_gk = json.loads(res_gk.content)
        assert data_gk['position_code'] == 'GK', f"Expected position_code 'GK', got {data_gk['position_code']}"
        assert 'clean_sheets' in data_gk, "clean_sheets missing in GK response"
        assert 'goals' in data_gk, "goals missing in GK response"
        assert 'assists' in data_gk, "assists missing in GK response"
        assert 'yellow_cards' in data_gk, "yellow_cards missing in GK response"
        assert 'red_cards' in data_gk, "red_cards missing in GK response"
        print(f"[OK] API GK Player details verified for #{gk.jersey_number} {gk.full_name}: CS={data_gk['clean_sheets']}")

    if fwd:
        res_fwd = client.get(f'/api/player/{fwd.id}/')
        assert res_fwd.status_code == 200, f"Failed GET /api/player/{fwd.id}/: {res_fwd.status_code}"
        data_fwd = json.loads(res_fwd.content)
        assert data_fwd['position_code'] == 'FWD', f"Expected position_code 'FWD', got {data_fwd['position_code']}"
        assert 'goals' in data_fwd, "goals missing in FWD response"
        assert 'assists' in data_fwd, "assists missing in FWD response"
        assert 'yellow_cards' in data_fwd, "yellow_cards missing in FWD response"
        assert 'red_cards' in data_fwd, "red_cards missing in FWD response"
        print(f"[OK] API FWD Player details verified for #{fwd.jersey_number} {fwd.full_name}: Goals={data_fwd['goals']}, Assists={data_fwd['assists']}")

    print("\nALL CHECKS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_team_player_detail_feature()
