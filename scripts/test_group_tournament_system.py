"""
Comprehensive Test Suite for Group-wise Tournament Management in Futbolix.
Verifies all 15 required scenarios:
1. Automatic team distribution
2. Manual team distribution
3. Unequal team distribution across groups
4. Duplicate team assignment prevention
5. Different numbers of groups
6. Odd and even numbers of teams
7. Single round-robin fixtures
8. Double round-robin fixtures
9. Independent group points tables
10. Automatic standings updates after match results
11. Custom qualification of 1, 2, 3 or more teams per group
12. Qualification validation
13. Knockout fixture generation using qualified teams
14. BYE handling in the knockout stage
15. Page refresh and database persistence
"""

import os
import sys
import django
from datetime import date, time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from django.contrib.auth.models import User
from leagues.models import (
    Competition, TournamentGroup, CompetitionTeam, QualifiedTeam,
    TournamentFormat, CompetitionStatus
)
from teams.models import Team, Player, PositionChoice
from matches.models import Match, MatchStatus
from standings.models import StandingEntry
from standings.services import recalculate_competition_standings
from leagues.group_service import (
    create_or_sync_groups,
    distribute_teams_automatically,
    distribute_teams_manually,
    get_group_distribution_status,
    confirm_group_assignments,
    generate_group_fixtures,
    get_group_standings_data,
    check_group_stage_completed,
    update_qualified_teams,
    generate_knockout_from_qualified_teams
)


