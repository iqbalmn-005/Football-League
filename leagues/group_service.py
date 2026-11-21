"""
Group-wise League and Tournament Management Service for Futbolix.
Provides comprehensive business logic for:
1. Dynamic group creation and management
2. Automatic and manual team distribution
3. Independent group-wise fixture generation (single & double round-robin with BYE handling)
4. Independent group points tables & standings
5. Customizable qualification calculation & tracking
6. Knockout stage generation from qualified teams with cross-group pairing and distributed BYE system
"""

import math
from datetime import date, time, timedelta
from django.db import transaction
from django.utils import timezone
from leagues.models import (
    Competition, TournamentGroup, CompetitionTeam, QualifiedTeam,
    TournamentFormat, CompetitionStatus
)
from teams.models import Team
from matches.models import Match, MatchStatus
from standings.models import StandingEntry
from standings.services import recalculate_competition_standings
from fixtures.services import (
    _build_round_robin_rounds,
    _allocate_conflict_free_slot,
    _find_next_preferred_date,
    plan_knockout_byes,
    get_knockout_stage_names,
    advance_knockout_bracket,
    DEFAULT_VENUES,
    DEFAULT_KICKOFF_TIMES,
    WEEKDAY_MAP
)


def create_or_sync_groups(competition, num_groups):
    """
    Dynamically creates or updates groups for a competition based on the requested group count.
    Generates names: 'Group A', 'Group B', 'Group C', etc.
    """
    num_groups = max(1, int(num_groups))
    expected_names = [f"Group {chr(65 + i)}" for i in range(num_groups)]
    
    with transaction.atomic():
        existing_groups = list(competition.groups.order_by('name'))
        existing_names = [g.name for g in existing_groups]

        # Create missing groups
        created_groups = []
        for name in expected_names:
            grp, created = TournamentGroup.objects.get_or_create(competition=competition, name=name)
            created_groups.append(grp)

        # If reducing number of groups, clean up empty extra groups
        for grp in existing_groups:
            if grp.name not in expected_names and grp.group_teams.count() == 0 and grp.matches.count() == 0:
                grp.delete()

        competition.num_groups = num_groups
        competition.save(update_fields=['num_groups'])

    return list(competition.groups.order_by('name'))


def distribute_teams_automatically(competition, num_groups=None):
    """
    Automatically distributes registered teams across the selected groups.
    - Distributes teams as equally as possible.
    - If team count cannot be divided equally, distributes remaining teams across groups
      (e.g., 18 teams into 4 groups: Group A: 5, Group B: 5, Group C: 4, Group D: 4).
    - Prevents duplicate team assignments and ensures no teams are left unassigned.
    """
    if competition.is_completed:
        return {'success': False, 'error': "This competition is already completed. Teams and groups cannot be modified."}
    if num_groups is None:
        num_groups = competition.num_groups or 2
    num_groups = max(1, int(num_groups))

    groups = create_or_sync_groups(competition, num_groups)
    comp_teams = list(CompetitionTeam.objects.filter(competition=competition).select_related('team').order_by('id'))

    if not comp_teams:
        return {'success': False, 'error': "No teams registered in this competition to distribute."}

    total_teams = len(comp_teams)
    base_size = total_teams // num_groups
    remainder = total_teams % num_groups

    # Target size per group: first 'remainder' groups get base_size + 1, rest get base_size
    target_sizes = [base_size + (1 if i < remainder else 0) for i in range(num_groups)]

    with transaction.atomic():
        team_idx = 0
        distribution_preview = {}
        for g_idx, grp in enumerate(groups):
            count_for_this_group = target_sizes[g_idx]
            group_team_list = comp_teams[team_idx:team_idx + count_for_this_group]
            team_idx += count_for_this_group

            distribution_preview[grp.name] = []
            for ct in group_team_list:
                ct.group = grp
                ct.save(update_fields=['group'])
                distribution_preview[grp.name].append({
                    'id': ct.team.id,
                    'name': ct.team.name,
                    'short_name': ct.team.short_name
                })

        competition.distribution_method = 'automatic'
        competition.save(update_fields=['distribution_method'])
        recalculate_competition_standings(competition)

        # If group fixtures already exist, automatically regenerate them to reflect new group rosters
        if competition.matches.filter(group__isnull=False).exists():
            generate_group_fixtures(competition)

    return {
        'success': True,
        'groups': distribution_preview,
        'total_teams': total_teams,
        'num_groups': num_groups,
        'target_sizes': target_sizes
    }


