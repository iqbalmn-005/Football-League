import os
import sys
import django
from datetime import date, time

# Setup django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from django.contrib.auth.models import User
from leagues.models import Competition, TournamentFormat, CompetitionCategory, CompetitionStatus
from teams.models import Team, Player, PositionChoice
from matches.models import (
    Match, MatchStatus, MatchEventType, MatchEvent,
    PenaltyShootout, PenaltyShootoutAttempt,
    ShootoutPhase, ShootoutOutcome, ShootoutStatus
)
from matches.shootout_service import (
    get_or_create_shootout, get_shootout_state,
    record_shootout_attempt, undo_last_shootout_attempt,
    get_eligible_match_players, get_game_format_capacity
)
from fixtures.services import advance_knockout_bracket


def run_all_tests():
    print("================================================================")
    print("STARTING COMPLETE PENALTY SHOOTOUT TEST SUITE")
    print("================================================================")

    user, _ = User.objects.get_or_create(username="test_shootout_admin")

    # Helper to create a test tournament and teams with players
    def setup_tournament(category='7-a-side', extra_time_enabled=False, num_players=10):
        comp = Competition.objects.create(
            name=f"Shootout Cup {category} ET={extra_time_enabled}",
            competition_type='TOURNAMENT',
            tournament_format=TournamentFormat.SINGLE_ELIMINATION,
            category=category,
            season="2026/2027",
            status=CompetitionStatus.ACTIVE,
            extra_time_before_penalties=extra_time_enabled,
            created_by=user
        )

        team_a = Team.objects.create(name=f"Team Alpha {comp.id}", short_name="TMA")
        team_b = Team.objects.create(name=f"Team Beta {comp.id}", short_name="TMB")
        comp.teams.add(team_a, team_b)

        # Create players for each team
        for i in range(1, num_players + 1):
            Player.objects.create(
                team=team_a,
                full_name=f"Alpha Player {i}",
                jersey_number=i,
                position=PositionChoice.GK if i == 1 else PositionChoice.FWD
            )
            Player.objects.create(
                team=team_b,
                full_name=f"Beta Player {i}",
                jersey_number=i,
                position=PositionChoice.GK if i == 1 else PositionChoice.FWD
            )

        match = Match.objects.create(
            competition=comp,
            tournament_round="Quarter-Finals",
            round_number=1,
            home_team=team_a,
            away_team=team_b,
            match_date=date.today(),
            kickoff_time=time(15, 0),
            home_score=2,
            away_score=2,
            status=MatchStatus.LIVE
        )

        return comp, team_a, team_b, match

    # -------------------------------------------------------------
    # TEST 1: 7-a-side match with a winner in the first five penalties
    # -------------------------------------------------------------
    print("\n--- TEST 1: 7-a-side match with a winner in the first 5 penalties ---")
    comp, team_a, team_b, match = setup_tournament(category='7-a-side', num_players=8)
    shootout = get_or_create_shootout(match)
    
    # 5 kicks for Home, 5 kicks for Away (total 10)
    # Home scores 4, Away scores 3 -> Home wins at attempt 10!
    # Home: GOAL, GOAL, GOAL, MISS, GOAL (4)
    # Away: GOAL, MISS, GOAL, GOAL, MISS (3)
    home_players = get_eligible_match_players(match, team_a)
    away_players = get_eligible_match_players(match, team_b)
    assert len(home_players) == 7, f"Expected 7 eligible players, got {len(home_players)}"
    assert len(away_players) == 7, f"Expected 7 eligible players, got {len(away_players)}"

    outcomes_pattern = [
        (team_a, home_players[0], 'GOAL'), # 1. Home R1
        (team_b, away_players[0], 'GOAL'), # 2. Away R1
        (team_a, home_players[1], 'GOAL'), # 3. Home R2
        (team_b, away_players[1], 'MISS'), # 4. Away R2
        (team_a, home_players[2], 'GOAL'), # 5. Home R3
        (team_b, away_players[2], 'GOAL'), # 6. Away R3
        (team_a, home_players[3], 'MISS'), # 7. Home R4
        (team_b, away_players[3], 'GOAL'), # 8. Away R4
        (team_a, home_players[4], 'GOAL'), # 9. Home R5
        (team_b, away_players[4], 'MISS'), # 10. Away R5 -> Shootout ends!
    ]

    for team, player, outcome in outcomes_pattern:
        res = record_shootout_attempt(shootout, player.id, outcome)
        assert res['success'], f"Failed recording attempt: {res}"

    state = get_shootout_state(shootout)
    assert state['is_completed'], "Expected shootout to be completed after 10 attempts with unequal score"
    assert state['winner'].id == team_a.id, f"Expected Team Alpha to win, got {state['winner']}"
    assert state['home_score'] == 4
    assert state['away_score'] == 3
    match.refresh_from_db()
    assert match.status == MatchStatus.COMPLETED
    assert match.penalties is True
    assert match.home_penalties == 4
    assert match.away_penalties == 3
    print(f"[PASSED] Test 1: Shootout completed 4–3 in initial 5. Winner: {state['winner'].name}")

    # -------------------------------------------------------------
    # TEST 2: 7-a-side match tied after five penalties
    # -------------------------------------------------------------
    print("\n--- TEST 2: 7-a-side match tied after 5 penalties ---")
    comp, team_a, team_b, match = setup_tournament(category='7-a-side', num_players=8)
    shootout = get_or_create_shootout(match)
    home_players = get_eligible_match_players(match, team_a)
    away_players = get_eligible_match_players(match, team_b)

    # Both teams score 4 in first 5 rounds
    tied_pattern = [
        (team_a, home_players[0], 'GOAL'),
        (team_b, away_players[0], 'GOAL'),
        (team_a, home_players[1], 'GOAL'),
        (team_b, away_players[1], 'GOAL'),
        (team_a, home_players[2], 'GOAL'),
        (team_b, away_players[2], 'GOAL'),
        (team_a, home_players[3], 'MISS'),
        (team_b, away_players[3], 'MISS'),
        (team_a, home_players[4], 'GOAL'),
        (team_b, away_players[4], 'GOAL'),
    ]

    for team, player, outcome in tied_pattern:
        res = record_shootout_attempt(shootout, player.id, outcome)
        assert res['success']

    state = get_shootout_state(shootout)
    assert not state['is_completed'], "Shootout should NOT be completed when tied 4-4 after round 5"
    assert state['current_round'] == 6, f"Expected Round 6 (Sudden Death), got {state['current_round']}"
    assert state['current_phase'] == ShootoutPhase.SUDDEN_DEATH
    print("[PASSED] Test 2: Shootout tied 4–4 after Round 5, successfully transitioned to Sudden Death (Round 6).")

    # -------------------------------------------------------------
    # TEST 3: 7-a-side sudden death using the remaining two players
    # -------------------------------------------------------------
    print("\n--- TEST 3: 7-a-side sudden death using the remaining 2 players ---")
    # In 7-a-side, total players = 7. First 5 have been used. Exactly 2 unused players remain (players index 5 and 6).
    assert len(state['available_players']) == 2, f"Expected exactly 2 available players for Team A, got {len(state['available_players'])}"
    avail_ids = [p.id for p in state['available_players']]
    assert home_players[5].id in avail_ids
    assert home_players[6].id in avail_ids
    assert home_players[0].id not in avail_ids, "Player 1 from round 1 must NOT be available while unused players remain!"

    # Attempting to use player 0 must be rejected by backend validation!
    rejected_res = record_shootout_attempt(shootout, home_players[0].id, 'GOAL')
    assert not rejected_res['success'], "Backend must reject already-used player when unused eligible players remain!"
    print("[PASSED] Test 3: Backend successfully rejected already-used player when 2 unused players remained.")

    # Now use remaining player 5 for Home in Round 6
    res6a = record_shootout_attempt(shootout, home_players[5].id, 'GOAL')
    assert res6a['success']
    
    # Next is Away Round 6: Away must also use one of their 2 unused players!
    state = get_shootout_state(shootout)
    assert len(state['available_players']) == 2
    res6b = record_shootout_attempt(shootout, away_players[5].id, 'GOAL')
    assert res6b['success']

    # Both scored in Round 6 -> Still tied, Round 7!
    state = get_shootout_state(shootout)
    assert not state['is_completed']
    assert state['current_round'] == 7
    # Exactly 1 unused player remaining now for each team!
    assert len(state['available_players']) == 1
    assert state['available_players'][0].id == home_players[6].id
    print("[PASSED] Test 3: Round 6 sudden death completed with remaining players, advancing to Round 7.")

    # -------------------------------------------------------------
    # TEST 4: 7-a-side player rotation after all seven players have taken a penalty
    # -------------------------------------------------------------
    print("\n--- TEST 4: 7-a-side player rotation after all 7 players have taken a penalty ---")
    # Take Round 7 with the 7th player for each team, both score
    res7a = record_shootout_attempt(shootout, home_players[6].id, 'GOAL')
    assert res7a['success']
    res7b = record_shootout_attempt(shootout, away_players[6].id, 'GOAL')
    assert res7b['success']

    # Now all 7 players have taken 1 penalty! Round 8 begins!
    state = get_shootout_state(shootout)
    assert state['current_round'] == 8
    assert not state['is_completed']
    # Rotation must restart: all 7 players are available again for cycle 2!
    assert len(state['available_players']) == 7, f"Expected all 7 players available on rotation restart, got {len(state['available_players'])}"
    print(f"[PASSED] Test 4: All 7 players have taken 1 kick. Rotation restarted for Round 8 with {len(state['available_players'])} available players.")

    # Take Round 8: Home scores, Away misses -> Home wins in sudden death!
    res8a = record_shootout_attempt(shootout, home_players[0].id, 'GOAL')
    assert res8a['success']
    res8b = record_shootout_attempt(shootout, away_players[0].id, 'SAVED')
    assert res8b['success']

    state = get_shootout_state(shootout)
    assert state['is_completed']
    assert state['winner'].id == team_a.id
    print(f"[PASSED] Test 4: Round 8 sudden death decided winner: {state['winner'].name}.")

    # -------------------------------------------------------------
    # TEST 5: 11-a-side match with a winner in the first five penalties
    # -------------------------------------------------------------
    print("\n--- TEST 5: 11-a-side match with a winner in the first 5 penalties ---")
    comp, team_a, team_b, match = setup_tournament(category='11-a-side', num_players=15)
    shootout = get_or_create_shootout(match)
    home_players = get_eligible_match_players(match, team_a)
    away_players = get_eligible_match_players(match, team_b)
    assert len(home_players) == 11, f"Expected 11 players for 11-a-side, got {len(home_players)}"
    assert len(away_players) == 11, f"Expected 11 players for 11-a-side, got {len(away_players)}"

    # Home 5 - 3 Away in first 5 rounds
    p5 = [
        (team_a, home_players[0], 'GOAL'),
        (team_b, away_players[0], 'GOAL'),
        (team_a, home_players[1], 'GOAL'),
        (team_b, away_players[1], 'MISS'),
        (team_a, home_players[2], 'GOAL'),
        (team_b, away_players[2], 'GOAL'),
        (team_a, home_players[3], 'GOAL'),
        (team_b, away_players[3], 'MISS'),
        (team_a, home_players[4], 'GOAL'),
        (team_b, away_players[4], 'GOAL'),
    ]
    for team, player, outcome in p5:
        res = record_shootout_attempt(shootout, player.id, outcome)
        assert res['success']

    state = get_shootout_state(shootout)
    assert state['is_completed']
    assert state['home_score'] == 5 and state['away_score'] == 3
    assert state['winner'].id == team_a.id
    print(f"[PASSED] Test 5: 11-a-side shootout completed 5–3 in first 5. Winner: {state['winner'].name}")

    # -------------------------------------------------------------
    # TEST 6: 11-a-side match tied after five penalties
    # -------------------------------------------------------------
    print("\n--- TEST 6: 11-a-side match tied after 5 penalties ---")
    comp, team_a, team_b, match = setup_tournament(category='11-a-side', num_players=15)
    shootout = get_or_create_shootout(match)
    home_players = get_eligible_match_players(match, team_a)
    away_players = get_eligible_match_players(match, team_b)

    # 5-5 tie
    for i in range(5):
        record_shootout_attempt(shootout, home_players[i].id, 'GOAL')
        record_shootout_attempt(shootout, away_players[i].id, 'GOAL')

    state = get_shootout_state(shootout)
    assert not state['is_completed']
    assert state['current_round'] == 6
    assert state['home_score'] == 5 and state['away_score'] == 5
    print("[PASSED] Test 6: 11-a-side match tied 5–5 after first 5, correctly enters Sudden Death.")

    # -------------------------------------------------------------
    # TEST 7: 11-a-side sudden death using the remaining six players
    # -------------------------------------------------------------
    print("\n--- TEST 7: 11-a-side sudden death using the remaining 6 players ---")
    # In 11-a-side, 11 total. 5 used. Exactly 6 unused remaining (index 5 to 10).
    assert len(state['available_players']) == 6, f"Expected 6 remaining unused players, got {len(state['available_players'])}"
    for idx in range(5):
        assert home_players[idx].id not in [p.id for p in state['available_players']], f"Player {idx} must be excluded"
    print(f"[PASSED] Test 7: Exactly 6 unused players remaining in sudden death for 11-a-side.")

    # -------------------------------------------------------------
    # TEST 8: 11-a-side player rotation after all 11 players have taken a penalty
    # -------------------------------------------------------------
    print("\n--- TEST 8: 11-a-side player rotation after all 11 players take a penalty ---")
    # Play rounds 6 through 11 with the remaining 6 players, tied
    for r_idx in range(5, 11):
        record_shootout_attempt(shootout, home_players[r_idx].id, 'GOAL')
        record_shootout_attempt(shootout, away_players[r_idx].id, 'GOAL')

    state = get_shootout_state(shootout)
    assert state['current_round'] == 12, f"Expected Round 12, got {state['current_round']}"
    assert len(state['available_players']) == 11, f"Expected all 11 players available on rotation restart, got {len(state['available_players'])}"
    print("[PASSED] Test 8: All 11 players have taken 1 kick. Rotation successfully restarted for Round 12.")

    # -------------------------------------------------------------
    # TEST 9: Extra time enabled
    # -------------------------------------------------------------
    print("\n--- TEST 9: Extra time enabled ---")
    comp_et, t_a, t_b, match_et = setup_tournament(category='11-a-side', extra_time_enabled=True, num_players=11)
    assert comp_et.extra_time_before_penalties is True
    assert match_et.is_knockout is True
    # Simulate recording regular time 1-1, and extra time 2-2
    match_et.home_regular_score = 1
    match_et.away_regular_score = 1
    match_et.extra_time = True
    match_et.home_extra_time_score = 2
    match_et.away_extra_time_score = 2
    match_et.home_score = 2
    match_et.away_score = 2
    match_et.save()
    shootout_et = get_or_create_shootout(match_et)
    state_et = get_shootout_state(shootout_et)
    assert state_et['home_score'] == 0 and state_et['away_score'] == 0
    print("[PASSED] Test 9: Extra time enabled setting verified and shootout initialized after extra time tie.")

    # -------------------------------------------------------------
    # TEST 10: Extra time disabled
    # -------------------------------------------------------------
    print("\n--- TEST 10: Extra time disabled ---")
    comp_no_et, t_a, t_b, match_no_et = setup_tournament(category='11-a-side', extra_time_enabled=False, num_players=11)
    assert comp_no_et.extra_time_before_penalties is False
    match_no_et.home_score = 1
    match_no_et.away_score = 1
    match_no_et.save()
    shootout_no_et = get_or_create_shootout(match_no_et)
    state_no_et = get_shootout_state(shootout_no_et)
    assert state_no_et['current_round'] == 1
    print("[PASSED] Test 10: Extra time disabled verified; shootout proceeds immediately after tied regular time.")

    # -------------------------------------------------------------
    # TEST 11: Page refresh during a shootout
    # -------------------------------------------------------------
    print("\n--- TEST 11: Page refresh during a shootout ---")
    # Take 3 attempts on shootout_no_et
    p_home = get_eligible_match_players(match_no_et, t_a)
    p_away = get_eligible_match_players(match_no_et, t_b)
    record_shootout_attempt(shootout_no_et, p_home[0].id, 'GOAL')
    record_shootout_attempt(shootout_no_et, p_away[0].id, 'SAVED')
    record_shootout_attempt(shootout_no_et, p_home[1].id, 'GOAL')

    # Simulate page refresh: re-fetch from database from scratch
    refreshed_shootout = PenaltyShootout.objects.get(id=shootout_no_et.id)
    refreshed_state = get_shootout_state(refreshed_shootout)
    assert refreshed_state['home_score'] == 2
    assert refreshed_state['away_score'] == 0
    assert refreshed_state['current_round'] == 2
    assert refreshed_state['next_team'].id == t_b.id
    assert refreshed_state['next_attempt_order'] == 4
    assert len(refreshed_state['attempts']) == 3
    print("[PASSED] Test 11: Complete shootout state preserved accurately after simulating page refresh.")

    # -------------------------------------------------------------
    # TEST 12: Automatic winner advancement to the next knockout round
    # -------------------------------------------------------------
    print("\n--- TEST 12: Automatic winner advancement to next knockout round ---")
    # Create a knockout tournament with Semi-Finals and Final
    comp_adv = Competition.objects.create(
        name="Knockout Bracket Shootout Test",
        competition_type='TOURNAMENT',
        tournament_format=TournamentFormat.SINGLE_ELIMINATION,
        category='7-a-side',
        season="2026/2027",
        status=CompetitionStatus.ACTIVE,
        created_by=user
    )
    t1 = Team.objects.create(name=f"SF Team 1 {comp_adv.id}", short_name="SF1")
    t2 = Team.objects.create(name=f"SF Team 2 {comp_adv.id}", short_name="SF2")
    t3 = Team.objects.create(name=f"SF Team 3 {comp_adv.id}", short_name="SF3")
    t4 = Team.objects.create(name=f"SF Team 4 {comp_adv.id}", short_name="SF4")
    comp_adv.teams.add(t1, t2, t3, t4)

    for team in [t1, t2, t3, t4]:
        for i in range(1, 8):
            Player.objects.create(team=team, full_name=f"{team.short_name} Player {i}", jersey_number=i)

    # Semi-Final 1
    sf1 = Match.objects.create(
        competition=comp_adv,
        tournament_round="Semi-Finals",
        round_number=1,
        home_team=t1,
        away_team=t2,
        match_date=date.today(),
        kickoff_time=time(14, 0),
        home_score=1,
        away_score=1,
        status=MatchStatus.LIVE
    )
    # Semi-Final 2
    sf2 = Match.objects.create(
        competition=comp_adv,
        tournament_round="Semi-Finals",
        round_number=1,
        home_team=t3,
        away_team=t4,
        match_date=date.today(),
        kickoff_time=time(16, 30),
        home_score=2,
        away_score=0,
        status=MatchStatus.COMPLETED
    )
    # Final with placeholders
    final_match = Match.objects.create(
        competition=comp_adv,
        tournament_round="Final",
        round_number=2,
        home_team=None,
        away_team=None,
        placeholder_home="Winner of Semi-Final 1",
        placeholder_away="Winner of Semi-Final 2",
        match_date=date.today(),
        kickoff_time=time(19, 0),
        status=MatchStatus.SCHEDULED
    )

    # SF 2 winner advances into placeholder_away
    advance_knockout_bracket(comp_adv)
    final_match.refresh_from_db()
    assert final_match.away_team_id == t3.id

    # Now play shootout for SF 1: Team 2 (Away) wins on penalties!
    shootout_sf1 = get_or_create_shootout(sf1)
    p_sf1_home = get_eligible_match_players(sf1, t1)
    p_sf1_away = get_eligible_match_players(sf1, t2)

    # 5 kicks each: Away wins 4-3
    outcomes_sf1 = [
        (t1, p_sf1_home[0], 'GOAL'),
        (t2, p_sf1_away[0], 'GOAL'),
        (t1, p_sf1_home[1], 'MISS'),
        (t2, p_sf1_away[1], 'GOAL'),
        (t1, p_sf1_home[2], 'GOAL'),
        (t2, p_sf1_away[2], 'GOAL'),
        (t1, p_sf1_home[3], 'GOAL'),
        (t2, p_sf1_away[3], 'GOAL'),
        (t1, p_sf1_home[4], 'MISS'),
        (t2, p_sf1_away[4], 'MISS'),
    ]
    for team, player, outcome in outcomes_sf1:
        res = record_shootout_attempt(shootout_sf1, player.id, outcome)
        assert res['success']

    sf1.refresh_from_db()
    assert sf1.status == MatchStatus.COMPLETED
    assert sf1.penalties is True
    assert sf1.winner.id == t2.id, f"Expected Team 2 to win shootout, got {sf1.winner}"

    # Check that Final match automatically populated Team 2 in placeholder_home!
    final_match.refresh_from_db()
    assert final_match.home_team_id == t2.id, f"Expected SF1 winner ({t2.name}) in Final home_team, got {final_match.home_team}"
    assert final_match.placeholder_home == ''
    print(f"[PASSED] Test 12: Shootout winner ({t2.name}) automatically advanced to the Grand Final!")

    # Cleanup test data
    Competition.objects.filter(name__icontains="Shootout Cup").delete()
    User.objects.filter(username="test_shootout_admin").delete()

    print("\n================================================================")
    print("ALL 12 PENALTY SHOOTOUT TEST SCENARIOS PASSED SUCCESSFULLY!")
    print("================================================================")


if __name__ == '__main__':
    run_all_tests()
