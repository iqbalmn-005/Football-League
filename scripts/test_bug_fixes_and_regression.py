"""
Comprehensive Verification and Regression Test Suite for Futbolix Bug Fixes:
1. BUG-SHOOTOUT-001: Penalty Shootout JSON vs HTML error responses.
2. BUG-SHOOTOUT-002: Mandatory Five-Penalties Rule & Sudden Death.
3. BUG-MATCH-001: Prevention of duplicate MatchEvent records on result updates.
4. BUG-VIEWER-001: Creator preview access for unpublished competitions.
5. BUG-NAV-001: Custom 404 & 500 error handlers and DEBUG environment toggle.
"""
import os
import sys
import django
from datetime import date, time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from django.test import Client, RequestFactory
from django.contrib.auth.models import User
from django.db import transaction
from django.http import Http404

from accounts.models import UserProfile, UserRole, OrganizerStatus
from leagues.models import Competition, TournamentFormat, CompetitionStatus, CompetitionTeam
from teams.models import Team, Player, PositionChoice
from matches.models import (
    Match, MatchStatus, MatchEvent, MatchEventType,
    PenaltyShootout, PenaltyShootoutAttempt, ShootoutStatus
)
from matches.shootout_service import (
    get_or_create_shootout, get_shootout_state,
    record_shootout_attempt, undo_last_shootout_attempt,
    get_eligible_match_players
)
from leagues.public_views import competition_viewer, custom_404_view, custom_500_view
from fixtures.services import plan_knockout_byes, get_knockout_stage_names