def distribute_teams_manually(competition, group_assignments):
    """
    Manually distributes teams according to the organizer's specifications.
    group_assignments can be:
    - dict of {group_id or group_name: [team_ids]}
    Validates:
    1. Every assigned team must be registered in the competition.
    2. No duplicate team assignments across groups.
    3. No registered teams left unassigned.
    """
    if competition.is_completed:
        return {'success': False, 'error': "This competition is already completed. Teams and groups cannot be modified."}
    comp_teams = list(CompetitionTeam.objects.filter(competition=competition).select_related('team'))
    valid_team_ids = {ct.team_id for ct in comp_teams}
    groups = {g.id: g for g in competition.groups.all()}
    groups_by_name = {g.name: g for g in competition.groups.all()}

    assigned_team_ids = set()
    parsed_assignments = []

    for key, team_ids in group_assignments.items():
        # Resolve group
        grp = groups.get(int(key)) if str(key).isdigit() else groups_by_name.get(str(key))
        if not grp:
            return {'success': False, 'error': f"Group '{key}' not found in this competition."}

        for t_id in team_ids:
            t_id = int(t_id)
            if t_id not in valid_team_ids:
                return {'success': False, 'error': f"Team ID {t_id} is not registered in this competition."}
            if t_id in assigned_team_ids:
                team = next(ct.team for ct in comp_teams if ct.team_id == t_id)
                return {'success': False, 'error': f"Duplicate team assignment: '{team.name}' is assigned to multiple groups."}
            assigned_team_ids.add(t_id)
            parsed_assignments.append((t_id, grp))

    unassigned_ids = valid_team_ids - assigned_team_ids
    if unassigned_ids:
        unassigned_names = [ct.team.name for ct in comp_teams if ct.team_id in unassigned_ids]
        return {
            'success': False,
            'error': f"Cannot confirm distribution: {len(unassigned_names)} teams remain unassigned ({', '.join(unassigned_names)}). All registered teams must be assigned.",
            'unassigned_teams': unassigned_names
        }

    with transaction.atomic():
        for t_id, grp in parsed_assignments:
            CompetitionTeam.objects.filter(competition=competition, team_id=t_id).update(group=grp)

        competition.distribution_method = 'manual'
        competition.save(update_fields=['distribution_method'])
        recalculate_competition_standings(competition)

        # If group fixtures already exist, automatically regenerate them to reflect new group rosters
        if competition.matches.filter(group__isnull=False).exists():
            generate_group_fixtures(competition)

    return {'success': True}


def get_group_distribution_status(competition):
    """
    Returns current group distribution state:
    - Groups with their assigned teams
    - Unassigned registered teams
    - Counts and validity flag
    """
    groups = list(competition.groups.order_by('name'))
    comp_teams = list(CompetitionTeam.objects.filter(competition=competition).select_related('team', 'group'))
    
    assigned_by_group = {g.id: [] for g in groups}
    unassigned = []

    for ct in comp_teams:
        t_data = {
            'id': ct.team.id,
            'name': ct.team.name,
            'short_name': ct.team.short_name,
            'logo_url': ct.team.get_logo_url()
        }
        if ct.group_id and ct.group_id in assigned_by_group:
            assigned_by_group[ct.group_id].append(t_data)
        else:
            unassigned.append(t_data)

    groups_data = []
    for g in groups:
        groups_data.append({
            'id': g.id,
            'name': g.name,
            'teams': assigned_by_group[g.id],
            'count': len(assigned_by_group[g.id])
        })

    is_valid = (len(unassigned) == 0 and len(comp_teams) > 0 and all(g['count'] > 0 for g in groups_data))

    return {
        'competition_id': competition.id,
        'groups': groups_data,
        'unassigned_teams': unassigned,
        'total_registered': len(comp_teams),
        'is_valid': is_valid,
        'groups_confirmed': competition.groups_confirmed
    }


