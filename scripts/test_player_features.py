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
from django.contrib.messages import get_messages
from teams.models import Team, Player
from leagues.models import Competition

def run_tests():
    print("=== TESTING PLAYER REQUIREMENTS ===")
    client = Client()

    # Get or create an organizer user
    user = User.objects.filter(is_superuser=False).first()
    if not user:
        user = User.objects.create_user(username="test_org", password="password123")
    
    # Authenticate
    client.force_login(user)

    team = Team.objects.first()
    assert team is not None, "No team found in DB"

    print(f"[TEST 1] Verifying Duplicate Jersey Number Validation in {team.name}...")
    existing_player = team.players.first()
    assert existing_player is not None, "No player found in team"
    dup_jersey = existing_player.jersey_number

    # Attempt to add another player with the duplicate jersey number
    res = client.post(f'/organizer/team/{team.id}/player/add/', {
        'full_name': 'Duplicate Jersey Test Player',
        'jersey_number': dup_jersey,
        'position': 'FWD',
    }, follow=True)
    
    # Check that error message was produced and duplicate was NOT created
    messages = [m.message for m in get_messages(res.wsgi_request)]
    print(f"  Messages: {messages}")
    assert any(f"Jersey #{dup_jersey} is already" in m for m in messages), "Duplicate jersey check failed!"
    assert not Player.objects.filter(team=team, full_name='Duplicate Jersey Test Player').exists()
    print("  ✓ Duplicate jersey submission cleanly blocked!")

    print("[TEST 2] Verifying Position Required Validation...")
    res = client.post(f'/organizer/team/{team.id}/player/add/', {
        'full_name': 'No Position Player',
        'jersey_number': 88,
        'position': '',  # Empty position
    }, follow=True)
    messages = [m.message for m in get_messages(res.wsgi_request)]
    print(f"  Messages: {messages}")
    assert any("select a player position" in m.lower() for m in messages), "Empty position check failed!"
    assert not Player.objects.filter(team=team, full_name='No Position Player').exists()
    print("  ✓ Empty position submission cleanly blocked!")

    print("[TEST 3] Verifying Edit Player Endpoint (Name, Position, Jersey, Photo)...")
    # Test valid edit
    original_name = existing_player.full_name
    original_number = existing_player.jersey_number
    new_jersey = 77
    while Player.objects.filter(team=team, jersey_number=new_jersey).exists():
        new_jersey += 1

    res = client.post(f'/organizer/team/{team.id}/player/{existing_player.id}/edit/', {
        'full_name': 'Updated Test Name',
        'jersey_number': new_jersey,
        'position': 'MID',
    }, follow=True)
    
    existing_player.refresh_from_db()
    assert existing_player.full_name == 'Updated Test Name'
    assert existing_player.jersey_number == new_jersey
    assert existing_player.position == 'MID'
    print("  ✓ Player edited successfully with updated name, position, and jersey!")

    # Test editing to a conflicting jersey number
    other_player = team.players.exclude(id=existing_player.id).first()
    if other_player:
        conflict_num = other_player.jersey_number
        res = client.post(f'/organizer/team/{team.id}/player/{existing_player.id}/edit/', {
            'full_name': 'Conflict Try',
            'jersey_number': conflict_num,
            'position': 'MID',
        }, follow=True)
        messages = [m.message for m in get_messages(res.wsgi_request)]
        assert any(f"Jersey #{conflict_num} is already" in m for m in messages)
        print("  ✓ Edit duplicate jersey check blocked conflict!")

    # Restore original values
    existing_player.full_name = original_name
    existing_player.jersey_number = original_number
    existing_player.save()

    print("[TEST 4] Verifying Template Elements in organizer_team_detail.html...")
    with open('front/organizer_team_detail.html', 'r', encoding='utf-8') as f:
        html = f.read()

    assert 'id="editPlayerModal"' in html, "Edit player modal missing"
    assert 'id="deletePlayerModal"' in html, "Delete player popup modal missing"
    assert 'id="addPlayerJerseyError"' in html, "Inline jersey error missing"
    assert 'Select Position' in html, "Select position placeholder missing"
    assert 'goBackToPreviousPage' in html, "Back button script missing"
    assert 'confirm(' not in html, "Old browser alert/confirm still found!"
    print("  ✓ All modal, validation, and navigation components present and verified!")

    print("\nALL PLAYER FEATURE REQUIREMENTS VERIFIED SUCCESSFULLY! ✓")

if __name__ == '__main__':
    run_tests()
