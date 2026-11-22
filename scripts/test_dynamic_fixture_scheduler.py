"""
Comprehensive automated tests for Futbolix Dynamic Fixture Scheduling System.
Validates:
1. Match calculation across all formats and rules.
2. Capacity & feasibility calculation with deficit reporting.
3. Strict enforcement of daily match limit globally across groups and stages.
4. No team playing twice on the same match date.
5. Group stage strictly concluding before knockout stage starts.
6. Semi-final scheduling preference (same day vs separate days).
7. Grand final showcase date strictly after semi-finals.
8. No silent date clamping on tight ranges.
"""
import os
import sys
from datetime import date, timedelta
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath('.'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
import django
django.setup()

from leagues.models import Competition, TournamentFormat, CompetitionStatus, CompetitionTeam
from teams.models import Team
from fixtures.services import (
    calculate_required_matches,
    calculate_scheduling_capacity,
    generate_smart_fixtures,
    TournamentFormat
)

def run_tests():
    print("=" * 70)
    print("FUTBOLIX DYNAMIC FIXTURE SCHEDULING SYSTEM VERIFICATION SUITE")
    print("=" * 70)

    # -------------------------------------------------------------
    # 1. Match Calculation Formulas Test
    # -------------------------------------------------------------
    print("\n--- 1. Testing Dynamic Match Calculations ---")
    # Single RR 6 teams: 6 * 5 / 2 = 15
    res = calculate_required_matches(teams_count=6, format_type='ROUND_ROBIN', is_double_round=False)
    assert res['total_matches'] == 15, f"Expected 15, got {res['total_matches']}"
    print(" [PASS] Single Round Robin 6 teams: 15 matches")

    # Double RR 6 teams: 6 * 5 = 30
    res = calculate_required_matches(teams_count=6, format_type='ROUND_ROBIN', is_double_round=True)
    assert res['total_matches'] == 30, f"Expected 30, got {res['total_matches']}"
    print(" [PASS] Double Round Robin 6 teams: 30 matches")

    # Group Knockout: 8 teams, 2 groups of 4. Group matches: 2 * (4*3/2) = 12.
    # 2 qualifiers/group = 4 qualifiers -> 3 knockout matches. Total = 15 matches.
    res = calculate_required_matches(
        teams_count=8, format_type='GROUP_KNOCKOUT', num_groups=2, qualifiers_per_group=2,
        is_double_round=False, knockout_legs='single'
    )
    assert res['group_stage_matches'] == 12, f"Expected 12 group matches, got {res['group_stage_matches']}"
    assert res['knockout_matches'] == 3, f"Expected 3 knockout matches, got {res['knockout_matches']}"
    assert res['total_matches'] == 15, f"Expected 15 total matches, got {res['total_matches']}"
    print(" [PASS] Group Knockout (8 teams, 2 groups, 2 qualifiers): 12 group + 3 knockout = 15 matches")

    # Pure Knockout single leg 11 teams: n - 1 = 10 matches
    res = calculate_required_matches(teams_count=11, format_type='KNOCKOUT', knockout_legs='single')
    assert res['total_matches'] == 10, f"Expected 10 matches, got {res['total_matches']}"
    print(" [PASS] Knockout Single Leg 11 teams (with BYEs): 10 matches")

    # Pure Knockout double leg 8 teams: (8 - 2) * 2 + 1 = 13 matches
    res = calculate_required_matches(teams_count=8, format_type='KNOCKOUT', knockout_legs='double')
    assert res['total_matches'] == 13, f"Expected 13 matches, got {res['total_matches']}"
    print(" [PASS] Knockout Double Leg 8 teams: 13 matches")

    # Page-McIntyre 4 teams: exactly 4 matches
    res = calculate_required_matches(teams_count=4, format_type='PAGE_MCINTYRE')
    assert res['total_matches'] == 4, f"Expected 4 matches, got {res['total_matches']}"
    print(" [PASS] Page-McIntyre 4 teams: 4 matches")

    # -------------------------------------------------------------
    # 2. Capacity & Feasibility Calculation Test
    # -------------------------------------------------------------
    print("\n--- 2. Testing Capacity & Feasibility Calculations ---")
    start = date(2027, 1, 1)  # Friday
    # Only Saturdays and Sundays: weekdays 5 and 6
    preferred = [5, 6]

    # Date range: 2027-01-01 to 2027-01-03 (1 Sat, 1 Sun = 2 match days)
    # Total matches: 6, matches_per_day: 1 -> Need 6 days, have 2 -> Infeasible!
    cap = calculate_scheduling_capacity(
        start_date=start,
        end_date=date(2027, 1, 3),
        preferred_weekdays=preferred,
        matches_per_day=1,
        total_matches=6,
        min_stage_days=2
    )
    assert not cap['is_feasible'], "Expected infeasible"
    assert cap['available_match_days'] == 2, f"Expected 2 match days, got {cap['available_match_days']}"
    assert cap['required_match_days'] == 6, f"Expected 6 required days, got {cap['required_match_days']}"
    assert cap['days_short'] == 4, f"Expected 4 days short, got {cap['days_short']}"
    assert cap['min_matches_per_day_needed'] == 3, f"Expected 3 matches/day needed, got {cap['min_matches_per_day_needed']}"
    assert cap['suggested_end_date'] is not None, "Expected suggested end date"
    print(f" [PASS] Detected infeasible schedule correctly: Short by {cap['days_short']} match days, suggested end date: {cap['suggested_end_date']}")

    # Sufficient range: 2027-01-01 to 2027-01-31 (10 weekend days, 10 capacity >= 6 matches)
    cap_ok = calculate_scheduling_capacity(
        start_date=start,
        end_date=date(2027, 1, 31),
        preferred_weekdays=preferred,
        matches_per_day=1,
        total_matches=6,
        min_stage_days=2
    )
    assert cap_ok['is_feasible'], "Expected feasible"
    assert cap_ok['available_match_days'] == 10, f"Expected 10 match days, got {cap_ok['available_match_days']}"
    print(" [PASS] Detected feasible schedule correctly with ample match days")

    # -------------------------------------------------------------
    # 3. Live Smart Fixture Generation with Real DB Models
    # -------------------------------------------------------------
    print("\n--- 3. Testing Smart Fixtures Generation Constraints ---")
    comp = Competition.objects.filter(teams__isnull=False).first()
    if not comp:
        print(" [SKIP] No competition found")
        return

    teams = list(comp.teams.all()[:8])
    if len(teams) < 8:
        # Create dummy teams
        for i in range(len(teams), 8):
            t = Team.objects.create(name=f"Sched Team {i+1}", short_name=f"ST{i+1}")
            CompetitionTeam.objects.create(competition=comp, team=t)
        teams = list(comp.teams.all()[:8])

    # Test 3.1: Date range enforcement: Fixtures generate ONLY between start_date and end_date
    tight_end = start + timedelta(days=2) # Only 1-2 days (requires 6 days)
    res_tight = generate_smart_fixtures(comp, {
        'tournament_format': TournamentFormat.ROUND_ROBIN,
        'round_robin_type': 'single',
        'start_date': start.isoformat(),
        'end_date': tight_end.isoformat(),
        'matches_per_day': 1,
        'preferred_days': ['Saturday', 'Sunday'],
        'selected_team_ids': [t.id for t in teams[:4]]  # 4 teams = 6 matches
    })
    assert not res_tight['success'], "Expected rejection when matches cannot fit between start and end date"
    assert not res_tight['is_feasible'], "Expected is_feasible to be False"
    assert res_tight['summary']['days_wanted'] == 6, f"Expected 6 days wanted, got {res_tight['summary']['days_wanted']}"
    assert len(res_tight['matches']) == 0, "Expected zero matches generated when date range is insufficient"
    print(f" [PASS] Date range strictly enforced: Rejects insufficient range, reports {res_tight['summary']['days_wanted']} days wanted")

    # Test 3.2: Feasible generation strictly enforces global daily matches limit across groups
    gen_end = start + timedelta(days=120)
    res_group = generate_smart_fixtures(comp, {
        'tournament_format': TournamentFormat.GROUP_KNOCKOUT,
        'num_groups': 2,
        'qualifiers_per_group': 2,
        'start_date': start.isoformat(),
        'end_date': gen_end.isoformat(),
        'matches_per_day': 2,  # Maximum 2 matches per day globally
        'daily_kickoff_times': ['15:00', '17:30'],
        'preferred_days': ['Saturday', 'Sunday'],
        'selected_team_ids': [t.id for t in teams[:8]],
    })
    assert res_group['success'], f"Generation failed: {res_group.get('errors')}"
    matches = res_group['matches']

    # Strictly between start_date and end_date
    for m in matches:
        m_d = date.fromisoformat(m['match_date']) if isinstance(m['match_date'], str) else m['match_date']
        assert m_d >= start and m_d <= gen_end, f"Match {m} scheduled outside start/end date range!"
    print(f" [PASS] All {len(matches)} generated matches strictly fall between {start} and {gen_end}")

    # Verify global daily count
    dates_count = Counter(m['match_date'] for m in matches)
    for d_str, count in dates_count.items():
        assert count <= 2, f"Violation of daily limit on {d_str}: {count} matches > 2 matches_per_day!"
    print(f" [PASS] Global daily limit strictly enforced: max matches per date = {max(dates_count.values())} <= 2")

    # Test 3.3: No team plays twice on the same match date
    teams_per_date = defaultdict(set)
    for m in matches:
        d = m['match_date']
        h = m['home_team_id']
        a = m['away_team_id']
        if h:
            assert h not in teams_per_date[d], f"Team {h} plays multiple matches on {d}!"
            teams_per_date[d].add(h)
        if a:
            assert a not in teams_per_date[d], f"Team {a} plays multiple matches on {d}!"
            teams_per_date[d].add(a)
    print(" [PASS] Rest rule strictly enforced: No team scheduled multiple times on the same date")

    # Test 3.4: Group stage strictly concludes before knockout stage begins
    group_matches = [m for m in matches if not m['is_knockout']]
    ko_matches = [m for m in matches if m['is_knockout']]
    assert len(group_matches) > 0 and len(ko_matches) > 0
    max_group_date = max(m['match_date'] for m in group_matches)
    min_ko_date = min(m['match_date'] for m in ko_matches)
    assert min_ko_date >= max_group_date, f"Knockout starts ({min_ko_date}) before group stage ends ({max_group_date})!"
    print(f" [PASS] Stage sequence enforced: Group stage ends {max_group_date}, Knockout starts {min_ko_date}")

    # Test 3.5: Semi-Finals and Final are ALWAYS on separated days
    sf_matches = [m for m in matches if 'Semi-Final' in m['round_name']]
    final_matches = [m for m in matches if 'Final' in m['round_name'] and 'Semi' not in m['round_name']]
    assert len(sf_matches) == 2, f"Expected 2 SF matches, got {len(sf_matches)}"
    assert len(final_matches) >= 1, "Expected Final match"
    final_match = final_matches[0]

    # SF1 and SF2 must be on separate dates
    assert sf_matches[0]['match_date'] != sf_matches[1]['match_date'], \
        f"Semi-finals on same date {sf_matches[0]['match_date']}! Must always be on separated days."
    # Final must be strictly after all SF dates
    latest_sf_date = max(sf_matches[0]['match_date'], sf_matches[1]['match_date'])
    assert final_match['match_date'] > latest_sf_date, \
        f"Final date {final_match['match_date']} not after latest semi-final date {latest_sf_date}!"
    print(f" [PASS] Semi-Finals and Final ALWAYS on separated days: SF1 on {sf_matches[0]['match_date']}, SF2 on {sf_matches[1]['match_date']}, Final on {final_match['match_date']}")

    # Test 3.6: Stage name present in all formatted match objects
    stages_present = set(m.get('stage_name') for m in matches)
    assert 'League Stage' in stages_present or any('Group Stage' in s for s in stages_present), f"Missing group stage name in {stages_present}"
    assert 'Semi-Finals' in stages_present, f"Missing Semi-Finals in {stages_present}"
    assert 'Championship Final' in stages_present, f"Missing Championship Final in {stages_present}"
    print(f" [PASS] Stage names present in formatted preview matches: {stages_present}")

    # Test 3.7: Odd team count in Round Robin (5 teams -> 5 * 4 / 2 = 10 matches)
    res_odd = generate_smart_fixtures(comp, {
        'tournament_format': TournamentFormat.ROUND_ROBIN,
        'round_robin_type': 'single',
        'start_date': start.isoformat(),
        'end_date': gen_end.isoformat(),
        'matches_per_day': 2,
        'preferred_days': ['Saturday', 'Sunday'],
        'selected_team_ids': [t.id for t in teams[:5]]  # 5 teams
    })
    assert res_odd['success'], f"Failed on odd team count: {res_odd.get('errors')}"
    assert len(res_odd['matches']) == 10, f"Expected 10 matches for 5 teams single RR, got {len(res_odd['matches'])}"
    # Every pair plays exactly once
    pair_counts = Counter()
    for m in res_odd['matches']:
        h, a = m['home_team_id'], m['away_team_id']
        pair_counts[tuple(sorted([h, a]))] += 1
    assert all(c == 1 for c in pair_counts.values()) and len(pair_counts) == 10, "Not all pairs played exactly once!"
    print(" [PASS] Odd team count (5 teams) Single RR: 10 matches, all pairs play exactly once")

    # Test 3.8: Double Round Robin home/away balance (4 teams -> 4 * 3 = 12 matches)
    res_drr = generate_smart_fixtures(comp, {
        'tournament_format': TournamentFormat.ROUND_ROBIN,
        'round_robin_type': 'double',
        'start_date': start.isoformat(),
        'end_date': gen_end.isoformat(),
        'matches_per_day': 2,
        'preferred_days': ['Saturday', 'Sunday'],
        'selected_team_ids': [t.id for t in teams[:4]]  # 4 teams
    })
    assert res_drr['success'], f"Failed on double RR: {res_drr.get('errors')}"
    assert len(res_drr['matches']) == 12, f"Expected 12 matches for 4 teams double RR, got {len(res_drr['matches'])}"
    # Each directed pair (A vs B) plays exactly once
    directed_pairs = Counter((m['home_team_id'], m['away_team_id']) for m in res_drr['matches'])
    assert all(c == 1 for c in directed_pairs.values()) and len(directed_pairs) == 12, "Double RR home/away balance violated!"
    print(" [PASS] Double Round Robin (4 teams): 12 matches, balanced home & away fixtures")

    # Test 3.9: Pure Knockout with distributed BYEs for odd team count (7 teams -> 6 matches)
    res_ko_odd = generate_smart_fixtures(comp, {
        'tournament_format': TournamentFormat.SINGLE_ELIMINATION,
        'tournament_type': 'single_elimination',
        'knockout_legs': 'single',
        'start_date': start.isoformat(),
        'end_date': gen_end.isoformat(),
        'matches_per_day': 2,
        'preferred_days': ['Saturday', 'Sunday'],
        'selected_team_ids': [t.id for t in teams[:7]]  # 7 teams -> 6 matches with 1 bye in R1
    })
    assert res_ko_odd['success'], f"Failed on 7 teams knockout: {res_ko_odd.get('errors')}"
    assert len(res_ko_odd['matches']) == 6, f"Expected 6 matches for 7 teams knockout, got {len(res_ko_odd['matches'])}"
    print(" [PASS] Pure Knockout with distributed BYEs (7 teams): exactly 6 matches")

    # Test 3.10: Database transaction commit verification (atomic commit, zero duplicates)
    from fixtures.services import commit_generated_fixtures
    from matches.models import Match, MatchStatus
    committed = commit_generated_fixtures(
        competition=comp,
        matches_data=res_group['matches'],
        groups_data=res_group['groups'],
        tournament_format=TournamentFormat.GROUP_KNOCKOUT
    )
    assert len(committed) == len(res_group['matches']), f"Expected {len(res_group['matches'])} matches saved, got {len(committed)}"
    assert comp.matches.filter(status=MatchStatus.SCHEDULED).count() == len(committed)
    print(f" [PASS] Database persistence: {len(committed)} fixtures committed transactionally without duplicates")

    print("\n" + "=" * 70)
    print("ALL DYNAMIC FIXTURE SCHEDULER TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == '__main__':
    run_tests()