def confirm_group_assignments(competition):
    """
    Validates and marks group assignments as confirmed.
    """
    if competition.is_completed:
        return {'success': False, 'error': "This competition is already completed. Group assignments cannot be modified."}
    status = get_group_distribution_status(competition)
    if not status['is_valid']:
        if status['unassigned_teams']:
            return {'success': False, 'error': f"{len(status['unassigned_teams'])} teams are still unassigned. All registered teams must be assigned before confirming."}
        return {'success': False, 'error': "Groups are empty or invalid."}

    competition.groups_confirmed = True
    competition.save(update_fields=['groups_confirmed'])
    recalculate_competition_standings(competition)
    if competition.matches.filter(group__isnull=False).exists():
        generate_group_fixtures(competition)
    return {'success': True}


def generate_group_fixtures(competition, double_round=False, start_date=None, preferred_weekdays=None, matches_per_day=1, slot_times=None, venues=None):
    """
    Generates fixtures independently for every group in the competition.
    - Teams play ONLY against teams in their own group.
    - Generates matchweeks for each group.
    - Handles odd and even numbers of teams (1 BYE per matchweek if odd).
    - Prevents cross-group matches.
    - Assigns match.group = group_obj and round_name = 'Group X - Matchweek Y'.
    - Deletes only previously scheduled group-stage matches, leaving completed results intact.
    """
    if competition.is_completed:
        return {'success': False, 'error': "This competition is already completed. Fixtures cannot be generated."}
    groups = list(competition.groups.order_by('name'))
    if not groups:
        return {'success': False, 'error': "No groups found. Please create groups and distribute teams first."}

    # Verify all teams are assigned to a group
    unassigned = CompetitionTeam.objects.filter(competition=competition, group__isnull=True).count()
    if unassigned > 0:
        return {'success': False, 'error': f"Cannot generate fixtures: {unassigned} teams remain unassigned to any group."}

    start_date = start_date or competition.start_date or date.today()
    if preferred_weekdays is None:
        preferred_weekdays = [5, 6]  # Saturday, Sunday

    matches_per_day = max(1, int(matches_per_day or 1))

    if slot_times is None:
        slot_times = [time(15, 0)] if matches_per_day == 1 else [time(15, 0), time(17, 30)]
    while len(slot_times) < matches_per_day:
        last_t = slot_times[-1]
        slot_times.append(time(min(last_t.hour + 2, 22), last_t.minute))
    slot_times = slot_times[:matches_per_day]

    if venues is None or len(venues) == 0:
        team_venues = [ct.team.home_venue for ct in CompetitionTeam.objects.filter(competition=competition) if getattr(ct.team, 'home_venue', '')]
        venues = list(dict.fromkeys(team_venues + DEFAULT_VENUES))[:6]

    booked_slots = set()
    created_matches = []

    with transaction.atomic():
        # Clear existing SCHEDULED group matches
        competition.matches.filter(group__isnull=False, status=MatchStatus.SCHEDULED).delete()

        # Build independent round-robin rounds for each group
        group_rounds_map = {}
        max_group_rounds = 0

        for grp in groups:
            group_teams = [ct.team for ct in grp.group_teams.all().select_related('team')]
            if len(group_teams) < 2:
                continue

            g_rounds = _build_round_robin_rounds(group_teams, double_round=double_round, prefix=f"{grp.name} - ")
            group_rounds_map[grp] = g_rounds
            if len(g_rounds) > max_group_rounds:
                max_group_rounds = len(g_rounds)

        if max_group_rounds == 0:
            return {'success': False, 'error': "At least one group must have 2 or more teams to generate fixtures."}

        cur_date = _find_next_preferred_date(start_date, preferred_weekdays)

        # Schedule matchweek by matchweek across all groups concurrently
        for week_idx in range(max_group_rounds):
            daily_count = 0
            for grp in groups:
                rounds_for_grp = group_rounds_map.get(grp, [])
                if week_idx >= len(rounds_for_grp):
                    continue

                round_data = rounds_for_grp[week_idx]
                r_name = round_data['round_name']
                r_num = week_idx + 1

                for home_team, away_team in round_data['pairs']:
                    if home_team is None or away_team is None:
                        continue  # BYE

                    if daily_count >= matches_per_day:
                        cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays)
                        daily_count = 0

                    desired_time = slot_times[daily_count % len(slot_times)]
                    desired_venue = getattr(home_team, 'home_venue', '') or venues[daily_count % len(venues)]

                    m_date, k_time, v_name = _allocate_conflict_free_slot(
                        cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                        preferred_weekdays=preferred_weekdays
                    )

                    match = Match.objects.create(
                        competition=competition,
                        group=grp,
                        tournament_round=r_name,
                        round_number=r_num,
                        home_team=home_team,
                        away_team=away_team,
                        match_date=m_date,
                        kickoff_time=k_time,
                        venue=v_name,
                        status=MatchStatus.SCHEDULED
                    )
                    created_matches.append(match)
                    daily_count += 1

            # Advance to next matchweek date for the next group matchweek
            cur_date = _find_next_preferred_date(cur_date + timedelta(days=7), preferred_weekdays)

        # Initialize standings tables with 0s
        recalculate_competition_standings(competition)

        competition.fixture_format = 'double' if double_round else 'single'
        if competition.status == CompetitionStatus.UPCOMING:
            competition.status = CompetitionStatus.ACTIVE
        competition.save(update_fields=['fixture_format', 'status'])

    return {
        'success': True,
        'matches_count': len(created_matches),
        'matches': created_matches
    }