def run_all_group_tests():
    print("================================================================")
    print("STARTING GROUP-WISE TOURNAMENT MANAGEMENT TEST SUITE")
    print("================================================================")

    user, _ = User.objects.get_or_create(username="test_group_admin")

    def create_test_comp(name, format_type='GROUP_KNOCKOUT', num_groups=2, qualifiers=2):
        comp = Competition.objects.create(
            name=name,
            competition_type='TOURNAMENT',
            tournament_format=format_type,
            season="2026/2027",
            status=CompetitionStatus.ACTIVE,
            num_groups=num_groups,
            qualifiers_per_group=qualifiers,
            created_by=user
        )
        return comp

    def add_teams_to_comp(comp, count, prefix="Team"):
        teams = []
        for i in range(1, count + 1):
            t = Team.objects.create(name=f"{prefix} {i} ({comp.id})", short_name=f"T{i}")
            CompetitionTeam.objects.create(competition=comp, team=t)
            teams.append(t)
        return teams

    # -------------------------------------------------------------------------
    # TEST 1: Automatic team distribution
    # -------------------------------------------------------------------------
    print("\n--- TEST 1: Automatic team distribution ---")
    comp1 = create_test_comp("Test Cup Auto 1", num_groups=2)
    teams1 = add_teams_to_comp(comp1, 8, "Alpha")
    res1 = distribute_teams_automatically(comp1, num_groups=2)
    assert res1['success'], f"Failed auto distribution: {res1}"
    groups1 = list(comp1.groups.order_by('name'))
    assert len(groups1) == 2, f"Expected 2 groups, got {len(groups1)}"
    assert groups1[0].group_teams.count() == 4
    assert groups1[1].group_teams.count() == 4
    print("[PASSED] Test 1: 8 teams automatically divided equally into 2 groups (4 and 4).")

    # -------------------------------------------------------------------------
    # TEST 2: Manual team distribution
    # -------------------------------------------------------------------------
    print("\n--- TEST 2: Manual team distribution ---")
    comp2 = create_test_comp("Test Cup Manual 2", num_groups=2)
    teams2 = add_teams_to_comp(comp2, 6, "Beta")
    groups2 = create_or_sync_groups(comp2, 2)
    assignments2 = {
        groups2[0].id: [teams2[0].id, teams2[1].id, teams2[2].id],
        groups2[1].id: [teams2[3].id, teams2[4].id, teams2[5].id],
    }
    res2 = distribute_teams_manually(comp2, assignments2)
    assert res2['success'], f"Manual distribution failed: {res2}"
    assert groups2[0].group_teams.count() == 3
    assert groups2[1].group_teams.count() == 3
    print("[PASSED] Test 2: Manual team assignment successfully persisted without errors.")

    # -------------------------------------------------------------------------
    # TEST 3: Unequal team distribution across groups
    # -------------------------------------------------------------------------
    print("\n--- TEST 3: Unequal team distribution across groups ---")
    comp3 = create_test_comp("Test Cup Unequal 3", num_groups=4)
    teams3 = add_teams_to_comp(comp3, 18, "Gamma")
    res3 = distribute_teams_automatically(comp3, num_groups=4)
    assert res3['success']
    groups3 = list(comp3.groups.order_by('name'))
    counts3 = [g.group_teams.count() for g in groups3]
    # 18 teams into 4 groups: 5, 5, 4, 4
    assert counts3 == [5, 5, 4, 4], f"Expected [5, 5, 4, 4], got {counts3}"
    unassigned3 = CompetitionTeam.objects.filter(competition=comp3, group__isnull=True).count()
    assert unassigned3 == 0, f"Expected 0 unassigned teams, got {unassigned3}"
    print(f"[PASSED] Test 3: 18 teams distributed unequally across 4 groups: {counts3} without unassigned teams.")

    # -------------------------------------------------------------------------
    # TEST 4: Duplicate team assignment prevention
    # -------------------------------------------------------------------------
    print("\n--- TEST 4: Duplicate team assignment prevention ---")
    comp4 = create_test_comp("Test Cup Dup 4", num_groups=2)
    teams4 = add_teams_to_comp(comp4, 4, "Delta")
    groups4 = create_or_sync_groups(comp4, 2)
    dup_assignments = {
        groups4[0].id: [teams4[0].id, teams4[1].id],
        groups4[1].id: [teams4[1].id, teams4[2].id, teams4[3].id]  # teams4[1] duplicated!
    }
    res4 = distribute_teams_manually(comp4, dup_assignments)
    assert not res4['success'], "Expected failure due to duplicate team assignment"
    assert "Duplicate" in res4['error'] or "duplicate" in res4['error']
    print(f"[PASSED] Test 4: Duplicate team assignment correctly rejected: '{res4['error']}'")

    # -------------------------------------------------------------------------
    # TEST 5: Different numbers of groups
    # -------------------------------------------------------------------------
    print("\n--- TEST 5: Different numbers of groups (3 and 6 groups) ---")
    comp5_3 = create_test_comp("Test Cup 3 Groups", num_groups=3)
    teams5_3 = add_teams_to_comp(comp5_3, 12, "Epsilon")
    res5_3 = distribute_teams_automatically(comp5_3, num_groups=3)
    assert res5_3['success']
    assert comp5_3.groups.count() == 3
    assert [g.group_teams.count() for g in comp5_3.groups.all()] == [4, 4, 4]

    comp5_6 = create_test_comp("Test Cup 6 Groups", num_groups=6)
    teams5_6 = add_teams_to_comp(comp5_6, 24, "Zeta")
    res5_6 = distribute_teams_automatically(comp5_6, num_groups=6)
    assert res5_6['success']
    assert comp5_6.groups.count() == 6
    assert all(g.group_teams.count() == 4 for g in comp5_6.groups.all())
    print("[PASSED] Test 5: Successfully supported 3 groups (4 teams each) and 6 groups (4 teams each).")

    # -------------------------------------------------------------------------
    # TEST 6: Odd and even numbers of teams
    # -------------------------------------------------------------------------
    print("\n--- TEST 6: Odd and even numbers of teams with BYE handling ---")
    comp6 = create_test_comp("Test Cup Odd 6", num_groups=2)
    teams6 = add_teams_to_comp(comp6, 7, "Eta") # 7 teams: Group A: 4, Group B: 3 (odd)
    res6 = distribute_teams_automatically(comp6, num_groups=2)
    assert res6['success']
    assert [g.group_teams.count() for g in comp6.groups.all()] == [4, 3]
    # Generate fixtures
    f_res6 = generate_group_fixtures(comp6, double_round=False)
    assert f_res6['success']
    # Group A with 4 teams: 4*(3)/2 = 6 matches
    # Group B with 3 teams: 3 matchweeks, 1 match per week + 1 BYE per week = 3 matches
    # Total matches = 6 + 3 = 9 matches
    assert f_res6['matches_count'] == 9, f"Expected 9 matches, got {f_res6['matches_count']}"
    print(f"[PASSED] Test 6: Handled odd and even group sizes (4 and 3 teams) generating 9 matches with BYEs.")

    # -------------------------------------------------------------------------
    # TEST 7: Single round-robin fixtures
    # -------------------------------------------------------------------------
    print("\n--- TEST 7: Single round-robin fixtures ---")
    comp7 = create_test_comp("Test Cup Single RR 7", num_groups=2)
    teams7 = add_teams_to_comp(comp7, 8, "Theta")
    distribute_teams_automatically(comp7, num_groups=2)
    f_res7 = generate_group_fixtures(comp7, double_round=False)
    assert f_res7['success']
    # 2 groups of 4 teams -> each group has 6 matches -> total 12 matches
    assert f_res7['matches_count'] == 12, f"Expected 12 matches, got {f_res7['matches_count']}"
    assert comp7.fixture_format == 'single'
    print("[PASSED] Test 7: Single round-robin produced 12 matches (6 per 4-team group).")

    # -------------------------------------------------------------------------
    # TEST 8: Double round-robin fixtures
    # -------------------------------------------------------------------------
    print("\n--- TEST 8: Double round-robin fixtures ---")
    comp8 = create_test_comp("Test Cup Double RR 8", num_groups=2)
    teams8 = add_teams_to_comp(comp8, 8, "Iota")
    distribute_teams_automatically(comp8, num_groups=2)
    f_res8 = generate_group_fixtures(comp8, double_round=True)
    assert f_res8['success']
    # Double round: 12 * 2 = 24 matches
    assert f_res8['matches_count'] == 24, f"Expected 24 matches, got {f_res8['matches_count']}"
    assert comp8.fixture_format == 'double'
    print("[PASSED] Test 8: Double round-robin produced 24 home & away matches.")

    # -------------------------------------------------------------------------
    # TEST 9: Independent group points tables
    # -------------------------------------------------------------------------
    print("\n--- TEST 9: Independent group points tables ---")
    comp9 = create_test_comp("Test Cup Tables 9", num_groups=2)
    teams9 = add_teams_to_comp(comp9, 8, "Kappa")
    distribute_teams_automatically(comp9, num_groups=2)
    generate_group_fixtures(comp9, double_round=False)
    tables9 = get_group_standings_data(comp9)
    assert len(tables9) == 2, f"Expected 2 group tables, got {len(tables9)}"
    groups9 = list(comp9.groups.order_by('name'))
    assert len(tables9[groups9[0]]) == 4
    assert len(tables9[groups9[1]]) == 4
    print("[PASSED] Test 9: Independent points tables generated for each group with 4 teams each.")

    # -------------------------------------------------------------------------
    # TEST 10: Automatic standings updates after match results
    # -------------------------------------------------------------------------
    print("\n--- TEST 10: Automatic standings updates after match results ---")
    comp10 = create_test_comp("Test Cup Standings 10", num_groups=2)
    teams10 = add_teams_to_comp(comp10, 8, "Lambda")
    distribute_teams_automatically(comp10, num_groups=2)
    generate_group_fixtures(comp10, double_round=False)
    
    # Complete match in Group A: Home team wins 3 - 0
    m_grpA = comp10.matches.filter(group__name='Group A').first()
    m_grpA.home_score = 3
    m_grpA.away_score = 0
    m_grpA.status = MatchStatus.COMPLETED
    m_grpA.save()
    recalculate_competition_standings(comp10)

    # Check that Group A table updated while Group B table remains 0 played
    entry_h = StandingEntry.objects.get(competition=comp10, team=m_grpA.home_team)
    assert entry_h.points == 3
    assert entry_h.played == 1
    assert entry_h.goal_difference == 3
    assert entry_h.position == 1

    entry_grpB = StandingEntry.objects.filter(competition=comp10, group__name='Group B').first()
    assert entry_grpB.played == 0
    assert entry_grpB.points == 0
    print("[PASSED] Test 10: Match result updated only Group A standings (Home team: 3 pts, +3 GD) without affecting Group B.")

    # -------------------------------------------------------------------------
    # TEST 11: Custom qualification of 1, 2, 3 or more teams per group
    # -------------------------------------------------------------------------
    print("\n--- TEST 11: Custom qualification of 1, 2, 3 teams per group ---")
    comp11 = create_test_comp("Test Cup Qual Settings 11", num_groups=2, qualifiers=1)
    teams11 = add_teams_to_comp(comp11, 8, "Mu")
    distribute_teams_automatically(comp11, num_groups=2)
    generate_group_fixtures(comp11, double_round=False)

    # Complete all matches in both groups
    for idx, m in enumerate(comp11.matches.filter(group__isnull=False)):
        m.home_score = 2 if idx % 2 == 0 else 0
        m.away_score = 1 if idx % 2 == 0 else 2
        m.status = MatchStatus.COMPLETED
        m.save()
    recalculate_competition_standings(comp11)

    # Qualifiers = 1 per group -> 2 total
    q_res1 = update_qualified_teams(comp11)
    assert q_res1['success']
    assert len(q_res1['qualified_teams']) == 2

    # Update to 2 per group -> 4 total
    comp11.qualifiers_per_group = 2
    comp11.save()
    q_res2 = update_qualified_teams(comp11)
    assert len(q_res2['qualified_teams']) == 4

    # Update to 3 per group -> 6 total
    comp11.qualifiers_per_group = 3
    comp11.save()
    q_res3 = update_qualified_teams(comp11)
    assert len(q_res3['qualified_teams']) == 6
    print("[PASSED] Test 11: Dynamic qualification settings validated for 1, 2, and 3 qualifiers per group.")

    # -------------------------------------------------------------------------
    # TEST 12: Qualification validation (cannot exceed group team count)
    # -------------------------------------------------------------------------
    print("\n--- TEST 12: Qualification validation ---")
    comp12 = create_test_comp("Test Cup Val 12", num_groups=2, qualifiers=10) # 10 exceeds 4 teams
    teams12 = add_teams_to_comp(comp12, 8, "Nu")
    distribute_teams_automatically(comp12, num_groups=2)
    val_res = update_qualified_teams(comp12)
    assert not val_res['success']
    assert "cannot exceed" in val_res['error']
    print(f"[PASSED] Test 12: Excessive qualification count correctly rejected: '{val_res['error']}'")

    # -------------------------------------------------------------------------
    # TEST 13: Knockout fixture generation using qualified teams
    # -------------------------------------------------------------------------
    print("\n--- TEST 13: Knockout fixture generation using qualified teams ---")
    comp13 = create_test_comp("Test Cup KO 13", num_groups=2, qualifiers=2)
    teams13 = add_teams_to_comp(comp13, 8, "Xi")
    distribute_teams_automatically(comp13, num_groups=2)
    generate_group_fixtures(comp13, double_round=False)

    # Complete group matches
    for idx, m in enumerate(comp13.matches.filter(group__isnull=False)):
        m.home_score = 3 if idx % 2 == 0 else 0
        m.away_score = 1 if idx % 2 == 0 else 2
        m.status = MatchStatus.COMPLETED
        m.save()
    recalculate_competition_standings(comp13)

    ko_res13 = generate_knockout_from_qualified_teams(comp13)
    assert ko_res13['success'], f"Failed knockout generation: {ko_res13}"
    # 4 qualified teams: 2 Semi-Finals + 1 Grand Championship Final = 3 matches
    assert ko_res13['knockout_matches_count'] == 3, f"Expected 3 matches, got {ko_res13['knockout_matches_count']}"

    # Verify cross-group pairing in SFs: Team from Group A vs Team from Group B
    sf_matches = comp13.matches.filter(tournament_round__icontains="Semi-Final")
    for sf in sf_matches:
        h_group = CompetitionTeam.objects.get(competition=comp13, team=sf.home_team).group.name
        a_group = CompetitionTeam.objects.get(competition=comp13, team=sf.away_team).group.name
        assert h_group != a_group, f"Cross-group pairing failed: {sf.home_team.name} ({h_group}) vs {sf.away_team.name} ({a_group})"
    print(f"[PASSED] Test 13: 4 qualified teams formed cross-group Semi-Finals and Final (3 matches total).")

    # -------------------------------------------------------------------------
    # TEST 14: BYE handling in the knockout stage (6 qualified teams)
    # -------------------------------------------------------------------------
    print("\n--- TEST 14: BYE handling in knockout stage (6 qualified teams) ---")
    comp14 = create_test_comp("Test Cup BYE 14", num_groups=2, qualifiers=3)
    teams14 = add_teams_to_comp(comp14, 8, "Omicron")
    distribute_teams_automatically(comp14, num_groups=2)
    generate_group_fixtures(comp14, double_round=False)

    # Complete group matches
    for idx, m in enumerate(comp14.matches.filter(group__isnull=False)):
        m.home_score = 2 if idx % 2 == 0 else 1
        m.away_score = 0 if idx % 2 == 0 else 3
        m.status = MatchStatus.COMPLETED
        m.save()
    recalculate_competition_standings(comp14)

    # 6 qualified teams (not a power of 2): distributed BYE system (2 BYEs to top seeds, 2 Round 1 matches)
    ko_res14 = generate_knockout_from_qualified_teams(comp14)
    assert ko_res14['success'], f"Failed knockout with BYEs: {ko_res14}"
    # 6 teams progression: Round 1 (2 matches, 2 byes) -> Semi-Finals (2 matches) -> Final (1 match) = 5 matches
    assert ko_res14['knockout_matches_count'] == 5, f"Expected 5 matches for 6 teams with BYEs, got {ko_res14['knockout_matches_count']}"
    print(f"[PASSED] Test 14: 6 qualified teams generated knockout with Futbolix distributed BYEs (5 matches total).")

    # -------------------------------------------------------------------------
    # TEST 15: Page refresh and database persistence
    # -------------------------------------------------------------------------
    print("\n--- TEST 15: Page refresh and database persistence ---")
    comp13.refresh_from_db()
    assert comp13.groups.count() == 2
    assert comp13.qualified_teams.count() == 4
    assert comp13.knockout_generated is True
    assert comp13.matches.filter(group__isnull=False).count() == 12
    assert comp13.matches.filter(group__isnull=True).count() == 3
    print("[PASSED] Test 15: Groups, fixtures, standings, and knockout matches are fully persistent in SQLite DB.")

    # Cleanup test cups
    Competition.objects.filter(name__startswith="Test Cup").delete()
    user.delete()

    print("\n================================================================")
    print("ALL 15 GROUP-WISE TOURNAMENT TEST SCENARIOS PASSED SUCCESSFULLY!")
    print("================================================================")


if __name__ == '__main__':
    run_all_group_tests()