def run_tests():
    print("=" * 70)
    print("RUNNING FUTBOLIX RECTIFICATION & REGRESSION VERIFICATION SUITE")
    print("=" * 70)

    client = Client()
    passed_count = 0
    total_count = 0

    def record_result(test_name, passed, message=""):
        nonlocal passed_count, total_count
        total_count += 1
        if passed:
            passed_count += 1
            print(f" [PASS] {test_name}")
        else:
            print(f" [FAIL] {test_name}: {message}")

    # =========================================================================
    # 1. BUG-SHOOTOUT-001: Penalty Shootout AJAX Error Handling
    # =========================================================================
    print("\n--- Testing BUG-SHOOTOUT-001: Shootout AJAX Auth & Error Handling ---")
    
    # 1.1 Unauthenticated AJAX attempt must return JSON 401, not HTML 302
    res_unauth = client.post(
        '/organizer/match/9999/shootout/attempt/',
        {'player_id': '1', 'outcome': 'GOAL'},
        HTTP_X_REQUESTED_WITH='XMLHttpRequest'
    )
    is_json = 'application/json' in res_unauth.headers.get('content-type', '')
    record_result(
        "1.1 Unauthenticated AJAX attempt returns HTTP 401 JSON",
        res_unauth.status_code == 401 and is_json and res_unauth.json().get('redirect'),
        f"status={res_unauth.status_code}, content-type={res_unauth.headers.get('content-type')}"
    )

    # 1.2 Suspended Organizer AJAX attempt must return JSON 403
    suspended_user, _ = User.objects.get_or_create(username="test_suspended_org")
    if not hasattr(suspended_user, 'profile'):
        UserProfile.objects.create(user=suspended_user, role=UserRole.ORGANIZER, organizer_status=OrganizerStatus.SUSPENDED)
    else:
        suspended_user.profile.role = UserRole.ORGANIZER
        suspended_user.profile.organizer_status = OrganizerStatus.SUSPENDED
        suspended_user.profile.save()

    client.force_login(suspended_user)
    res_susp = client.post(
        '/organizer/match/9999/shootout/attempt/',
        {'player_id': '1', 'outcome': 'GOAL'},
        HTTP_X_REQUESTED_WITH='XMLHttpRequest'
    )
    record_result(
        "1.2 Suspended organizer AJAX returns HTTP 403 JSON",
        res_susp.status_code == 403 and 'suspended' in res_susp.json().get('error', '').lower(),
        f"status={res_susp.status_code}, body={res_susp.content}"
    )

    # 1.3 Unauthorized Viewer AJAX attempt must return JSON 403
    viewer_user, _ = User.objects.get_or_create(username="test_viewer_user")
    if not hasattr(viewer_user, 'profile'):
        UserProfile.objects.create(user=viewer_user, role=UserRole.VIEWER)
    else:
        viewer_user.profile.role = UserRole.VIEWER
        viewer_user.profile.save()

    client.force_login(viewer_user)
    res_viewer = client.post(
        '/organizer/match/9999/shootout/attempt/',
        {'player_id': '1', 'outcome': 'GOAL'},
        HTTP_X_REQUESTED_WITH='XMLHttpRequest'
    )
    record_result(
        "1.3 Viewer user AJAX attempt returns HTTP 403 JSON",
        res_viewer.status_code == 403 and 'denied' in res_viewer.json().get('error', '').lower(),
        f"status={res_viewer.status_code}, body={res_viewer.content}"
    )

    # 1.4 Approved Organizer with missing fields returns HTTP 400 JSON with specific error
    org_user, _ = User.objects.get_or_create(username="test_approved_org")
    if not hasattr(org_user, 'profile'):
        UserProfile.objects.create(user=org_user, role=UserRole.ORGANIZER, organizer_status=OrganizerStatus.APPROVED)
    else:
        org_user.profile.role = UserRole.ORGANIZER
        org_user.profile.organizer_status = OrganizerStatus.APPROVED
        org_user.profile.save()

    # Create temporary isolated match within transaction to test valid organizer requests
    with transaction.atomic():
        comp = Competition.objects.create(
            name="Test Shootout Cup",
            competition_type='TOURNAMENT',
            tournament_format=TournamentFormat.SINGLE_ELIMINATION,
            category='7-a-side',
            season="2026/2027",
            status=CompetitionStatus.ACTIVE,
            created_by=org_user
        )
        t_a = Team.objects.create(name="Team Alpha", short_name="TMA")
        t_b = Team.objects.create(name="Team Beta", short_name="TMB")
        comp.teams.add(t_a, t_b)
        p_a = [Player.objects.create(team=t_a, full_name=f"Alpha P{i}", jersey_number=i) for i in range(1, 8)]
        p_b = [Player.objects.create(team=t_b, full_name=f"Beta P{i}", jersey_number=i) for i in range(1, 8)]
        match = Match.objects.create(
            competition=comp,
            tournament_round="Semi-Finals",
            round_number=1,
            home_team=t_a,
            away_team=t_b,
            match_date=date.today(),
            kickoff_time=time(15, 0),
            home_score=1,
            away_score=1,
            status=MatchStatus.LIVE
        )

        client.force_login(org_user)
        res_missing = client.post(
            f'/organizer/match/{match.id}/shootout/attempt/',
            {'player_id': ''},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        record_result(
            "1.4 Missing fields return HTTP 400 JSON with validation message",
            res_missing.status_code == 400 and 'player id is required' in res_missing.json().get('error', '').lower(),
            f"status={res_missing.status_code}, error={res_missing.json()}"
        )

        transaction.set_rollback(True)

    # =========================================================================
    # 2. BUG-SHOOTOUT-002: Mandatory Five Penalties & Sudden Death Logic
    # =========================================================================
    print("\n--- Testing BUG-SHOOTOUT-002: Mandatory Five Rule & Sudden Death ---")
    with transaction.atomic():
        comp = Competition.objects.create(
            name="Shootout Rule Test Cup",
            competition_type='TOURNAMENT',
            tournament_format=TournamentFormat.SINGLE_ELIMINATION,
            category='7-a-side',
            season="2026/2027",
            status=CompetitionStatus.ACTIVE,
            created_by=org_user
        )
        t_a = Team.objects.create(name="Alpha", short_name="ALP")
        t_b = Team.objects.create(name="Beta", short_name="BET")
        comp.teams.add(t_a, t_b)
        players_a = [Player.objects.create(team=t_a, full_name=f"PA_{i}", jersey_number=i) for i in range(1, 8)]
        players_b = [Player.objects.create(team=t_b, full_name=f"PB_{i}", jersey_number=i) for i in range(1, 8)]

        # Red-card player 7 of Team A
        match = Match.objects.create(
            competition=comp,
            tournament_round="Quarter-Finals",
            round_number=1,
            home_team=t_a,
            away_team=t_b,
            match_date=date.today(),
            kickoff_time=time(15, 0),
            home_score=0,
            away_score=0,
            status=MatchStatus.LIVE
        )
        MatchEvent.objects.create(
            match=match,
            team=t_a,
            player=players_a[6], # PA_7
            event_type=MatchEventType.RED_CARD,
            minute=75
        )

        # 2.1 Verify red-carded player excluded from eligible kicking pool
        eligible_a = get_eligible_match_players(match, t_a)
        record_result(
            "2.1 Red-carded player excluded from eligible shootout pool",
            players_a[6] not in eligible_a and len(eligible_a) == 6,
            f"eligible_a length={len(eligible_a)}"
        )

        shootout = get_or_create_shootout(match)

        # 2.2 Simulate 3-0 lead after 3 rounds: verify shootout NOT terminated early
        # Team A scores first 3, Team B misses first 3
        for r in range(3):
            record_shootout_attempt(shootout, players_a[r].id, 'GOAL')
            record_shootout_attempt(shootout, players_b[r].id, 'MISS')

        shootout.refresh_from_db()
        record_result(
            "2.2 Mandatory Five Rule: Shootout NOT terminated early after 3 rounds (score 3-0)",
            shootout.status == ShootoutStatus.IN_PROGRESS and shootout.winner is None,
            f"status={shootout.status}, winner={shootout.winner}"
        )

        # Complete rounds 4 and 5 (Round 4: A miss, B goal -> 3-1. Round 5: A miss, B goal -> 3-2. Team A wins 3-2 after 10 kicks)
        record_shootout_attempt(shootout, players_a[3].id, 'MISS')
        record_shootout_attempt(shootout, players_b[3].id, 'GOAL')
        record_shootout_attempt(shootout, players_a[4].id, 'MISS')
        record_shootout_attempt(shootout, players_b[4].id, 'GOAL')

        shootout.refresh_from_db()
        record_result(
            "2.3 Winner declared exactly after 10 attempts (score 3-2)",
            shootout.status == ShootoutStatus.COMPLETED and shootout.winner == t_a and shootout.home_score == 3 and shootout.away_score == 2,
            f"status={shootout.status}, winner={shootout.winner}, score={shootout.home_score}-{shootout.away_score}"
        )

        transaction.set_rollback(True)

    # 2.4 Test Sudden Death progression when tied after 10 kicks
    with transaction.atomic():
        comp = Competition.objects.create(
            name="Sudden Death Cup",
            competition_type='TOURNAMENT',
            tournament_format=TournamentFormat.SINGLE_ELIMINATION,
            category='7-a-side',
            season="2026/2027",
            status=CompetitionStatus.ACTIVE,
            created_by=org_user
        )
        t_a = Team.objects.create(name="Alpha", short_name="ALP")
        t_b = Team.objects.create(name="Beta", short_name="BET")
        comp.teams.add(t_a, t_b)
        players_a = [Player.objects.create(team=t_a, full_name=f"PA_{i}", jersey_number=i) for i in range(1, 8)]
        players_b = [Player.objects.create(team=t_b, full_name=f"PB_{i}", jersey_number=i) for i in range(1, 8)]
        match = Match.objects.create(
            competition=comp,
            tournament_round="Final",
            round_number=1,
            home_team=t_a,
            away_team=t_b,
            match_date=date.today(),
            kickoff_time=time(15, 0),
            home_score=2,
            away_score=2,
            status=MatchStatus.LIVE
        )
        shootout = get_or_create_shootout(match)

        # 5 goals each in initial five -> 5-5 tied after 10 kicks
        for i in range(5):
            record_shootout_attempt(shootout, players_a[i].id, 'GOAL')
            record_shootout_attempt(shootout, players_b[i].id, 'GOAL')

        shootout.refresh_from_db()
        state = get_shootout_state(shootout)
        record_result(
            "2.4 Tied 5-5 after 10 kicks enters Sudden Death (Round 6)",
            shootout.status == ShootoutStatus.IN_PROGRESS and state['current_round'] == 6 and state['current_phase'] == 'SUDDEN_DEATH',
            f"round={state['current_round']}, phase={state['current_phase']}"
        )

        # Round 6: Both score (player 6 for each) -> tied 6-6, continues to Round 7
        record_shootout_attempt(shootout, players_a[5].id, 'GOAL')
        record_shootout_attempt(shootout, players_b[5].id, 'GOAL')
        shootout.refresh_from_db()
        state = get_shootout_state(shootout)
        record_result(
            "2.5 Sudden Death Round 6 tied 6-6 continues to Round 7",
            shootout.status == ShootoutStatus.IN_PROGRESS and state['current_round'] == 7,
            f"round={state['current_round']}, status={shootout.status}"
        )

        # Round 7: Team A scores, Team B misses -> Team A wins in Sudden Death!
        # Note: 7-a-side format: player 7 must kick in Round 7 before repetition
        record_shootout_attempt(shootout, players_a[6].id, 'GOAL')
        record_shootout_attempt(shootout, players_b[6].id, 'MISS')
        shootout.refresh_from_db()
        record_result(
            "2.6 Sudden Death Round 7: Team A scores and Team B misses -> Team A declared champion",
            shootout.status == ShootoutStatus.COMPLETED and shootout.winner == t_a and shootout.home_score == 7 and shootout.away_score == 6,
            f"status={shootout.status}, winner={shootout.winner}, score={shootout.home_score}-{shootout.away_score}"
        )

        transaction.set_rollback(True)

    # =========================================================================
    # 3. BUG-MATCH-001: Match Result Duplicate Prevention & Atomicity
    # =========================================================================
    print("\n--- Testing BUG-MATCH-001: Result Entry Duplicate Event Prevention ---")
    with transaction.atomic():
        comp = Competition.objects.create(
            name="Duplicate Prevention Cup",
            competition_type='TOURNAMENT',
            tournament_format=TournamentFormat.ROUND_ROBIN,
            season="2026/2027",
            status=CompetitionStatus.ACTIVE,
            created_by=org_user
        )
        t_a = Team.objects.create(name="Club Red", short_name="RED")
        t_b = Team.objects.create(name="Club Blue", short_name="BLU")
        comp.teams.add(t_a, t_b)
        gk_a = Player.objects.create(team=t_a, full_name="Red Keeper", jersey_number=1, position=PositionChoice.GK)
        fwd_a = Player.objects.create(team=t_a, full_name="Red Striker", jersey_number=9, position=PositionChoice.FWD)
        gk_b = Player.objects.create(team=t_b, full_name="Blue Keeper", jersey_number=1, position=PositionChoice.GK)

        match = Match.objects.create(
            competition=comp,
            tournament_round="Matchweek 1",
            round_number=1,
            home_team=t_a,
            away_team=t_b,
            match_date=date.today(),
            kickoff_time=time(16, 0),
            status=MatchStatus.SCHEDULED
        )

        client.force_login(org_user)

        # Initial result entry: 1-0 win for Red, Fwd scored, GK kept clean sheet
        post_data = {
            'home_score': '1',
            'away_score': '0',
            'home_goal_scorer': [str(fwd_a.id)],
            'home_goal_assist': [''],
            'home_goal_minute': ['35'],
            'card_player': [str(fwd_a.id)],
            'card_type': [MatchEventType.YELLOW_CARD],
            'card_team': ['home'],
            'card_minute': ['40'],
            'home_clean_sheet_keeper': str(gk_a.id)
        }
        res_post1 = client.post(f'/organizer/match/{match.id}/result/', post_data)
        
        events_1 = MatchEvent.objects.filter(match=match).count()
        goals_1 = MatchEvent.objects.filter(match=match, event_type=MatchEventType.GOAL).count()
        yellows_1 = MatchEvent.objects.filter(match=match, event_type=MatchEventType.YELLOW_CARD).count()
        clean_sheets_1 = MatchEvent.objects.filter(match=match, event_type=MatchEventType.CLEAN_SHEET).count()

        # Re-save the exact same result (simulate editing / pressing save again)
        res_post2 = client.post(f'/organizer/match/{match.id}/result/', post_data)

        events_2 = MatchEvent.objects.filter(match=match).count()
        goals_2 = MatchEvent.objects.filter(match=match, event_type=MatchEventType.GOAL).count()
        yellows_2 = MatchEvent.objects.filter(match=match, event_type=MatchEventType.YELLOW_CARD).count()
        clean_sheets_2 = MatchEvent.objects.filter(match=match, event_type=MatchEventType.CLEAN_SHEET).count()

        record_result(
            "3.1 Re-saving match result produces EXACT same event count (Zero Duplicates)",
            events_1 == events_2 and goals_1 == 1 and goals_2 == 1 and clean_sheets_1 == 1 and clean_sheets_2 == 1,
            f"events1={events_1}, events2={events_2}, goals2={goals_2}, cs2={clean_sheets_2}"
        )

        transaction.set_rollback(True)

    # =========================================================================
    # 4. BUG-VIEWER-001: Creator Preview of Unpublished Competition
    # =========================================================================
    print("\n--- Testing BUG-VIEWER-001: Organizer Preview of Unpublished Competition ---")
    with transaction.atomic():
        # Unpublished draft competition
        draft_comp = Competition.objects.create(
            name="Private Draft Tournament",
            competition_type='TOURNAMENT',
            tournament_format=TournamentFormat.SINGLE_ELIMINATION,
            season="2026/2027",
            status=CompetitionStatus.ACTIVE,
            is_published=False,
            created_by=org_user
        )

        # 4.1 Creator can view own unpublished competition
        client.force_login(org_user)
        res_creator = client.get(f'/competition/{draft_comp.id}/')
        record_result(
            "4.1 Competition creator can preview own unpublished competition (HTTP 200)",
            res_creator.status_code == 200,
            f"status={res_creator.status_code}"
        )

        # 4.2 Super Admin can view unpublished competition
        admin_user, _ = User.objects.get_or_create(username="test_super_admin", is_superuser=True, is_staff=True)
        client.force_login(admin_user)
        res_admin = client.get(f'/competition/{draft_comp.id}/')
        record_result(
            "4.2 Super Admin can preview unpublished competition (HTTP 200)",
            res_admin.status_code == 200,
            f"status={res_admin.status_code}"
        )

        # 4.3 Another regular viewer cannot view unpublished competition (HTTP 404)
        client.force_login(viewer_user)
        res_other_viewer = client.get(f'/competition/{draft_comp.id}/')
        record_result(
            "4.3 Non-owner viewer receives HTTP 404 on unpublished competition",
            res_other_viewer.status_code == 404,
            f"status={res_other_viewer.status_code}"
        )

        # 4.4 Anonymous user receives HTTP 404 on unpublished competition
        client.logout()
        res_anon = client.get(f'/competition/{draft_comp.id}/')
        record_result(
            "4.4 Anonymous public user receives HTTP 404 on unpublished competition",
            res_anon.status_code == 404,
            f"status={res_anon.status_code}"
        )

        # 4.5 When published, public access is available to everyone
        draft_comp.is_published = True
        draft_comp.save()
        res_pub_anon = client.get(f'/competition/{draft_comp.id}/')
        record_result(
            "4.5 Published competition is accessible to all users (HTTP 200)",
            res_pub_anon.status_code == 200,
            f"status={res_pub_anon.status_code}"
        )

        transaction.set_rollback(True)

    # =========================================================================
    # 5. BUG-NAV-001: Custom 404 & 500 Error Handlers
    # =========================================================================
    print("\n--- Testing BUG-NAV-001: Custom 404 & 500 Pages ---")
    rf = RequestFactory()
    
    # 5.1 Test custom 404 handler directly
    req_404 = rf.get('/non-existent-page/')
    res_custom_404 = custom_404_view(req_404)
    has_brand_404 = "FUTBOLIX" in res_custom_404.content.decode('utf-8')
    has_status_404 = res_custom_404.status_code == 404
    record_result(
        "5.1 Custom 404 view renders Futbolix Stadium Night template (HTTP 404)",
        has_status_404 and has_brand_404 and "Out of Bounds" in res_custom_404.content.decode('utf-8'),
        f"status={res_custom_404.status_code}, brand_in_html={has_brand_404}"
    )

    # 5.2 Test custom 500 handler directly
    req_500 = rf.get('/test-server-error/')
    res_custom_500 = custom_500_view(req_500)
    has_brand_500 = "FUTBOLIX" in res_custom_500.content.decode('utf-8')
    has_status_500 = res_custom_500.status_code == 500
    record_result(
        "5.2 Custom 500 view renders Futbolix Stadium Night template (HTTP 500)",
        has_status_500 and has_brand_500 and "Technical Stoppage" in res_custom_500.content.decode('utf-8'),
        f"status={res_custom_500.status_code}, brand_in_html={has_brand_500}"
    )

    # =========================================================================
    # 6. Regression Testing: Knockout Fixture Progression for all team counts
    # =========================================================================
    print("\n--- Regression Testing: Knockout Distributed BYEs (5 to 32 teams) ---")
    team_counts = [5, 6, 7, 8, 12, 16, 20, 24, 32]
    all_brackets_ok = True
    for n in team_counts:
        plan = plan_knockout_byes(n)
        stages = get_knockout_stage_names(n, plan)
        for st, p in zip(stages, plan):
            if p['byes'] > 3 or (st in ['Semi-Finals', 'Final'] and p['byes'] > 0):
                all_brackets_ok = False
        if sum(p['matches'] for p in plan) != n - 1:
            all_brackets_ok = False

    record_result(
        "6.1 Knockout Bracket Generator: 5, 6, 7, 8, 12, 16, 20, 24, 32 teams fully compliant",
        all_brackets_ok,
        "Bracket validation error"
    )

    print("\n" + "=" * 70)
    print(f"VERIFICATION SUMMARY: {passed_count}/{total_count} TESTS PASSED ({(passed_count/total_count)*100:.1f}%)")
    print("=" * 70)

    return passed_count == total_count


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