def get_group_standings_data(competition):
    """
    Returns independent standings tables for every group in the competition.
    Includes qualification highlight badges based on qualifiers_per_group.
    Ensures stale entries from previous group redistributions are pruned.
    """
    groups = list(competition.groups.order_by('name'))
    if not groups:
        return {}

    comp_teams = list(CompetitionTeam.objects.filter(competition=competition).select_related('team', 'group'))
    valid_team_ids_by_group = {
        grp.id: {ct.team_id for ct in comp_teams if ct.group_id == grp.id}
        for grp in groups
    }

    standings_entries = list(
        StandingEntry.objects.filter(competition=competition, group__in=groups)
        .select_related('group', 'team')
        .order_by('group__name', 'position')
    )

    # Check if standings are out of sync with current group assignments
    needs_recalc = False
    for grp in groups:
        valid_ids = valid_team_ids_by_group.get(grp.id, set())
        grp_entries = [e for e in standings_entries if e.group_id == grp.id]
        grp_entry_team_ids = {e.team_id for e in grp_entries}
        if grp_entry_team_ids != valid_ids:
            needs_recalc = True
            break

    if needs_recalc:
        recalculate_competition_standings(competition)
        standings_entries = list(
            StandingEntry.objects.filter(competition=competition, group__in=groups)
            .select_related('group', 'team')
            .order_by('group__name', 'position')
        )

    q_per_group = competition.qualifiers_per_group or 2
    group_tables = {}

    group_matches_qs = list(competition.matches.filter(group__in=groups).values('group_id', 'status'))
    group_matches_by_id = {}
    for gm in group_matches_qs:
        group_matches_by_id.setdefault(gm['group_id'], []).append(gm['status'])

    for grp in groups:
        grp_m_statuses = group_matches_by_id.get(grp.id, [])
        grp_completed = bool(grp_m_statuses and all(s == MatchStatus.COMPLETED for s in grp_m_statuses))
        valid_ids = valid_team_ids_by_group.get(grp.id, set())
        entries = [e for e in standings_entries if e.group_id == grp.id and e.team_id in valid_ids]
        entries_data = []
        for e in entries:
            is_qualified_pos = bool(grp_completed and (e.position <= q_per_group))
            entries_data.append({
                'entry': e,
                'team': e.team,
                'position': e.position,
                'played': e.played,
                'won': e.won,
                'drawn': e.drawn,
                'lost': e.lost,
                'goals_for': e.goals_for,
                'goals_against': e.goals_against,
                'goal_difference': e.goal_difference,
                'points': e.points,
                'form_list': e.form_list,
                'is_qualified_position': is_qualified_pos
            })
        group_tables[grp] = entries_data

    return group_tables


def check_group_stage_completed(competition, group=None):
    """
    Checks if all matches in the group stage (or for a specific group) are completed.
    """
    if group:
        matches = competition.matches.filter(group=group)
    else:
        matches = competition.matches.filter(group__isnull=False)

    return matches.exists() and not matches.exclude(status=MatchStatus.COMPLETED).exists()


def update_qualified_teams(competition):
    """
    Identifies and persists qualified teams from the group stage:
    - Only updates once the group stage is completed.
    - Takes top `qualifiers_per_group` from each group.
    - Validates qualification count does not exceed group size.
    - Prevents duplicates via QualifiedTeam model.
    """
    groups = list(competition.groups.order_by('name'))
    if not groups:
        return {'success': False, 'error': "No groups found in competition."}

    # Check minimum group size
    min_size = min((g.group_teams.count() for g in groups), default=0)
    q_per_group = competition.qualifiers_per_group or 2
    if q_per_group > min_size:
        return {
            'success': False,
            'error': f"Qualifiers per group ({q_per_group}) cannot exceed the smallest group size ({min_size} teams)."
        }

    # Ensure group stage is fully completed before qualifying teams
    if not check_group_stage_completed(competition):
        return {
            'success': False,
            'error': "Group stage is not yet completed. All group matches must be finished before teams qualify.",
            'is_completed': False
        }

    # Recalculate standings to ensure exact order
    recalculate_competition_standings(competition)

    qualified_records = []
    eliminated_teams = []

    with transaction.atomic():
        QualifiedTeam.objects.filter(competition=competition).delete()

        for grp in groups:
            entries = list(StandingEntry.objects.filter(competition=competition, group=grp).order_by('position'))
            for idx, entry in enumerate(entries, start=1):
                if idx <= q_per_group:
                    qt = QualifiedTeam.objects.create(
                        competition=competition,
                        group=grp,
                        team=entry.team,
                        rank_in_group=idx
                    )
                    qualified_records.append(qt)
                else:
                    eliminated_teams.append({
                        'team': entry.team,
                        'group': grp,
                        'rank': idx,
                        'points': entry.points
                    })

    return {
        'success': True,
        'qualified_teams': qualified_records,
        'eliminated_teams': eliminated_teams,
        'total_qualified': len(qualified_records),
        'is_completed': True
    }


def generate_knockout_from_qualified_teams(competition, start_date=None, preferred_weekdays=None, matches_per_day=1, slot_times=None, venues=None):
    """
    Generates the Knockout Stage from Qualified Teams:
    1. Validates that group stage is completed and qualified teams are identified.
    2. Pairs teams smartly to avoid pairing teams from the same group in Round 1
       (e.g., 1st Group A vs 2nd Group B, 1st Group B vs 2nd Group A, etc.).
    3. If total qualified teams is not a power of 2 (e.g., 6 or 12 teams):
       Uses Futbolix's distributed BYE system (`plan_knockout_byes`) with top seeds receiving BYEs!
    4. Connects seamlessly with `advance_knockout_bracket` and marks `knockout_generated = True`.
    """
    if getattr(competition, 'knockout_generated', False):
        return {'success': False, 'error': "Knockout stage has already been generated for this tournament."}
    if competition.is_completed and competition.matches.filter(group__isnull=True, status=MatchStatus.COMPLETED).exists():
        return {'success': False, 'error': "This tournament and its knockout stage are already completed."}
    if competition.status == CompetitionStatus.COMPLETED and not getattr(competition, 'knockout_generated', False):
        competition.status = CompetitionStatus.ACTIVE
        competition.save(update_fields=['status'])
    # Verify/update qualified teams
    q_result = update_qualified_teams(competition)
    if not q_result.get('success'):
        return q_result

    qualified_teams = list(competition.qualified_teams.select_related('team', 'group').order_by('rank_in_group', 'group__name'))
    n = len(qualified_teams)
    if n < 2:
        return {'success': False, 'error': f"Need at least 2 qualified teams to generate knockout stage (found {n})."}

    # Determine start date (subsequent to last group match)
    last_group_match = competition.matches.filter(group__isnull=False).order_by('-match_date').first()
    if last_group_match and last_group_match.match_date:
        default_ko_start = last_group_match.match_date + timedelta(days=7)
    else:
        default_ko_start = competition.start_date or date.today()

    start_date = start_date or default_ko_start
    if preferred_weekdays is None:
        preferred_weekdays = [5, 6]  # Saturday, Sunday

    matches_per_day = max(1, int(matches_per_day or 1))
    if slot_times is None:
        slot_times = [time(15, 0), time(17, 30)]
    slot_times = slot_times[:matches_per_day]

    if venues is None or len(venues) == 0:
        team_venues = [qt.team.home_venue for qt in qualified_teams if getattr(qt.team, 'home_venue', '')]
        venues = list(dict.fromkeys(team_venues + DEFAULT_VENUES))[:6]

    booked_slots = set()
    created_matches = []

    with transaction.atomic():
        # Clear previously scheduled knockout matches
        competition.matches.filter(group__isnull=True, status=MatchStatus.SCHEDULED).delete()

        # Seed arrangement preventing same-group matchups in Round 1
        # Organize seeds by group: { 'Group A': [Rank 1, Rank 2...], 'Group B': ... }
        by_group = {}
        for qt in qualified_teams:
            by_group.setdefault(qt.group.name, []).append(qt.team)

        group_names = sorted(list(by_group.keys()))
        num_groups = len(group_names)
        q_per_group = competition.qualifiers_per_group or 2

        # Build cross-group seeded order
        seeded_teams = []
        if num_groups == 2 and q_per_group == 2:
            # 4 teams: A1 vs B2, B1 vs A2
            seeded_teams = [
                by_group['Group A'][0], # Seed 1
                by_group['Group B'][1], # Seed 4
                by_group['Group B'][0], # Seed 2
                by_group['Group A'][1], # Seed 3
            ]
        elif num_groups == 4 and q_per_group == 2:
            # 8 teams: QF1: A1 vs B2, QF2: C1 vs D2, QF3: B1 vs A2, QF4: D1 vs C2
            seeded_teams = [
                by_group['Group A'][0], by_group['Group B'][1],
                by_group['Group C'][0], by_group['Group D'][1],
                by_group['Group B'][0], by_group['Group A'][1],
                by_group['Group D'][0], by_group['Group C'][1],
            ]
        elif num_groups == 4 and q_per_group == 1:
            # 4 teams: A1 vs B1, C1 vs D1
            seeded_teams = [
                by_group['Group A'][0], by_group['Group B'][0],
                by_group['Group C'][0], by_group['Group D'][0],
            ]
        elif num_groups == 2 and q_per_group == 1:
            # 2 teams: A1 vs B1
            seeded_teams = [
                by_group['Group A'][0], by_group['Group B'][0]
            ]
        else:
            # General cross-group pairing: Top seeds vs Bottom seeds from different groups
            top_seeds = [qt.team for qt in qualified_teams if qt.rank_in_group == 1]
            other_seeds = [qt.team for qt in qualified_teams if qt.rank_in_group > 1]
            
            # Rotate other_seeds so they don't face same group
            if other_seeds:
                # Reverse or rotate to pair Group A winner with Group B/C/D runner-up
                rotated_other = other_seeds[::-1]
                seeded_teams = []
                for idx in range(max(len(top_seeds), len(rotated_other))):
                    if idx < len(top_seeds):
                        seeded_teams.append(top_seeds[idx])
                    if idx < len(rotated_other):
                        seeded_teams.append(rotated_other[idx])
            else:
                seeded_teams = [qt.team for qt in qualified_teams]

        # Check if n is a power of 2
        is_power_of_2 = (n > 0) and (n & (n - 1)) == 0
        cur_date = _find_next_preferred_date(start_date, preferred_weekdays)

        if is_power_of_2:
            # Standard single elimination bracket
            # n=2 -> Final, n=4 -> Semi-Finals + Final, n=8 -> QF + SF + Final, etc.
            round_matches_count = n // 2
            current_round_teams = seeded_teams
            stage_idx = 1

            while round_matches_count >= 1:
                if round_matches_count == 1:
                    round_name = "Grand Championship Final"
                elif round_matches_count == 2:
                    round_name = "Semi-Finals"
                elif round_matches_count == 4:
                    round_name = "Quarter-Finals"
                elif round_matches_count == 8:
                    round_name = "Round of 16"
                else:
                    round_name = f"Knockout Round of {round_matches_count * 2}"

                daily_count = 0
                next_stage_placeholders = []

                for m_idx in range(round_matches_count):
                    if daily_count >= matches_per_day:
                        cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays)
                        daily_count = 0

                    if stage_idx == 1:
                        home_t = current_round_teams[m_idx * 2]
                        away_t = current_round_teams[m_idx * 2 + 1]
                        ph_home = ""
                        ph_away = ""
                    else:
                        home_t = None
                        away_t = None
                        prev_round_name = "Semi-Final" if round_matches_count == 1 else "Quarter-Final"
                        ph_home = f"Winner of {prev_round_name} {m_idx * 2 + 1}"
                        ph_away = f"Winner of {prev_round_name} {m_idx * 2 + 2}"

                    desired_time = slot_times[daily_count % len(slot_times)]
                    desired_venue = getattr(home_t, 'home_venue', '') or venues[daily_count % len(venues)]
                    m_date, k_time, v_name = _allocate_conflict_free_slot(
                        cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                        preferred_weekdays=preferred_weekdays
                    )

                    match = Match.objects.create(
                        competition=competition,
                        group=None,
                        tournament_round=round_name,
                        round_number=100 + stage_idx,
                        home_team=home_t,
                        away_team=away_t,
                        placeholder_home=ph_home,
                        placeholder_away=ph_away,
                        match_date=m_date,
                        kickoff_time=k_time,
                        venue=v_name,
                        status=MatchStatus.SCHEDULED
                    )
                    created_matches.append(match)
                    daily_count += 1

                round_matches_count //= 2
                stage_idx += 1
                cur_date = _find_next_preferred_date(cur_date + timedelta(days=7), preferred_weekdays)

        else:
            # Distributed BYE system for non-power-of-2 (e.g. 6 or 12 qualified teams)
            plan = plan_knockout_byes(n)
            stage_names = get_knockout_stage_names(n, plan)
            
            # Round 1:
            r1_info = plan[0]
            r1_byes_count = r1_info['byes']
            r1_matches_count = r1_info['matches']

            # Top seeds receive BYEs
            bye_teams = seeded_teams[:r1_byes_count]
            r1_playing_teams = seeded_teams[r1_byes_count:]

            daily_count = 0
            r1_name = stage_names[0]
            for m_idx in range(r1_matches_count):
                if daily_count >= matches_per_day:
                    cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays)
                    daily_count = 0

                home_t = r1_playing_teams[m_idx * 2]
                away_t = r1_playing_teams[m_idx * 2 + 1]

                desired_time = slot_times[daily_count % len(slot_times)]
                desired_venue = getattr(home_t, 'home_venue', '') or venues[daily_count % len(venues)]
                m_date, k_time, v_name = _allocate_conflict_free_slot(
                    cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays
                )

                match = Match.objects.create(
                    competition=competition,
                    group=None,
                    tournament_round=r1_name,
                    round_number=101,
                    home_team=home_t,
                    away_team=away_t,
                    match_date=m_date,
                    kickoff_time=k_time,
                    venue=v_name,
                    status=MatchStatus.SCHEDULED
                )
                created_matches.append(match)
                daily_count += 1

            # Subsequent rounds generated with placeholder pairings and BYE team integration
            cur_date = _find_next_preferred_date(cur_date + timedelta(days=7), preferred_weekdays)
            for stage_idx in range(1, len(plan)):
                st_info = plan[stage_idx]
                st_name = stage_names[stage_idx]
                st_matches = st_info['matches']
                daily_count = 0

                for m_idx in range(st_matches):
                    if daily_count >= matches_per_day:
                        cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays)
                        daily_count = 0

                    # For Round 2, if bye teams exist, integrate them as home teams!
                    home_t = None
                    ph_home = ""
                    if stage_idx == 1 and m_idx < len(bye_teams):
                        home_t = bye_teams[m_idx]
                    else:
                        prev_st_name = stage_names[stage_idx - 1]
                        ph_home = f"Winner of {prev_st_name} {m_idx * 2 + 1}"

                    ph_away = f"Winner of {stage_names[stage_idx - 1]} {m_idx + 1}" if stage_idx == 1 and m_idx < len(bye_teams) else f"Winner of {stage_names[stage_idx - 1]} {m_idx * 2 + 2}"

                    desired_time = slot_times[daily_count % len(slot_times)]
                    desired_venue = getattr(home_t, 'home_venue', '') or venues[daily_count % len(venues)]
                    m_date, k_time, v_name = _allocate_conflict_free_slot(
                        cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                        preferred_weekdays=preferred_weekdays
                    )

                    match = Match.objects.create(
                        competition=competition,
                        group=None,
                        tournament_round=st_name,
                        round_number=101 + stage_idx,
                        home_team=home_t,
                        away_team=None,
                        placeholder_home=ph_home,
                        placeholder_away=ph_away,
                        match_date=m_date,
                        kickoff_time=k_time,
                        venue=v_name,
                        status=MatchStatus.SCHEDULED
                    )
                    created_matches.append(match)
                    daily_count += 1

                cur_date = _find_next_preferred_date(cur_date + timedelta(days=7), preferred_weekdays)

        competition.knockout_generated = True
        competition.save(update_fields=['knockout_generated'])

    return {
        'success': True,
        'knockout_matches_count': len(created_matches),
        'matches': created_matches
    }
