"""
Fixtures application services - Streamlined Fixture Scheduling & Generation Engine for Futbolix.
Automatically includes all league teams, divides groups equally, and schedules fixtures
by user-specified matches per day and daily slot kickoff times.
"""
from datetime import timedelta, date, time, datetime
import json
import math
from collections import Counter, defaultdict
from django.db import transaction
from matches.models import Match, MatchStatus
from fixtures.models import ScheduleGenerationLog
from leagues.models import Competition, TournamentGroup, CompetitionTeam, TournamentFormat, CompetitionStatus
from teams.models import Team
from fixtures.scheduling_engine import (
    generate_league_pairings,
    generate_available_dates,
    optimize_schedule_distribution,
    validate_complete_schedule,
)

DEFAULT_VENUES = [
    "Central Stadium", "Metropolis Arena", "Riverside Sports Complex",
    "Emirates Field", "Olympia Park Pitch 1", "St. Jude Ground"
]

DEFAULT_KICKOFF_TIMES = ["14:00", "16:30", "19:00"]

SLOT_PRESETS = {
    1: ["15:00"],
    2: ["15:00", "17:30"],
    3: ["14:00", "16:30", "19:00"],
    4: ["11:00", "13:30", "16:00", "18:30"],
    5: ["10:00", "12:15", "14:30", "16:45", "19:00"],
    6: ["09:30", "11:30", "13:30", "15:30", "17:30", "19:30"],
}

WEEKDAY_MAP = {
    'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
    'Friday': 4, 'Saturday': 5, 'Sunday': 6
}


def parse_date_safe(val, default_date=None):
    if not val:
        return default_date or date.today()
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val).strip(), '%Y-%m-%d').date()
    except Exception:
        return default_date or date.today()


def parse_time_safe(val, default_time=time(15, 0)):
    if not val:
        return default_time
    if isinstance(val, time):
        return val
    try:
        parts = str(val).strip().split(':')
        return time(int(parts[0]), int(parts[1]))
    except Exception:
        return default_time


def calculate_required_matches(
    teams_count,
    format_type,
    num_groups=1,
    qualifiers_per_group=2,
    is_double_round=False,
    knockout_legs='single',
    knockout_system='single_elimination',
    group_team_counts=None,
    has_third_place=False,
    matches_per_day=1,
    sf_preference='same_day',
    scheduling_strategy='optimized'
):
    """
    Pure calculation function: Computes the exact number of required fixtures and rounds
    based on the tournament format, team counts, group structure, and knockout rules.
    Also calculates realistic minimum stage days considering matches per day, team rest,
    scheduling strategy (sequential matchweeks vs optimized date distribution),
    and stage separation (e.g. semi-finals, and showcase grand final).
    Does not assign dates or write to database.
    """
    if teams_count < 2:
        return {
            'total_matches': 0,
            'group_stage_matches': 0,
            'knockout_matches': 0,
            'total_rounds': 0,
            'group_rounds': 0,
            'knockout_rounds': 0,
            'min_stage_days': 0,
            'group_days': 0,
            'ko_days': 0
        }

    is_double_leg = (knockout_legs == 'double')
    mpd = max(1, int(matches_per_day or 1))

    if format_type in [TournamentFormat.ROUND_ROBIN, 'ROUND_ROBIN']:
        matches = teams_count * (teams_count - 1)
        if not is_double_round:
            matches //= 2
        rounds = (teams_count - 1) if teams_count % 2 == 0 else teams_count
        if is_double_round:
            rounds *= 2

        if scheduling_strategy == 'sequential':
            matches_per_round = teams_count // 2
            days_per_round = math.ceil(matches_per_round / mpd)
            min_stage_days = rounds * days_per_round
        else:
            min_stage_days = math.ceil(matches / mpd)

        return {
            'total_matches': matches,
            'group_stage_matches': matches,
            'knockout_matches': 0,
            'total_rounds': rounds,
            'group_rounds': rounds,
            'knockout_rounds': 0,
            'min_stage_days': min_stage_days,
            'group_days': min_stage_days,
            'ko_days': 0
        }

    elif format_type in [TournamentFormat.PAGE_MCINTYRE, 'PAGE_MCINTYRE'] or (format_type in [TournamentFormat.SINGLE_ELIMINATION, 'KNOCKOUT'] and knockout_system == 'page_mcintyre'):
        return {
            'total_matches': 4,
            'group_stage_matches': 0,
            'knockout_matches': 4,
            'total_rounds': 4,
            'group_rounds': 0,
            'knockout_rounds': 4,
            'min_stage_days': 4,
            'group_days': 0,
            'ko_days': 4
        }

    elif format_type in [TournamentFormat.GROUP_KNOCKOUT, 'GROUP_KNOCKOUT', TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT']:
        is_league_knockout = (format_type in [TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT'])
        actual_num_groups = 1 if is_league_knockout else max(1, int(num_groups or 2))

        # Calculate group stage matches based on group allocations
        if not group_team_counts:
            base = teams_count // actual_num_groups
            rem = teams_count % actual_num_groups
            group_team_counts = [base + (1 if i < rem else 0) for i in range(actual_num_groups)]
            group_team_counts = [c for c in group_team_counts if c > 0]

        group_matches = 0
        max_group_rounds = 0
        for cnt in group_team_counts:
            if cnt >= 2:
                g_m = cnt * (cnt - 1)
                if not is_double_round:
                    g_m //= 2
                group_matches += g_m
                g_r = (cnt - 1) if cnt % 2 == 0 else cnt
                if is_double_round:
                    g_r *= 2
                if g_r > max_group_rounds:
                    max_group_rounds = g_r

        if scheduling_strategy == 'sequential':
            matches_per_round = sum(cnt // 2 for cnt in group_team_counts)
            days_per_round = math.ceil(matches_per_round / mpd)
            group_days = max_group_rounds * days_per_round
        else:
            group_days = math.ceil(group_matches / mpd)

        # Calculate knockout stage matches based on qualification rules
        default_q = 4 if is_league_knockout else 2
        actual_q_per_group = int(qualifiers_per_group or default_q)
        max_teams_in_group = max(group_team_counts, default=1)
        actual_q_per_group = min(actual_q_per_group, max_teams_in_group)
        total_qualifiers = actual_num_groups * actual_q_per_group

        if total_qualifiers <= 1:
            ko_matches = 0
            ko_rounds = 0
            ko_days = 0
        elif total_qualifiers == 2:
            ko_matches = 1
            ko_rounds = 1
            ko_days = 1
        elif knockout_system == 'page_mcintyre':
            ko_matches = 4
            ko_rounds = 4
            ko_days = 4
        else:
            if is_double_leg:
                ko_matches = (total_qualifiers - 2) * 2 + 1
            else:
                ko_matches = total_qualifiers - 1
            if has_third_place:
                ko_matches += 1

            ko_rounds = 0
            k = 1
            while k < total_qualifiers:
                k *= 2
                ko_rounds += 1
            if is_double_leg:
                ko_rounds = (ko_rounds - 1) * 2 + 1

            sf_days = 1 if (sf_preference == 'same_day' and mpd >= 2) else 2
            if total_qualifiers <= 4:
                ko_days = (sf_days * 2 + 1) if is_double_leg else (sf_days + 1)
            else:
                qf_days = math.ceil(4 / mpd)
                ko_days = (qf_days * 2 + sf_days * 2 + 1) if is_double_leg else (qf_days + sf_days + 1)

        total_matches = group_matches + ko_matches
        total_rounds = max_group_rounds + ko_rounds
        min_stage_days = group_days + ko_days

        return {
            'total_matches': total_matches,
            'group_stage_matches': group_matches,
            'knockout_matches': ko_matches,
            'total_rounds': total_rounds,
            'group_rounds': max_group_rounds,
            'knockout_rounds': ko_rounds,
            'min_stage_days': min_stage_days,
            'group_days': group_days,
            'ko_days': ko_days
        }

    elif format_type in [TournamentFormat.SINGLE_ELIMINATION, 'KNOCKOUT']:
        if knockout_system == 'page_mcintyre':
            return {
                'total_matches': 4,
                'group_stage_matches': 0,
                'knockout_matches': 4,
                'total_rounds': 4,
                'group_rounds': 0,
                'knockout_rounds': 4,
                'min_stage_days': 4,
                'group_days': 0,
                'ko_days': 4
            }
        else:
            if is_double_leg:
                ko_matches = (teams_count - 2) * 2 + 1
            else:
                ko_matches = teams_count - 1
            if has_third_place:
                ko_matches += 1

            ko_rounds = 0
            k = 1
            while k < teams_count:
                k *= 2
                ko_rounds += 1
            if is_double_leg:
                ko_rounds = (ko_rounds - 1) * 2 + 1

            sf_days = 1 if (sf_preference == 'same_day' and mpd >= 2) else 2
            if teams_count <= 2:
                ko_days = 1
            elif teams_count <= 4:
                ko_days = (sf_days * 2 + 1) if is_double_leg else (sf_days + 1)
            else:
                qf_days = math.ceil(4 / mpd)
                ko_days = (qf_days * 2 + sf_days * 2 + 1) if is_double_leg else (qf_days + sf_days + 1)

            return {
                'total_matches': ko_matches,
                'group_stage_matches': 0,
                'knockout_matches': ko_matches,
                'total_rounds': ko_rounds,
                'group_rounds': 0,
                'knockout_rounds': ko_rounds,
                'min_stage_days': ko_days,
                'group_days': 0,
                'ko_days': ko_days
            }

    return {
        'total_matches': 0,
        'group_stage_matches': 0,
        'knockout_matches': 0,
        'total_rounds': 0,
        'group_rounds': 0,
        'knockout_rounds': 0,
        'min_stage_days': 0
    }


def calculate_scheduling_capacity(
    start_date,
    end_date,
    preferred_weekdays,
    matches_per_day,
    total_matches,
    min_stage_days=1,
    stage_details=None,
    excluded_dates=None,
    min_rest_days=0,
    venues_count=None,
    slots_count=None
):
    """
    Computes scheduling capacity between start_date and end_date.
    Determines available match dates (excluding organizer-excluded dates),
    volume capacity, stage requirements, venue/kickoff slot capacity,
    and team rest-day span requirements.
    """
    if not end_date:
        return {
            'is_feasible': True,
            'available_calendar_days': None,
            'available_match_days': None,
            'required_match_days': math.ceil(total_matches / max(1, matches_per_day)),
            'max_capacity': None,
            'days_short': 0,
            'min_matches_per_day_needed': matches_per_day,
            'suggested_end_date': None,
            'errors': []
        }

    calendar_days = max(1, (end_date - start_date).days + 1)
    excl_set = set(excluded_dates or [])

    # Collect all available match dates that match preferred weekdays and are not excluded
    available_dates = generate_available_dates(
        start_date=start_date,
        end_date=end_date,
        preferred_weekdays=preferred_weekdays,
        excluded_dates=excl_set
    )

    available_match_days = len(available_dates)
    effective_mpd = matches_per_day
    if venues_count is not None and slots_count is not None:
        slot_cap = max(1, venues_count) * max(1, slots_count)
        effective_mpd = min(matches_per_day, slot_cap)

    max_capacity = available_match_days * effective_mpd
    min_days_volume = math.ceil(total_matches / max(1, effective_mpd))
    required_match_days = max(min_days_volume, min_stage_days)

    is_feasible = (available_match_days >= required_match_days) and (max_capacity >= total_matches)

    errors = []
    days_short = 0
    min_mpd_needed = matches_per_day
    suggested_end_date = None

    if not is_feasible:
        days_short = max(0, required_match_days - available_match_days)
        min_mpd_needed = math.ceil(total_matches / max(1, available_match_days)) if available_match_days > 0 else total_matches

        # Calculate suggested end date providing required_match_days
        sug_dates = generate_available_dates(
            start_date=start_date,
            end_date=None,
            preferred_weekdays=preferred_weekdays,
            excluded_dates=excl_set,
            min_needed=required_match_days
        )
        suggested_end_date = sug_dates[-1] if len(sug_dates) >= required_match_days else None

        approx_calendar_days = (suggested_end_date - end_date).days if suggested_end_date and suggested_end_date > end_date else days_short * 7

        errors.append(
            f"The selected date range ({start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')}) provides {available_match_days} available match day(s), which is insufficient for {total_matches} required matches at {matches_per_day} match(es) per day."
        )
        if stage_details and (stage_details.get('group_days') or stage_details.get('ko_days')):
            g_d = stage_details.get('group_days', 0)
            k_d = stage_details.get('ko_days', 0)
            g_r = stage_details.get('group_rounds', 0)
            errors.append(
                f"Tournament Stage Breakdown: {g_r} group matchweeks require {g_d} match day(s) at {matches_per_day} match(es)/day, followed by {k_d} dedicated day(s) for knockout stages (Semi-Finals & Championship Final)."
            )
        if min_rest_days > 0:
            errors.append(
                f"Active Team Rest Constraint: Minimum {min_rest_days} rest day(s) required between matches for each team."
            )
        errors.append(
            f"Minimum required match days: {required_match_days} day(s) (short by {days_short} match day(s))."
        )
        if suggested_end_date:
            errors.append(
                f"Recommendation: Extend Fixture End Date to at least {suggested_end_date.strftime('%d-%m-%Y')} (+{approx_calendar_days} calendar days), or increase daily match limit to at least {min_mpd_needed} matches per day."
            )

    return {
        'is_feasible': is_feasible,
        'available_calendar_days': calendar_days,
        'available_match_days': available_match_days,
        'required_match_days': required_match_days,
        'max_capacity': max_capacity,
        'days_short': days_short,
        'min_matches_per_day_needed': min_mpd_needed,
        'suggested_end_date': suggested_end_date.strftime('%Y-%m-%d') if suggested_end_date else None,
        'errors': errors
    }


def generate_round_robin_fixtures(competition, start_date=None, double_round=False, matches_per_day=1):
    """
    Standard round-robin generator wrapper.
    """
    config = {
        'tournament_format': TournamentFormat.ROUND_ROBIN,
        'start_date': start_date or competition.start_date or date.today(),
        'round_robin_type': 'double' if double_round else 'single',
        'matches_per_day': matches_per_day,
        'daily_kickoff_times': ["15:00"],
        'preferred_days': ['Saturday', 'Sunday'],
    }
    res = generate_smart_fixtures(competition, config)
    if res.get('success'):
        return commit_generated_fixtures(competition, res['matches'])
    return []


def generate_smart_fixtures(competition, config):
    """
    Streamlined scheduling engine:
    1. Uses all registered league teams automatically (no manual selection required).
    2. Evenly divides teams among groups for Group Stage.
    3. Schedules by daily match capacity and user-input kickoff times.
    """
    if competition.is_completed:
        return {'success': False, 'errors': ["This competition is already completed. Fixtures cannot be generated."]}
    format_type = config.get('tournament_format', TournamentFormat.ROUND_ROBIN)
    tournament_type = config.get('tournament_type') or config.get('knockout_system', 'single_elimination')
    knockout_system = tournament_type
    knockout_legs = config.get('knockout_legs', 'single')
    two_legged_ko = (knockout_legs == 'double') or (config.get('round_robin_type') == 'double' and 'knockout_legs' not in config)

    # Automatically use all registered teams in competition
    selected_team_ids = config.get('selected_team_ids')
    if selected_team_ids:
        teams_qs = list(Team.objects.filter(id__in=selected_team_ids))
    else:
        teams_qs = list(competition.teams.all())

    if len(teams_qs) < 2:
        return {
            'success': False,
            'errors': ["At least 2 teams are required in this league to generate fixtures."],
            'matches': [],
            'summary': {}
        }

    # Scheduling settings
    start_date = parse_date_safe(config.get('start_date'), competition.start_date or (date.today() + timedelta(days=7)))
    end_date_raw = config.get('end_date')
    end_date = parse_date_safe(end_date_raw) if end_date_raw else None

    if end_date and end_date < start_date:
        return {
            'success': False,
            'errors': ["Fixture End Date cannot be earlier than the Start Date."],
            'matches': [],
            'summary': {}
        }

    preferred_days = config.get('preferred_days', ['Saturday', 'Sunday'])
    preferred_weekdays = [WEEKDAY_MAP[d] for d in preferred_days if d in WEEKDAY_MAP]
    if not preferred_weekdays:
        preferred_weekdays = [5, 6]  # Saturday & Sunday

    # Matches per day & slot times
    matches_per_day = int(config.get('matches_per_day', 1) or 1)
    raw_slot_times = config.get('daily_kickoff_times', [])
    if not raw_slot_times:
        raw_slot_times = SLOT_PRESETS.get(matches_per_day, [f"{12 + i * 2}:00" for i in range(matches_per_day)])

    # Ensure slot times list matches matches_per_day count
    while len(raw_slot_times) < matches_per_day:
        last_t = raw_slot_times[-1] if raw_slot_times else "15:00"
        h = int(last_t.split(':')[0]) + 2
        raw_slot_times.append(f"{min(h, 22):02d}:00")
    slot_times = [parse_time_safe(t) for t in raw_slot_times[:matches_per_day]]

    venues = config.get('venues', [])
    if not venues:
        team_venues = [getattr(t, 'home_venue', '') for t in teams_qs if getattr(t, 'home_venue', '')]
        venues = list(dict.fromkeys(team_venues + DEFAULT_VENUES))[:6]

    round_robin_type = config.get('round_robin_type', 'single')  # 'single' or 'double'
    sf_preference = config.get('sf_preference', 'same_day')  # 'same_day' or 'separate_days'
    scheduling_strategy = config.get('scheduling_strategy', 'optimized')  # 'optimized' or 'sequential'
    min_rest_days = int(config.get('min_rest_days', 0) or 0)

    raw_excluded = config.get('excluded_dates', [])
    if isinstance(raw_excluded, str):
        raw_excluded = [s.strip() for s in raw_excluded.split(',') if s.strip()]
    excluded_dates = [d for d in (parse_date_safe(x) for x in raw_excluded) if d is not None]

    team_unavail_raw = config.get('team_unavailable_dates', {}) or {}
    team_unavailable_dates = {}
    for tid_key, d_list in team_unavail_raw.items():
        try:
            tid_int = int(tid_key)
            parsed_set = {d for d in (parse_date_safe(x) for x in d_list) if d is not None}
            if parsed_set:
                team_unavailable_dates[tid_int] = parsed_set
        except Exception:
            continue

    # Load existing locked or completed/live matches to prevent scheduling conflicts on regeneration
    respect_locked = config.get('respect_locked_matches', True)
    locked_matches = []
    if respect_locked:
        existing_locked = competition.matches.filter(
            status__in=[MatchStatus.COMPLETED, MatchStatus.LIVE]
        ) | competition.matches.filter(is_locked=True)
        for lm in existing_locked.distinct():
            locked_matches.append({
                'id': lm.id,
                'match_date': lm.match_date,
                'kickoff_time': lm.kickoff_time,
                'venue': lm.venue,
                'home_team_id': lm.home_team_id,
                'away_team_id': lm.away_team_id,
                'leg': lm.leg,
            })

    # Determine groups structure if applicable
    groups_info = {}
    groups_dict = {}
    group_team_counts = None

    if format_type in [TournamentFormat.GROUP_KNOCKOUT, 'GROUP_KNOCKOUT', TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT']:
        is_league_knockout = (format_type in [TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT'])
        num_groups = 1 if is_league_knockout else int(config.get('num_groups', 2) or 2)
        default_q = 4 if is_league_knockout else 2
        q_per_group = int(config.get('qualifiers_per_group', default_q) or default_q)

        # Check if competition already has established group assignments for teams
        existing_comp_teams = competition.competitionteam_set.filter(group__isnull=False).select_related('team', 'group')
        existing_groups_map = {}
        for ct in existing_comp_teams:
            if ct.group and ct.team in teams_qs:
                existing_groups_map.setdefault(ct.group.name, []).append(ct.team)

        if existing_groups_map and len(existing_groups_map) == num_groups and not is_league_knockout and sum(len(tl) for tl in existing_groups_map.values()) == len(teams_qs):
            groups_dict = existing_groups_map
        else:
            groups_dict = _allocate_groups_equally(teams_qs, num_groups)

        groups_info = {
            g_name: [{'id': t.id, 'name': t.name, 'short_name': t.short_name, 'logo_url': t.get_logo_url()} for t in t_list]
            for g_name, t_list in groups_dict.items()
        }
        group_team_counts = [len(tl) for tl in groups_dict.values()]
    else:
        num_groups = 1
        q_per_group = 2

    # Step 1: Automatically calculate required matches based on tournament format & rules
    match_calc = calculate_required_matches(
        teams_count=len(teams_qs),
        format_type=format_type,
        num_groups=num_groups,
        qualifiers_per_group=q_per_group,
        is_double_round=(round_robin_type == 'double'),
        knockout_legs=knockout_legs,
        knockout_system=knockout_system,
        group_team_counts=group_team_counts,
        matches_per_day=matches_per_day,
        sf_preference=sf_preference,
        scheduling_strategy=scheduling_strategy
    )

    # Step 2: Calculate scheduling capacity and validate feasibility between start_date and end_date
    capacity = calculate_scheduling_capacity(
        start_date=start_date,
        end_date=end_date,
        preferred_weekdays=preferred_weekdays,
        matches_per_day=matches_per_day,
        total_matches=match_calc['total_matches'],
        min_stage_days=match_calc['min_stage_days'],
        stage_details=match_calc,
        excluded_dates=excluded_dates,
        min_rest_days=min_rest_days,
        venues_count=len(venues),
        slots_count=len(slot_times)
    )

    if end_date and not capacity['is_feasible']:
        return {
            'success': False,
            'is_feasible': False,
            'errors': capacity['errors'] or [
                f"Cannot schedule all fixtures between {start_date.strftime('%d-%m-%Y')} and {end_date.strftime('%d-%m-%Y')}.",
                f"This tournament wants {capacity['required_match_days']} match day(s), but the selected date range only provides {capacity['available_match_days']} preferred match day(s).",
                f"Please extend the Fixture End Date to at least {capacity['suggested_end_date']} or increase daily matches to {capacity['min_matches_per_day_needed']}."
            ],
            'capacity_details': capacity,
            'matches': [],
            'summary': {
                'total_matches': match_calc['total_matches'],
                'total_teams': len(teams_qs),
                'is_feasible': False,
                'days_wanted': capacity['required_match_days'],
                'available_match_days': capacity['available_match_days'],
                'suggested_end_date': capacity['suggested_end_date'],
                'matches_per_day': matches_per_day
            }
        }

    # Step 3: Dynamically distribute fixtures with global daily limit and team rest enforcement
    scheduled_matches = []
    booked_slots = set()
    global_daily_counts = Counter()
    teams_played_on_date = defaultdict(set)

    # Pre-seed booked_slots and daily counts with locked/completed matches
    for lm in locked_matches:
        d = lm['match_date']
        if d:
            global_daily_counts[d] += 1
            if lm.get('home_team_id'):
                teams_played_on_date[d].add(lm['home_team_id'])
            if lm.get('away_team_id'):
                teams_played_on_date[d].add(lm['away_team_id'])
            if lm.get('kickoff_time') and lm.get('venue'):
                booked_slots.add((d, lm['kickoff_time'], lm['venue']))

    solver_constraints = {
        'start_date': start_date,
        'end_date': end_date,
        'preferred_weekdays': preferred_weekdays,
        'excluded_dates': excluded_dates,
        'matches_per_day': matches_per_day,
        'min_rest_days': min_rest_days,
        'slot_times': slot_times,
        'venues': venues,
        'scheduling_strategy': scheduling_strategy,
        'team_unavailable_dates': team_unavailable_dates,
    }

    if format_type in [TournamentFormat.PAGE_MCINTYRE, 'PAGE_MCINTYRE'] or (format_type in [TournamentFormat.SINGLE_ELIMINATION, 'KNOCKOUT'] and knockout_system == 'page_mcintyre'):
        if len(teams_qs) < 4:
            return {
                'success': False,
                'is_feasible': False,
                'errors': [f"Page–McIntyre Playoff System requires at least 4 participating teams (found {len(teams_qs)}). Please register 4 teams to generate fixtures."],
                'matches': [],
                'summary': {}
            }
        knockout_matches = _generate_page_mcintyre_fixtures(
            teams=teams_qs[:4],
            start_date=start_date,
            preferred_weekdays=preferred_weekdays,
            slot_times=slot_times,
            venues=venues,
            end_date=end_date,
            booked_slots=booked_slots,
            matches_per_day=matches_per_day,
            global_daily_counts=global_daily_counts,
            teams_played_on_date=teams_played_on_date,
            sf_preference=sf_preference
        )
        scheduled_matches.extend(knockout_matches)

    elif format_type == TournamentFormat.ROUND_ROBIN or format_type == 'ROUND_ROBIN':
        pairings = generate_league_pairings({'': teams_qs}, is_double_round=(round_robin_type == 'double'))
        avail_dates = generate_available_dates(
            start_date=start_date,
            end_date=end_date,
            preferred_weekdays=preferred_weekdays,
            excluded_dates=excluded_dates,
            min_needed=max(len(pairings) * (min_rest_days + 1), 60)
        )
        opt_result, opt_info = optimize_schedule_distribution(
            pairings=pairings,
            available_dates=avail_dates,
            constraints=solver_constraints,
            locked_matches=locked_matches
        )
        if opt_result is None:
            return {
                'success': False,
                'is_feasible': False,
                'errors': [opt_info],
                'capacity_details': capacity,
                'matches': [],
                'summary': {
                    'total_matches': match_calc['total_matches'],
                    'total_teams': len(teams_qs),
                    'is_feasible': False,
                    'days_wanted': capacity['required_match_days'],
                    'available_match_days': capacity['available_match_days'],
                    'suggested_end_date': capacity['suggested_end_date'],
                    'matches_per_day': matches_per_day
                }
            }
        scheduled_matches = opt_result

    elif format_type in [TournamentFormat.GROUP_KNOCKOUT, 'GROUP_KNOCKOUT', TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT']:
        is_league_knockout = (format_type in [TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT'])
        total_qualifiers = num_groups * q_per_group
        use_page_mcintyre = (knockout_system == 'page_mcintyre')

        if use_page_mcintyre:
            ko_days_needed = 3
        elif total_qualifiers <= 2:
            ko_days_needed = 1
        elif total_qualifiers <= 4:
            sf_days = 1 if (sf_preference == 'same_day' and matches_per_day >= 2) else 2
            ko_days_needed = (sf_days * 2 + 1) if two_legged_ko else (sf_days + 1)
        else:
            sf_days = 1 if (sf_preference == 'same_day' and matches_per_day >= 2) else 2
            qf_days = math.ceil(4 / matches_per_day)
            ko_days_needed = (qf_days * 2 + sf_days * 2 + 1) if two_legged_ko else (qf_days + sf_days + 1)

        pairings = generate_league_pairings(groups_dict, is_double_round=(round_robin_type == 'double'))
        all_avail_dates = generate_available_dates(
            start_date=start_date,
            end_date=end_date,
            preferred_weekdays=preferred_weekdays,
            excluded_dates=excluded_dates,
            min_needed=max(len(pairings) * (min_rest_days + 1) + ko_days_needed, 60)
        )
        if end_date and len(all_avail_dates) > ko_days_needed:
            group_avail_dates = all_avail_dates[:-ko_days_needed]
        else:
            group_avail_dates = all_avail_dates

        group_matches, opt_info = optimize_schedule_distribution(
            pairings=pairings,
            available_dates=group_avail_dates,
            constraints=solver_constraints,
            locked_matches=locked_matches
        )
        if group_matches is None:
            return {
                'success': False,
                'is_feasible': False,
                'errors': [opt_info],
                'capacity_details': capacity,
                'matches': [],
                'summary': {
                    'total_matches': match_calc['total_matches'],
                    'total_teams': len(teams_qs),
                    'is_feasible': False,
                    'days_wanted': capacity['required_match_days'],
                    'available_match_days': capacity['available_match_days'],
                    'suggested_end_date': capacity['suggested_end_date'],
                    'matches_per_day': matches_per_day
                }
            }
        scheduled_matches.extend(group_matches)

        # Sync state for knockout phase
        for gm in group_matches:
            d = gm['match_date']
            global_daily_counts[d] += 1
            booked_slots.add((d, gm['kickoff_time'], gm['venue']))
            if getattr(gm.get('home_team'), 'id', None):
                teams_played_on_date[d].add(gm['home_team'].id)
            if getattr(gm.get('away_team'), 'id', None):
                teams_played_on_date[d].add(gm['away_team'].id)

        # Knockout Stage strictly follows the group stage (respecting min_rest_days)
        last_group_date = max([m['match_date'] for m in group_matches], default=start_date)
        ko_earliest = last_group_date + timedelta(days=max(1, min_rest_days + 1))
        ko_candidates = [d for d in all_avail_dates if d >= ko_earliest]
        knockout_start_date = ko_candidates[0] if ko_candidates else _find_next_preferred_date(ko_earliest, preferred_weekdays)

        if use_page_mcintyre:
            q_teams = [None, None, None, None]
            knockout_matches = _generate_page_mcintyre_fixtures(
                teams=q_teams,
                start_date=knockout_start_date,
                preferred_weekdays=preferred_weekdays,
                slot_times=slot_times,
                venues=venues,
                end_date=end_date,
                booked_slots=booked_slots,
                matches_per_day=matches_per_day,
                global_daily_counts=global_daily_counts,
                teams_played_on_date=teams_played_on_date,
                sf_preference=sf_preference
            )
            scheduled_matches.extend(knockout_matches)
        else:
            knockout_matches = _generate_knockout_stage_for_groups(
                groups_dict=groups_dict,
                start_date=knockout_start_date,
                preferred_weekdays=preferred_weekdays,
                slot_times=slot_times,
                venues=venues,
                qualifiers_per_group=q_per_group,
                two_legged=two_legged_ko,
                end_date=end_date,
                booked_slots=booked_slots,
                matches_per_day=matches_per_day,
                global_daily_counts=global_daily_counts,
                teams_played_on_date=teams_played_on_date,
                sf_preference=sf_preference
            )
            scheduled_matches.extend(knockout_matches)

    elif format_type == TournamentFormat.SINGLE_ELIMINATION or format_type == 'KNOCKOUT':
        knockout_matches = _generate_single_elimination_bracket(
            teams=teams_qs,
            start_date=start_date,
            preferred_weekdays=preferred_weekdays,
            slot_times=slot_times,
            venues=venues,
            two_legged=two_legged_ko,
            end_date=end_date,
            booked_slots=booked_slots,
            matches_per_day=matches_per_day,
            global_daily_counts=global_daily_counts,
            teams_played_on_date=teams_played_on_date,
            sf_preference=sf_preference
        )
        scheduled_matches.extend(knockout_matches)

    # Final validation: strictly ensure all generated matches fall between start_date and end_date
    if end_date:
        exceeded = [m for m in scheduled_matches if m['match_date'] > end_date]
        if exceeded:
            last_date = max(m['match_date'] for m in scheduled_matches)
            return {
                'success': False,
                'is_feasible': False,
                'errors': [
                    f"Selected end date {end_date.strftime('%d-%m-%Y')} cannot fit all {len(scheduled_matches)} matches between start date and end date.",
                    f"This tournament wants {capacity['required_match_days']} match day(s). The last match was scheduled on {last_date.strftime('%d-%m-%Y')}.",
                    f"Please extend the Fixture End Date to at least {last_date.strftime('%d-%m-%Y')}."
                ],
                'capacity_details': capacity,
                'matches': [],
                'summary': {
                    'days_wanted': capacity['required_match_days'],
                    'available_match_days': capacity['available_match_days'],
                    'suggested_end_date': last_date.strftime('%Y-%m-%d')
                }
            }

    # Summary
    total_matches = len(scheduled_matches)
    total_rounds = len(set(m['round_name'] for m in scheduled_matches))
    all_dates = [m['match_date'] for m in scheduled_matches]
    first_date = min(all_dates, default=start_date)
    final_date = max(all_dates, default=start_date)

    if format_type in [TournamentFormat.ROUND_ROBIN, 'ROUND_ROBIN']:
        fmt_label = "Round Robin (Double Round)" if round_robin_type == 'double' else "Round Robin (League)"
    elif format_type in [TournamentFormat.PAGE_MCINTYRE, 'PAGE_MCINTYRE']:
        fmt_label = "Page–McIntyre System"
    else:
        ko_type_label = "Page–McIntyre System" if knockout_system == 'page_mcintyre' else ("Single-Elimination (Double Leg)" if two_legged_ko else "Single-Elimination (Single Leg)")
        if format_type in [TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT']:
            fmt_label = f"League + Tournament ({ko_type_label})"
        elif format_type in [TournamentFormat.GROUP_KNOCKOUT, 'GROUP_KNOCKOUT']:
            fmt_label = f"Group Mode + Tournament ({ko_type_label})"
        elif format_type in [TournamentFormat.SINGLE_ELIMINATION, 'KNOCKOUT']:
            fmt_label = f"Tournament / Knockout ({ko_type_label})"
        else:
            fmt_label = dict(TournamentFormat.choices).get(format_type, format_type)

    summary = {
        'total_matches': total_matches,
        'total_rounds': total_rounds,
        'total_teams': len(teams_qs),
        'start_date': first_date.isoformat() if isinstance(first_date, date) else str(first_date),
        'end_date': final_date.isoformat() if isinstance(final_date, date) else str(final_date),
        'days_wanted': capacity['required_match_days'],
        'dates_used': len(set(all_dates)),
        'format_name': fmt_label,
        'matches_per_day': matches_per_day,
        'min_rest_days': min_rest_days,
        'scheduling_strategy': scheduling_strategy,
        'group_count': len(groups_info) if groups_info else 0,
        'venues_used': len(set(m['venue'] for m in scheduled_matches)),
        'byes_by_round': {m['round_name']: m['round_byes'] for m in scheduled_matches if m.get('round_byes')},
        'available_match_days': capacity['available_match_days'],
        'required_match_days': capacity['required_match_days'],
        'is_feasible': True,
        'group_stage_matches': match_calc['group_stage_matches'],
        'knockout_matches': match_calc['knockout_matches'],
        'capacity_details': capacity,
    }

    formatted_matches = []
    for idx, m in enumerate(scheduled_matches, 1):
        h_id = _extract_team_val(m.get('home_team'), 'id', m.get('home_team_id'))
        h_name = _extract_team_val(m.get('home_team'), 'name', m.get('home_team_name', 'TBD'))
        h_short = _extract_team_val(m.get('home_team'), 'short_name', m.get('home_team_short', 'TBD'))
        h_logo = _extract_team_val(m.get('home_team'), 'get_logo_url', '') or ''

        a_id = _extract_team_val(m.get('away_team'), 'id', m.get('away_team_id'))
        a_name = _extract_team_val(m.get('away_team'), 'name', m.get('away_team_name', 'TBD'))
        a_short = _extract_team_val(m.get('away_team'), 'short_name', m.get('away_team_short', 'TBD'))
        a_logo = _extract_team_val(m.get('away_team'), 'get_logo_url', '') or ''

        formatted_matches.append({
            'temp_id': f"match_{idx}",
            'stage_name': m.get('stage_name', 'League Stage'),
            'round_name': m['round_name'],
            'round_number': m.get('round_number', 1),
            'leg': m.get('leg', 1),
            'group_name': m.get('group_name', ''),
            'home_team_id': h_id,
            'home_team_name': h_name,
            'home_team_short': h_short,
            'home_team_logo': h_logo,
            'away_team_id': a_id,
            'away_team_name': a_name,
            'away_team_short': a_short,
            'away_team_logo': a_logo,
            'match_date': m['match_date'].isoformat() if isinstance(m['match_date'], date) else str(m['match_date']),
            'kickoff_time': m['kickoff_time'].strftime('%H:%M') if isinstance(m['kickoff_time'], time) else str(m['kickoff_time'])[:5],
            'venue': m['venue'],
            'is_knockout': m.get('is_knockout', False),
            'is_locked': False,
            'round_byes': m.get('round_byes', [])
        })

    validation_report = validate_complete_schedule(formatted_matches, solver_constraints, locked_matches=locked_matches)
    per_match_status = validation_report.get('per_match_status', {})
    for fm in formatted_matches:
        st = per_match_status.get(fm['temp_id'], {'valid': True, 'messages': []})
        fm['is_valid'] = st['valid']
        fm['validation_messages'] = st['messages']

    return {
        'success': True,
        'is_feasible': True,
        'summary': summary,
        'groups': groups_info,
        'matches': formatted_matches,
        'capacity_details': capacity,
        'validation': validation_report,
        'errors': validation_report['errors'] if not validation_report['is_valid'] else []
    }


def _build_round_robin_rounds(teams, double_round=False, prefix=""):
    """
    Berger table circle rotation round-robin pairing algorithm.
    """
    n = len(teams)
    team_list = list(teams)
    if n % 2 != 0:
        team_list.append(None)  # Bye
        n += 1

    total_rounds = n - 1
    matches_per_round = n // 2
    current_teams = list(team_list)

    rounds = []

    # First leg
    for r in range(total_rounds):
        round_num = r + 1
        r_name = f"{prefix}Matchweek {round_num:02d}"
        pairs = []
        for i in range(matches_per_round):
            t1 = current_teams[i]
            t2 = current_teams[n - 1 - i]
            if t1 is None or t2 is None:
                continue

            if (r + i) % 2 == 0:
                pairs.append((t1, t2))
            else:
                pairs.append((t2, t1))

        rounds.append({
            'round_name': r_name,
            'round_number': round_num,
            'pairs': pairs
        })
        current_teams = [current_teams[0]] + [current_teams[-1]] + current_teams[1:-1]

    # Second leg (reverse fixtures for double round-robin)
    if double_round:
        for r in range(total_rounds):
            round_num = total_rounds + r + 1
            r_name = f"{prefix}Matchweek {round_num:02d}"
            pairs = []
            for i in range(matches_per_round):
                t1 = current_teams[i]
                t2 = current_teams[n - 1 - i]
                if t1 is None or t2 is None:
                    continue

                if (r + i) % 2 == 0:
                    pairs.append((t2, t1))
                else:
                    pairs.append((t1, t2))

            rounds.append({
                'round_name': r_name,
                'round_number': round_num,
                'pairs': pairs
            })
            current_teams = [current_teams[0]] + [current_teams[-1]] + current_teams[1:-1]

    return rounds


def _allocate_groups_equally(teams, num_groups):
    """
    Divides teams equally across groups (e.g. 8 teams into 2 groups = 4 teams per group).
    """
    num_groups = max(1, min(num_groups, len(teams)))
    group_names = [f"Group {chr(65 + i)}" for i in range(num_groups)]
    groups = {g: [] for g in group_names}

    # Alternate assignment to ensure strictly equal group sizes
    for idx, t in enumerate(teams):
        g_name = group_names[idx % num_groups]
        groups[g_name].append(t)

    return groups


def _merge_concurrent_group_rounds(all_group_rounds):
    """
    Merges rounds across groups so Matchweek 01 of Group A and Group B run concurrently.
    """
    max_rounds = max(len(g_rounds) for _, g_rounds in all_group_rounds)
    merged = []

    for r_idx in range(max_rounds):
        round_num = r_idx + 1
        r_name = f"Matchweek {round_num:02d}"
        pairs_with_group = []
        for g_name, g_rounds in all_group_rounds:
            if r_idx < len(g_rounds):
                for h, a in g_rounds[r_idx]['pairs']:
                    pairs_with_group.append((h, a, g_name))

        merged.append({
            'round_name': r_name,
            'round_number': round_num,
            'pairs_with_group': pairs_with_group
        })

    return merged


def _find_next_preferred_date(start_from, preferred_weekdays, max_date=None):
    """
    Finds earliest date on or after start_from that matches preferred weekdays.
    Never clamps backwards to avoid infinite loops when days are filled to capacity.
    """
    cur = start_from
    for _ in range(730):
        if cur.weekday() in preferred_weekdays:
            return cur
        cur += timedelta(days=1)
    return start_from


def _count_preferred_days(from_date, to_date, preferred_weekdays):
    """Counts how many preferred matchdays exist between from_date and to_date inclusive."""
    if not to_date or from_date > to_date:
        return 999
    count = 0
    cur = from_date
    while cur <= to_date:
        if cur.weekday() in preferred_weekdays:
            count += 1
        cur += timedelta(days=1)
    return count


def _add_time(t, minutes):
    """Adds minutes to a time object safely."""
    dt = datetime.combine(date.today(), t) + timedelta(minutes=minutes)
    return dt.time()


def _allocate_conflict_free_slot(
    date_val,
    desired_time,
    desired_venue,
    venues,
    slot_times,
    booked_slots,
    min_time=None,
    preferred_weekdays=None,
    end_date=None
):
    """
    Finds and reserves a conflict-free (match_date, kickoff_time, venue) slot.
    - Prevents venue double-booking: no two matches share the same date, time, and venue.
    - If min_time is provided (sequential rounds on the same date), ensures time >= min_time.
    - Updates booked_slots with (match_date, kickoff_time, venue).
    """
    cur_date = date_val
    all_venues = list(dict.fromkeys([desired_venue] + list(venues) + DEFAULT_VENUES))
    if not all_venues:
        all_venues = DEFAULT_VENUES

    available_slot_times = list(slot_times) if slot_times else [time(15, 0)]

    for _ in range(30):
        # Determine valid kickoff times on this date
        valid_times = []
        for st in available_slot_times:
            if cur_date == date_val and min_time is not None and st < min_time:
                continue
            valid_times.append(st)

        if desired_time in valid_times:
            valid_times.remove(desired_time)
            valid_times.insert(0, desired_time)
        elif cur_date == date_val and min_time is not None:
            if not valid_times:
                valid_times = [min_time]
        elif not valid_times:
            valid_times = [desired_time or time(15, 0)]

        for st in valid_times:
            for ven in all_venues:
                slot_key = (cur_date, st, ven)
                if slot_key not in booked_slots:
                    booked_slots.add(slot_key)
                    return cur_date, st, ven

        # If day is full according to daily slot times, advance to next day matching preferred weekdays
        cand_date = cur_date + timedelta(days=1)
        if preferred_weekdays:
            cur_date = _find_next_preferred_date(cand_date, preferred_weekdays)
        else:
            cur_date = cand_date
        min_time = None
        available_slot_times = list(slot_times) if slot_times else [time(15, 0)]

    booked_slots.add((cur_date, desired_time, desired_venue))
    return cur_date, desired_time, desired_venue


def _calc_next_stage_date(current_stage_date, stages_remaining, end_date, preferred_weekdays):
    """
    Calculates the next stage target date so all remaining stages fit before end_date if possible,
    or smoothly advances to the next preferred weekday.
    Guarantees next stage is on a subsequent date (> current_stage_date).
    """
    if not end_date or end_date <= current_stage_date:
        return _find_next_preferred_date(current_stage_date + timedelta(days=1), preferred_weekdays)

    days_left = (end_date - current_stage_date).days
    if stages_remaining * 7 <= days_left:
        step = 7
    else:
        step = max(1, days_left // max(1, stages_remaining))

    target = current_stage_date + timedelta(days=step)
    nxt = _find_next_preferred_date(target, preferred_weekdays)
    if nxt <= current_stage_date:
        nxt = _find_next_preferred_date(current_stage_date + timedelta(days=1), preferred_weekdays)
    return nxt


def _schedule_daily_slots(
    rounds,
    start_date,
    preferred_weekdays,
    matches_per_day,
    slot_times,
    venues,
    end_date=None,
    booked_slots=None,
    global_daily_counts=None,
    teams_played_on_date=None,
    scheduling_strategy='optimized'
):
    """
    Schedules matches into daily capacity slots using user-defined kickoff times.
    Supports two distinct scheduling strategies:
      - 'optimized': Efficiently packs fixtures across available dates to utilize daily match capacity
        without leaving slots needlessly empty, while guaranteeing zero team conflicts and rest periods.
      - 'sequential': Strictly finishes all matches of a matchweek before starting the next on a subsequent date.
    Guarantees no team plays multiple matches on the same date and no match date exceeds end_date.
    Adheres strictly to matches_per_day across all concurrent groups and rounds.
    """
    if booked_slots is None:
        booked_slots = set()
    if global_daily_counts is None:
        global_daily_counts = Counter()
    if teams_played_on_date is None:
        teams_played_on_date = defaultdict(set)

    scheduled = []
    current_date = _find_next_preferred_date(start_date, preferred_weekdays, max_date=end_date)
    num_rounds = len(rounds)

    for r_idx, r in enumerate(rounds):
        round_name = r['round_name']
        round_num = r.get('round_number', 1)

        pairs = r.get('pairs') or [(item[0], item[1]) for item in r.get('pairs_with_group', [])]
        groups_tag = [item[2] if len(item) > 2 else '' for item in r.get('pairs_with_group', [])]

        for p_idx, (home, away) in enumerate(pairs):
            g_tag = groups_tag[p_idx] if p_idx < len(groups_tag) else ''
            h_id = getattr(home, 'id', None) if not isinstance(home, dict) else home.get('id')
            a_id = getattr(away, 'id', None) if not isinstance(away, dict) else away.get('id')

            # Advance date if daily matches limit reached OR either team already plays on current_date
            while (global_daily_counts[current_date] >= matches_per_day) or \
                  (h_id and h_id in teams_played_on_date[current_date]) or \
                  (a_id and a_id in teams_played_on_date[current_date]):
                cand = current_date + timedelta(days=1)
                current_date = _find_next_preferred_date(cand, preferred_weekdays)

            slot_idx = global_daily_counts[current_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            desired_venue = getattr(home, 'home_venue', '') or venues[slot_idx % len(venues)]
            match_d = current_date

            final_d, final_t, final_v = _allocate_conflict_free_slot(
                match_d, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            current_date = final_d

            stage_name = f"Group Stage ({g_tag})" if g_tag else "League Stage"

            scheduled.append({
                'round_name': round_name,
                'round_number': round_num,
                'group_name': g_tag,
                'stage_name': stage_name,
                'home_team': home,
                'away_team': away,
                'match_date': final_d,
                'kickoff_time': final_t,
                'venue': final_v,
                'is_knockout': False
            })

            global_daily_counts[final_d] += 1
            if h_id:
                teams_played_on_date[final_d].add(h_id)
            if a_id:
                teams_played_on_date[final_d].add(a_id)

        # Advance current_date for the next matchweek
        if r_idx < num_rounds - 1:
            if scheduling_strategy == 'optimized':
                # In optimized strategy: if current_date is full, advance to next preferred date.
                # If current_date has remaining capacity, keep current_date active so next round's
                # conflict-free fixtures can utilize remaining daily slot(s).
                if global_daily_counts[current_date] >= matches_per_day:
                    current_date = _find_next_preferred_date(current_date + timedelta(days=1), preferred_weekdays)
            else:
                # In sequential strategy: strictly finish this matchweek and advance to next date
                rounds_remaining = num_rounds - r_idx - 1
                if end_date and end_date > current_date:
                    # Collect remaining available preferred dates strictly after current_date up to end_date
                    rem_dates = []
                    c_chk = current_date + timedelta(days=1)
                    while c_chk <= end_date:
                        if c_chk.weekday() in preferred_weekdays:
                            rem_dates.append(c_chk)
                        c_chk += timedelta(days=1)

                    if rem_dates:
                        weekly_cand = _find_next_preferred_date(current_date + timedelta(days=7), preferred_weekdays)
                        # Calculate actual match days needed for remaining rounds
                        rounds_days_needed = sum(
                            math.ceil(len(rounds[r].get('pairs') or rounds[r].get('pairs_with_group', [])) / max(1, matches_per_day))
                            for r in range(r_idx + 1, num_rounds)
                        )
                        # If weekly cadence fits and leaves enough preferred match days for all remaining rounds, use it
                        if weekly_cand <= end_date and len([d for d in rem_dates if d >= weekly_cand]) >= rounds_days_needed:
                            current_date = weekly_cand
                        else:
                            # Distribute smoothly across remaining preferred dates so no round is pushed past end_date
                            slack = max(0, len(rem_dates) - rounds_days_needed)
                            idx_step = min(len(rem_dates) - 1, slack // rounds_remaining) if rounds_remaining > 0 else 0
                            current_date = rem_dates[idx_step]
                    else:
                        current_date = _find_next_preferred_date(current_date + timedelta(days=1), preferred_weekdays)
                elif not end_date:
                    next_week_target = current_date + timedelta(days=7)
                    current_date = _find_next_preferred_date(next_week_target, preferred_weekdays)
                else:
                    next_week_target = current_date + timedelta(days=1)
                    current_date = _find_next_preferred_date(next_week_target, preferred_weekdays)

    return scheduled


def _extract_team_val(team_obj, key, default=''):
    if team_obj is None:
        return default
    if isinstance(team_obj, dict):
        val = team_obj.get(key, default)
        return val() if callable(val) else val
    if hasattr(team_obj, key):
        val = getattr(team_obj, key)
        return val() if callable(val) else val
    return default


def _generate_knockout_stage_for_groups(
    groups_dict,
    start_date,
    preferred_weekdays,
    slot_times,
    venues,
    qualifiers_per_group=2,
    two_legged=False,
    end_date=None,
    booked_slots=None,
    matches_per_day=1,
    global_daily_counts=None,
    teams_played_on_date=None,
    sf_preference='same_day'
):
    """
    Generates single-elimination knockout fixtures tailored strictly to Teams Qualifying Per Group
    and the Number of Groups.
    Supports 1, 2, or 4 groups with 1, 2, 3, or 4 qualifiers per group.
    
    Structure:
    - 2 total qualifiers: Grand Championship Final (1 match)
    - 4 total qualifiers: Semi-Finals (Single or 2 Legs) -> Grand Championship Final (1 match)
    - 6 total qualifiers: Play-In / Quarter-Finals -> Semi-Finals -> Grand Championship Final (1 match)
    - 8 total qualifiers: Quarter-Finals -> Semi-Finals -> Grand Championship Final (1 match)
    - 16 total qualifiers: Round of 16 -> Quarter-Finals -> Semi-Finals -> Grand Championship Final (1 match)
    """
    if booked_slots is None:
        booked_slots = set()
    if global_daily_counts is None:
        global_daily_counts = Counter()
    if teams_played_on_date is None:
        teams_played_on_date = defaultdict(set)

    knockout_matches = []
    group_names = sorted(list(groups_dict.keys()))
    num_groups = len(group_names)
    cur_date = _find_next_preferred_date(start_date, preferred_weekdays)

    max_teams = max((len(t) for t in groups_dict.values()), default=1)
    q_per_group = max(1, min(int(qualifiers_per_group or 2), max_teams))

    seeds = {}
    for g in group_names:
        seeds[g] = []
        for q in range(q_per_group):
            suf = {1: 'st', 2: 'nd', 3: 'rd'}.get(q + 1, 'th')
            rank_str = f"{q + 1}{suf} Place" if num_groups == 1 else f"{q + 1}{suf} {g}"
            short_suf = f"P{q + 1}" if num_groups == 1 else f"{q + 1}{g[-1]}"
            seeds[g].append({
                'id': None,
                'name': rank_str,
                'seed_label': rank_str,
                'team_name': rank_str,
                'short_name': short_suf,
                'is_placeholder': True,
                'get_logo_url': lambda: "",
                'home_venue': ''
            })

    total_q = num_groups * q_per_group

    # CASE A: 2 TOTAL QUALIFIERS -> Straight to Grand Championship Final
    if total_q <= 2:
        if num_groups >= 2:
            home = seeds[group_names[0]][0]
            away = seeds[group_names[1]][0]
        else:
            home = seeds[group_names[0]][0]
            away = seeds[group_names[0]][1] if len(seeds[group_names[0]]) > 1 else seeds[group_names[0]][0]

        while global_daily_counts[cur_date] >= matches_per_day:
            cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

        slot_idx = global_daily_counts[cur_date]
        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            cur_date, slot_times[slot_idx % len(slot_times)], home.get('home_venue') or venues[slot_idx % len(venues)], venues, slot_times, booked_slots,
            preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        global_daily_counts[f_date] += 1
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 100,
            'group_name': "Knockout",
            'stage_name': "Championship Final",
            'home_team': home,
            'away_team': away,
            'placeholder_home': home.get('name', ''),
            'placeholder_away': away.get('name', ''),
            'match_date': f_date,
            'kickoff_time': f_time,
            'venue': f_ven,
            'is_knockout': True
        })
        return knockout_matches

    # CASE B: 4 TOTAL QUALIFIERS -> Semi-Finals (2 matches) -> Grand Championship Final (1 match)
    if total_q == 4:
        if num_groups == 2:
            gA, gB = group_names[0], group_names[1]
            sf1 = (seeds[gA][0], seeds[gB][1])
            sf2 = (seeds[gB][0], seeds[gA][1])
        elif num_groups == 4:
            gA, gB, gC, gD = group_names[0], group_names[1], group_names[2], group_names[3]
            sf1 = (seeds[gA][0], seeds[gB][0])
            sf2 = (seeds[gC][0], seeds[gD][0])
        else:
            g0 = group_names[0]
            sf1 = (seeds[g0][0], seeds[g0][3])
            sf2 = (seeds[g0][1], seeds[g0][2])

        sf_pairs = [sf1, sf2]
        sf_times = []
        sf_dates = []

        for idx, (h, a) in enumerate(sf_pairs):
            if idx > 0 and sf_preference == 'separate_days':
                cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
            else:
                while global_daily_counts[cur_date] >= matches_per_day:
                    cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

            slot_idx = global_daily_counts[cur_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            desired_venue = h.get('home_venue') or venues[slot_idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            sf_times.append(k_time)
            sf_dates.append(m_date)
            global_daily_counts[m_date] += 1

            knockout_matches.append({
                'round_name': "Semi-Finals" if not two_legged else "Semi-Finals (Leg 1)",
                'round_number': 100,
                'group_name': "Knockout",
                'stage_name': "Semi-Finals",
                'home_team': h,
                'away_team': a,
                'placeholder_home': h.get('name', ''),
                'placeholder_away': a.get('name', ''),
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        if two_legged:
            latest_sf_date = max(sf_dates) if sf_dates else cur_date
            leg2_date = _calc_next_stage_date(latest_sf_date, 2, end_date, preferred_weekdays)
            leg2_times = []
            leg2_dates = []
            for idx, (h, a) in enumerate(sf_pairs):
                if idx > 0 and sf_preference == 'separate_days':
                    leg2_date = _find_next_preferred_date(leg2_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
                else:
                    while global_daily_counts[leg2_date] >= matches_per_day:
                        leg2_date = _find_next_preferred_date(leg2_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

                slot_idx = global_daily_counts[leg2_date]
                desired_time = slot_times[slot_idx % len(slot_times)]
                desired_venue = a.get('home_venue') or venues[(slot_idx + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    leg2_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                leg2_times.append(l2_time)
                leg2_dates.append(l2_date)
                global_daily_counts[l2_date] += 1
                knockout_matches.append({
                    'round_name': "Semi-Finals (Leg 2)",
                    'round_number': 100,
                    'group_name': "Knockout",
                    'stage_name': "Semi-Finals",
                    'home_team': a,
                    'away_team': h,
                    'placeholder_home': a.get('name', ''),
                    'placeholder_away': h.get('name', ''),
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
                    'is_knockout': True
                })
            last_ko_date = max(leg2_dates) if leg2_dates else leg2_date
            final_date = _calc_next_stage_date(last_ko_date, 1, end_date, preferred_weekdays)
            if final_date <= last_ko_date:
                final_date = _find_next_preferred_date(last_ko_date + timedelta(days=1), preferred_weekdays)
            min_time = None
        else:
            latest_sf_date = max(sf_dates) if sf_dates else cur_date
            final_date = _calc_next_stage_date(latest_sf_date, 1, end_date, preferred_weekdays)
            if final_date <= latest_sf_date:
                final_date = _find_next_preferred_date(latest_sf_date + timedelta(days=1), preferred_weekdays)
            min_time = None

        while global_daily_counts[final_date] >= matches_per_day:
            final_date = _find_next_preferred_date(final_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

        final_home = {
            'id': None,
            'name': "Winner of Semi-Final 1",
            'team_name': "Winner of Semi-Final 1",
            'short_name': "W-SF1",
            'seed_label': "Winner of Semi-Final 1",
            'is_placeholder': True,
            'get_logo_url': lambda: ""
        }
        final_away = {
            'id': None,
            'name': "Winner of Semi-Final 2",
            'team_name': "Winner of Semi-Final 2",
            'short_name': "W-SF2",
            'seed_label': "Winner of Semi-Final 2",
            'is_placeholder': True,
            'get_logo_url': lambda: ""
        }
        f_slot = global_daily_counts[final_date]
        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            final_date, slot_times[f_slot % len(slot_times)], venues[f_slot % len(venues)], venues, slot_times, booked_slots,
            min_time=min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        global_daily_counts[f_date] += 1
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 101 if not two_legged else 102,
            'group_name': "Knockout",
            'stage_name': "Championship Final",
            'home_team': final_home,
            'away_team': final_away,
            'match_date': f_date,
            'kickoff_time': f_time,
            'venue': f_ven,
            'is_knockout': True
        })
        return knockout_matches

    # CASE C: 6 TOTAL QUALIFIERS -> Play-In / Quarter-Finals -> Semi-Finals -> Final
    if total_q == 6:
        if num_groups == 2:
            gA, gB = group_names[0], group_names[1]
            qf1 = (seeds[gA][1], seeds[gB][2])
            qf2 = (seeds[gB][1], seeds[gA][2])
            bye1 = seeds[gA][0]
            bye2 = seeds[gB][0]
        else:
            g0 = group_names[0]
            qf1 = (seeds[g0][2], seeds[g0][5])
            qf2 = (seeds[g0][3], seeds[g0][4])
            bye1 = seeds[g0][0]
            bye2 = seeds[g0][1]

        qf_pairs = [qf1, qf2]
        qf_times = []
        qf_dates = []
        for idx, (h, a) in enumerate(qf_pairs):
            while global_daily_counts[cur_date] >= matches_per_day:
                cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

            slot_idx = global_daily_counts[cur_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            desired_venue = h.get('home_venue') or venues[slot_idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            qf_times.append(k_time)
            qf_dates.append(m_date)
            global_daily_counts[m_date] += 1
            knockout_matches.append({
                'round_name': "Play-In / Quarter-Finals" if not two_legged else "Play-In / Quarter-Finals (Leg 1)",
                'round_number': 100,
                'group_name': "Knockout",
                'stage_name': "Quarter-Finals",
                'home_team': h,
                'away_team': a,
                'placeholder_home': h.get('name', ''),
                'placeholder_away': a.get('name', ''),
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        latest_qf_date = max(qf_dates) if qf_dates else cur_date
        sf_date = _calc_next_stage_date(latest_qf_date, 2, end_date, preferred_weekdays)
        if sf_date <= latest_qf_date and (not end_date or latest_qf_date < end_date):
            sf_date = _find_next_preferred_date(latest_qf_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
        sf_min_time = _add_time(max(qf_times), 150) if sf_date <= latest_qf_date else None

        sf1_away = {
            'id': None, 'name': "Winner of Play-In 1", 'team_name': "Winner of Play-In 1",
            'short_name': "W-PI1", 'seed_label': "Winner of Play-In 1", 'is_placeholder': True, 'get_logo_url': lambda: ""
        }
        sf2_away = {
            'id': None, 'name': "Winner of Play-In 2", 'team_name': "Winner of Play-In 2",
            'short_name': "W-PI2", 'seed_label': "Winner of Play-In 2", 'is_placeholder': True, 'get_logo_url': lambda: ""
        }
        sf_ties = [(bye1, sf1_away), (bye2, sf2_away)]
        sf_times = []
        sf_dates = []

        cur_sf_date = sf_date
        for idx, (h, a) in enumerate(sf_ties):
            if idx > 0 and sf_preference == 'separate_days':
                cur_sf_date = _find_next_preferred_date(cur_sf_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
            else:
                while global_daily_counts[cur_sf_date] >= matches_per_day:
                    cur_sf_date = _find_next_preferred_date(cur_sf_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

            slot_idx = global_daily_counts[cur_sf_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            desired_venue = (h.get('home_venue') if isinstance(h, dict) else getattr(h, 'home_venue', '')) or venues[slot_idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_sf_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                min_time=sf_min_time if cur_sf_date <= latest_qf_date else None, preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            sf_times.append(k_time)
            sf_dates.append(m_date)
            global_daily_counts[m_date] += 1
            knockout_matches.append({
                'round_name': "Semi-Finals" if not two_legged else "Semi-Finals (Leg 1)",
                'round_number': 101,
                'group_name': "Knockout",
                'stage_name': "Semi-Finals",
                'home_team': h,
                'away_team': a,
                'placeholder_home': h.get('name', ''),
                'placeholder_away': a.get('name', ''),
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        latest_sf_date = max(sf_dates) if sf_dates else cur_sf_date
        final_date = _calc_next_stage_date(latest_sf_date, 1, end_date, preferred_weekdays)
        if final_date <= latest_sf_date:
            final_date = _find_next_preferred_date(latest_sf_date + timedelta(days=1), preferred_weekdays)
        while global_daily_counts[final_date] >= matches_per_day:
            final_date = _find_next_preferred_date(final_date + timedelta(days=1), preferred_weekdays)

        final_home = {'id': None, 'name': "Winner of Semi-Final 1", 'team_name': "Winner of Semi-Final 1", 'short_name': "W-SF1", 'seed_label': "Winner SF 1", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        final_away = {'id': None, 'name': "Winner of Semi-Final 2", 'team_name': "Winner of Semi-Final 2", 'short_name': "W-SF2", 'seed_label': "Winner SF 2", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        f_slot = global_daily_counts[final_date]
        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            final_date, slot_times[f_slot % len(slot_times)], venues[f_slot % len(venues)], venues, slot_times, booked_slots,
            preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        global_daily_counts[f_date] += 1
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 102,
            'group_name': "Knockout",
            'stage_name': "Championship Final",
            'home_team': final_home,
            'away_team': final_away,
            'match_date': f_date,
            'kickoff_time': f_time,
            'venue': f_ven,
            'is_knockout': True
        })
        return knockout_matches

    # CASE D: 8 TOTAL QUALIFIERS -> Quarter-Finals (4 matches) -> Semi-Finals (2 matches) -> Final (1 match)
    if total_q == 8:
        if num_groups == 4:
            gA, gB, gC, gD = group_names[0], group_names[1], group_names[2], group_names[3]
            qfs = [
                (seeds[gA][0], seeds[gB][1]),
                (seeds[gC][0], seeds[gD][1]),
                (seeds[gB][0], seeds[gA][1]),
                (seeds[gD][0], seeds[gC][1]),
            ]
        elif num_groups == 2:
            gA, gB = group_names[0], group_names[1]
            qfs = [
                (seeds[gA][0], seeds[gB][3]),
                (seeds[gA][1], seeds[gB][2]),
                (seeds[gB][0], seeds[gA][3]),
                (seeds[gB][1], seeds[gA][2]),
            ]
        else:
            g0 = group_names[0]
            qfs = [
                (seeds[g0][0], seeds[g0][7]),
                (seeds[g0][1], seeds[g0][6]),
                (seeds[g0][2], seeds[g0][5]),
                (seeds[g0][3], seeds[g0][4]),
            ]

        qf_times = []
        qf_dates = []
        for idx, (h, a) in enumerate(qfs):
            while global_daily_counts[cur_date] >= matches_per_day:
                cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

            slot_idx = global_daily_counts[cur_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            desired_venue = h.get('home_venue') or venues[slot_idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            qf_times.append(k_time)
            qf_dates.append(m_date)
            global_daily_counts[m_date] += 1
            knockout_matches.append({
                'round_name': "Quarter-Finals" if not two_legged else "Quarter-Finals (Leg 1)",
                'round_number': 100,
                'group_name': "Knockout",
                'stage_name': "Quarter-Finals",
                'home_team': h,
                'away_team': a,
                'placeholder_home': h.get('name', ''),
                'placeholder_away': a.get('name', ''),
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        latest_qf_date = max(qf_dates) if qf_dates else cur_date
        sf_date = _calc_next_stage_date(latest_qf_date, 2, end_date, preferred_weekdays)
        if sf_date <= latest_qf_date and (not end_date or latest_qf_date < end_date):
            sf_date = _find_next_preferred_date(latest_qf_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

        sf1_home = {'id': None, 'name': "Winner of Quarter-Final 1", 'team_name': "Winner of Quarter-Final 1", 'short_name': "W-QF1", 'seed_label': "Winner of QF 1", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf1_away = {'id': None, 'name': "Winner of Quarter-Final 2", 'team_name': "Winner of Quarter-Final 2", 'short_name': "W-QF2", 'seed_label': "Winner of QF 2", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf2_home = {'id': None, 'name': "Winner of Quarter-Final 3", 'team_name': "Winner of Quarter-Final 3", 'short_name': "W-QF3", 'seed_label': "Winner of QF 3", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf2_away = {'id': None, 'name': "Winner of Quarter-Final 4", 'team_name': "Winner of Quarter-Final 4", 'short_name': "W-QF4", 'seed_label': "Winner of QF 4", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf_ties = [(sf1_home, sf1_away), (sf2_home, sf2_away)]
        sf_times = []
        sf_dates = []

        cur_sf_date = sf_date
        for idx, (h, a) in enumerate(sf_ties):
            if idx > 0 and sf_preference == 'separate_days':
                cur_sf_date = _find_next_preferred_date(cur_sf_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
            else:
                while global_daily_counts[cur_sf_date] >= matches_per_day:
                    cur_sf_date = _find_next_preferred_date(cur_sf_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

            slot_idx = global_daily_counts[cur_sf_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            desired_venue = venues[slot_idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_sf_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            sf_times.append(k_time)
            sf_dates.append(m_date)
            global_daily_counts[m_date] += 1
            knockout_matches.append({
                'round_name': "Semi-Finals" if not two_legged else "Semi-Finals (Leg 1)",
                'round_number': 101,
                'group_name': "Knockout",
                'stage_name': "Semi-Finals",
                'home_team': h,
                'away_team': a,
                'placeholder_home': h.get('name', ''),
                'placeholder_away': a.get('name', ''),
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        latest_sf_date = max(sf_dates) if sf_dates else cur_sf_date
        final_date = _calc_next_stage_date(latest_sf_date, 1, end_date, preferred_weekdays)
        if final_date <= latest_sf_date:
            final_date = _find_next_preferred_date(latest_sf_date + timedelta(days=1), preferred_weekdays)
        while global_daily_counts[final_date] >= matches_per_day:
            final_date = _find_next_preferred_date(final_date + timedelta(days=1), preferred_weekdays)

        final_home = {'id': None, 'name': "Winner of Semi-Final 1", 'team_name': "Winner of Semi-Final 1", 'short_name': "W-SF1", 'seed_label': "Winner SF 1", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        final_away = {'id': None, 'name': "Winner of Semi-Final 2", 'team_name': "Winner of Semi-Final 2", 'short_name': "W-SF2", 'seed_label': "Winner SF 2", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        f_slot = global_daily_counts[final_date]
        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            final_date, slot_times[f_slot % len(slot_times)], venues[f_slot % len(venues)], venues, slot_times, booked_slots,
            preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        global_daily_counts[f_date] += 1
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 102,
            'group_name': "Knockout",
            'stage_name': "Championship Final",
            'home_team': final_home,
            'away_team': final_away,
            'match_date': f_date,
            'kickoff_time': f_time,
            'venue': f_ven,
            'is_knockout': True
        })
        return knockout_matches

    # GENERAL FALLBACK FOR 16 OR ARBITRARY NUMBER OF QUALIFIERS
    all_qualifiers = []
    for g in group_names:
        all_qualifiers.extend(seeds[g])
    cur_teams = all_qualifiers
    stage_idx = 100
    prev_stage_date = None
    prev_stage_latest_time = None

    while len(cur_teams) > 1:
        n = len(cur_teams)
        if n > 8:
            stage_name = "Round of 16"
        elif n > 4:
            stage_name = "Quarter-Finals"
        elif n > 2:
            stage_name = "Semi-Finals"
        else:
            stage_name = "Grand Championship Final"

        half = n // 2
        next_teams = []
        is_final = (stage_name == "Grand Championship Final")
        stage_two_legged = (two_legged and not is_final)
        stage_badge = "Championship Final" if is_final else stage_name

        min_time = None
        if prev_stage_date and cur_date <= prev_stage_date and prev_stage_latest_time:
            min_time = _add_time(prev_stage_latest_time, 150)

        cur_stage_times = []
        for i in range(half):
            t1 = cur_teams[i]
            t2 = cur_teams[n - 1 - i]

            if stage_name == "Semi-Finals" and i > 0 and sf_preference == 'separate_days':
                cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
            else:
                while global_daily_counts[cur_date] >= matches_per_day:
                    cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

            slot_idx = global_daily_counts[cur_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            t1_venue = (t1.get('home_venue') if isinstance(t1, dict) else getattr(t1, 'home_venue', '')) or venues[slot_idx % len(venues)]

            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, t1_venue, venues, slot_times, booked_slots,
                min_time=min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            cur_stage_times.append(k_time)
            global_daily_counts[m_date] += 1

            knockout_matches.append({
                'round_name': stage_name if not stage_two_legged else f"{stage_name} (Leg 1)",
                'round_number': stage_idx,
                'group_name': "Knockout",
                'stage_name': stage_badge,
                'home_team': t1,
                'away_team': t2,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

            match_no = i + 1
            if stage_name == "Semi-Finals":
                next_label = f"Winner of Semi-Final {match_no}"
                next_short = f"W-SF{match_no}"
            elif stage_name == "Quarter-Finals":
                next_label = f"Winner of Quarter-Final {match_no}"
                next_short = f"W-QF{match_no}"
            else:
                next_label = f"Winner of {stage_name} {match_no}"
                next_short = f"W-{stage_name[:2]}{match_no}"

            next_teams.append({
                'id': None,
                'name': next_label,
                'team_name': next_label,
                'short_name': next_short,
                'seed_label': next_label,
                'is_placeholder': True,
                'get_logo_url': lambda: "",
                'home_venue': ''
            })

        cur_teams = next_teams
        prev_stage_date = cur_date
        prev_stage_latest_time = max(cur_stage_times) if cur_stage_times else time(15, 0)
        stage_idx += 1
        cur_date = _calc_next_stage_date(cur_date, max(1, half), end_date, preferred_weekdays)
        if cur_date <= prev_stage_date and (not end_date or prev_stage_date < end_date):
            cur_date = _find_next_preferred_date(prev_stage_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

    return knockout_matches


def plan_knockout_byes(n):
    """
    Calculates the round-by-round tournament progression for single-elimination knockout tournaments.
    - If n is a power of 2, generates standard rounds with 0 BYEs.
    - If n is not a power of 2:
        - BYEs start from Round 1.
        - Maximum 3 BYEs per round, distributed across rounds.
        - Strongly prefers 2 or 3 BYEs per round (2 if remaining teams even, 3 if odd).
        - No BYEs in semi-finals (exactly 4 teams) or final (exactly 2 teams).
        - Advancing teams = BYEs + (Teams - BYEs) / 2.
        - Total actual matches = n - 1.
    """
    if n <= 1:
        return []

    # Power of 2 check
    if (n & (n - 1)) == 0:
        rounds = []
        cur = n
        while cur > 1:
            m = cur // 2
            rounds.append({'teams': cur, 'byes': 0, 'matches': m, 'advancing': m})
            cur = m
        return rounds

    from collections import deque

    def search(allowed_byes):
        queue = deque([(n, [])])
        visited = {n}
        while queue:
            cur, path = queue.popleft()
            if cur == 4:
                full = list(path)
                full.append({'teams': 4, 'byes': 0, 'matches': 2, 'advancing': 2})
                full.append({'teams': 2, 'byes': 0, 'matches': 1, 'advancing': 1})
                return full

            choices = []
            for b in allowed_byes:
                if b < cur and (cur - b) >= 2 and (cur - b) % 2 == 0:
                    nxt = b + (cur - b) // 2
                    if nxt >= 4:
                        choices.append(b)

            # Prioritize 2 if cur is even, 3 if cur is odd
            choices.sort(key=lambda b: (0 if ((cur % 2 == 0 and b == 2) or (cur % 2 == 1 and b == 3)) else 1, -b))

            for b in choices:
                nxt = b + (cur - b) // 2
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, path + [{'teams': cur, 'byes': b, 'matches': (cur - b) // 2, 'advancing': nxt}]))
        return None

    # Search prioritizing {2, 3}
    for allowed in [[2, 3], [2, 3, 1], [2, 3, 1, 0]]:
        res = search(allowed)
        if res is not None:
            return res

    # Fallback for n < 4 (e.g. n = 3)
    if n == 3:
        return [
            {'teams': 3, 'byes': 1, 'matches': 1, 'advancing': 2},
            {'teams': 2, 'byes': 0, 'matches': 1, 'advancing': 1}
        ]

    return []


def get_knockout_stage_names(n, plan):
    """
    Returns human-friendly stage names for knockout rounds.
    For power-of-two brackets: Final, Semi-Finals, Quarter-Finals, Round of 16, Round of 32, etc.
    For distributed-BYE brackets: Round 1, Round 2, ..., Semi-Finals, Final.
    """
    num_rounds = len(plan)
    if num_rounds == 0:
        return []
    if (n & (n - 1)) == 0:
        if num_rounds == 1:
            return ["Final"]
        elif num_rounds == 2:
            return ["Semi-Finals", "Final"]
        elif num_rounds == 3:
            return ["Quarter-Finals", "Semi-Finals", "Final"]
        elif num_rounds == 4:
            return ["Round of 16", "Quarter-Finals", "Semi-Finals", "Final"]
        elif num_rounds == 5:
            return ["Round of 32", "Round of 16", "Quarter-Finals", "Semi-Finals", "Final"]
        else:
            names = [f"Round of {2**r}" for r in range(num_rounds, 2, -1)]
            names.extend(["Quarter-Finals", "Semi-Finals", "Final"])
            return names
    else:
        if num_rounds == 1:
            return ["Final"]
        elif num_rounds == 2:
            return ["Semi-Finals", "Final"]
        names = [f"Round {i+1}" for i in range(num_rounds - 2)]
        names.extend(["Semi-Finals", "Final"])
        return names


def _generate_single_elimination_bracket(
    teams,
    start_date,
    preferred_weekdays,
    slot_times,
    venues,
    two_legged=False,
    end_date=None,
    booked_slots=None,
    matches_per_day=1,
    global_daily_counts=None,
    teams_played_on_date=None,
    sf_preference='same_day'
):
    """
    Generates single elimination knockout bracket for pure knockout tournaments,
    guaranteed to conclude on or before end_date.
    Implements a distributed BYE system (max 3 BYEs per round, starting from Round 1,
    0 BYEs in SF/Final) when team count is not a power of 2.
    Ensures subsequent rounds use placeholder seeds, conflict-free venues,
    and sequential timing adhering to matches_per_day capacity and team rest rules.
    """
    if booked_slots is None:
        booked_slots = set()
    if global_daily_counts is None:
        global_daily_counts = Counter()
    if teams_played_on_date is None:
        teams_played_on_date = defaultdict(set)

    matches = []
    n = len(teams)
    if n < 2:
        return []

    cur_teams = list(teams)
    cur_date = _find_next_preferred_date(start_date, preferred_weekdays)

    plan = plan_knockout_byes(n)
    stage_names = get_knockout_stage_names(n, plan)

    prev_stage_date = None
    prev_stage_latest_time = None

    for stage_idx, step in enumerate(plan):
        stage_name = stage_names[stage_idx]
        b_count = step['byes']
        m_count = step['matches']
        is_final = (stage_name == "Final" or stage_idx == len(plan) - 1)
        is_sf = (stage_name == "Semi-Finals")
        stage_two_legged = (two_legged and not is_final)
        stage_badge = "Championship Final" if is_final else stage_name

        # Distribute BYE teams and playing teams
        bye_teams = cur_teams[:b_count]
        playing_teams = cur_teams[b_count:]

        bye_names = []
        for b in bye_teams:
            if isinstance(b, dict):
                b_name = b.get('name') or b.get('team_name') or 'BYE Team'
            else:
                b_name = getattr(b, 'name', 'BYE Team')
            bye_names.append(b_name)

        min_time = None
        if prev_stage_date and cur_date <= prev_stage_date and prev_stage_latest_time:
            min_time = _add_time(prev_stage_latest_time, 150)

        current_stage_times = []
        current_stage_dates = []

        for i in range(m_count):
            t1 = playing_teams[i]
            t2 = playing_teams[len(playing_teams) - 1 - i]
            t1_id = getattr(t1, 'id', None) if not isinstance(t1, dict) else t1.get('id')
            t2_id = getattr(t2, 'id', None) if not isinstance(t2, dict) else t2.get('id')

            # Respect semi-final preference for separate days
            if is_sf and i > 0 and sf_preference == 'separate_days':
                cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
            else:
                while (global_daily_counts[cur_date] >= matches_per_day) or \
                      (t1_id and t1_id in teams_played_on_date[cur_date]) or \
                      (t2_id and t2_id in teams_played_on_date[cur_date]):
                    cand = cur_date + timedelta(days=1)
                    cur_date = _find_next_preferred_date(cand, preferred_weekdays, max_date=end_date)

            slot_idx = global_daily_counts[cur_date]
            desired_time = slot_times[slot_idx % len(slot_times)]
            t1_venue = (t1.get('home_venue') if isinstance(t1, dict) else getattr(t1, 'home_venue', '')) or venues[slot_idx % len(venues)]

            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, t1_venue, venues, slot_times, booked_slots,
                min_time=min_time if cur_date <= (prev_stage_date or cur_date) else None,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            current_stage_times.append(k_time)
            current_stage_dates.append(m_date)
            global_daily_counts[m_date] += 1
            if t1_id:
                teams_played_on_date[m_date].add(t1_id)
            if t2_id:
                teams_played_on_date[m_date].add(t2_id)

            matches.append({
                'round_name': stage_name if not stage_two_legged else f"{stage_name} (Leg 1)",
                'round_number': stage_idx + 1,
                'group_name': "Knockout",
                'stage_name': stage_badge,
                'home_team': t1,
                'away_team': t2,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True,
                'round_byes': bye_names if i == 0 else []
            })

            if stage_two_legged:
                leg2_target = _calc_next_stage_date(m_date, max(1, len(stage_names) - stage_idx), end_date, preferred_weekdays)
                t2_venue = (t2.get('home_venue') if isinstance(t2, dict) else getattr(t2, 'home_venue', '')) or venues[(i + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    leg2_target, desired_time, t2_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                global_daily_counts[l2_date] += 1
                matches.append({
                    'round_name': f"{stage_name} (Leg 2)",
                    'round_number': stage_idx + 1,
                    'group_name': "Knockout",
                    'stage_name': stage_badge,
                    'home_team': t2,
                    'away_team': t1,
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
                    'is_knockout': True,
                    'round_byes': []
                })

        # Advance teams: BYE teams advance automatically, match winners advance via placeholder seeds
        next_teams = list(bye_teams)
        for i in range(m_count):
            match_no = i + 1
            if stage_name == "Semi-Finals":
                next_label = f"Winner of Semi-Final {match_no}"
                next_short = f"W-SF{match_no}"
            elif stage_name == "Quarter-Finals":
                next_label = f"Winner of Quarter-Final {match_no}"
                next_short = f"W-QF{match_no}"
            elif stage_name.startswith("Round of"):
                next_label = f"Winner of {stage_name} Match {match_no}"
                next_short = f"W-R{stage_name.replace('Round of ', '')}-{match_no}"
            else:
                next_label = f"Winner of {stage_name} Match {match_no}"
                next_short = f"W-{stage_name.replace(' ', '')}-M{match_no}"

            next_teams.append({
                'id': None,
                'name': next_label,
                'team_name': next_label,
                'short_name': next_short,
                'seed_label': next_label,
                'is_placeholder': True,
                'get_logo_url': lambda: "",
                'home_venue': ''
            })

        cur_teams = next_teams
        last_match_date = max(current_stage_dates) if current_stage_dates else cur_date
        prev_stage_date = last_match_date
        prev_stage_latest_time = max(current_stage_times) if current_stage_times else time(15, 0)
        cur_date = _calc_next_stage_date(last_match_date, max(1, len(stage_names) - stage_idx), end_date, preferred_weekdays)
        if cur_date <= last_match_date:
            cur_date = _find_next_preferred_date(last_match_date + timedelta(days=1), preferred_weekdays)

    return matches


def _normalize_team_seed(t, default_label, default_short):
    """
    Normalizes a team object or seed dictionary into a uniform dictionary
    with id, team_name, seed_label, short_name, logo getter, and venue.
    """
    if t is None:
        return {
            'id': None,
            'name': default_label,
            'team_name': default_label,
            'short_name': default_short,
            'seed_label': default_label,
            'get_logo_url': lambda: '',
            'home_venue': ''
        }
    if isinstance(t, dict):
        return {
            'id': t.get('id'),
            'name': t.get('name') or default_label,
            'team_name': t.get('team_name') or t.get('name') or default_label,
            'short_name': t.get('short_name') or default_short,
            'seed_label': t.get('seed_label') or default_label,
            'get_logo_url': t.get('get_logo_url', lambda: ''),
            'home_venue': t.get('home_venue', '')
        }
    return {
        'id': getattr(t, 'id', None),
        'name': f"{default_label} ({t.name})" if getattr(t, 'name', None) else default_label,
        'team_name': getattr(t, 'name', default_label),
        'short_name': getattr(t, 'short_name', default_short),
        'seed_label': default_label,
        'get_logo_url': getattr(t, 'get_logo_url', lambda: ''),
        'home_venue': getattr(t, 'home_venue', '')
    }


def _generate_page_mcintyre_fixtures(
    teams,
    start_date,
    preferred_weekdays,
    slot_times,
    venues,
    end_date=None,
    prefix="",
    booked_slots=None,
    matches_per_day=1,
    global_daily_counts=None,
    teams_played_on_date=None,
    sf_preference='same_day'
):
    """
    Generates the authentic Page–McIntyre Playoff System (Final Four) fixtures:
    Requires 4 teams (Seed 1 to 4).
    1. Qualifying Final (Major Semi-Final): Seed 1 vs Seed 2. Winner straight to Grand Final, Loser to Preliminary Final.
    2. Elimination Final (Minor Semi-Final): Seed 3 vs Seed 4. Winner to Preliminary Final, Loser eliminated.
    3. Preliminary Final: Loser QF vs Winner EF. Winner to Grand Final, Loser eliminated (3rd place).
    4. Grand Final: Winner QF vs Winner PF. Winner is crowned Champion!
    """
    if len(teams) < 4:
        return []

    if booked_slots is None:
        booked_slots = set()
    if global_daily_counts is None:
        global_daily_counts = Counter()
    if teams_played_on_date is None:
        teams_played_on_date = defaultdict(set)

    cur_date = _find_next_preferred_date(start_date, preferred_weekdays)

    seed1 = _normalize_team_seed(teams[0], "1st Place", "1st")
    seed2 = _normalize_team_seed(teams[1], "2nd Place", "2nd")
    seed3 = _normalize_team_seed(teams[2], "3rd Place", "3rd")
    seed4 = _normalize_team_seed(teams[3], "4th Place", "4th")

    matches = []
    stage1_times = []
    stage1_dates = []

    # STAGE 1 (Semi-Finals round):
    # Match 1: Qualifying Final (1st vs 2nd)
    while global_daily_counts[cur_date] >= matches_per_day:
        cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

    slot_idx = global_daily_counts[cur_date]
    qf_venue = seed1.get('home_venue') or venues[slot_idx % len(venues)]
    qf_date, qf_time, qf_ven = _allocate_conflict_free_slot(
        cur_date, slot_times[slot_idx % len(slot_times)], qf_venue, venues, slot_times, booked_slots,
        preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    stage1_times.append(qf_time)
    stage1_dates.append(qf_date)
    global_daily_counts[qf_date] += 1
    matches.append({
        'round_name': f"{prefix}Qualifying Final (1st vs 2nd)".strip(),
        'round_number': 100,
        'group_name': "Knockout",
        'stage_name': "Qualifying Final",
        'home_team': seed1,
        'away_team': seed2,
        'match_date': qf_date,
        'kickoff_time': qf_time,
        'venue': qf_ven,
        'is_knockout': True
    })

    # Match 2: Elimination Final (3rd vs 4th)
    if sf_preference == 'separate_days':
        cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
    else:
        while global_daily_counts[cur_date] >= matches_per_day:
            cur_date = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

    ef_slot = global_daily_counts[cur_date]
    ef_venue = seed3.get('home_venue') or venues[ef_slot % len(venues)]
    ef_time_des = slot_times[ef_slot % len(slot_times)]
    ef_date, ef_time, ef_ven = _allocate_conflict_free_slot(
        cur_date, ef_time_des, ef_venue, venues, slot_times, booked_slots,
        preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    stage1_times.append(ef_time)
    stage1_dates.append(ef_date)
    global_daily_counts[ef_date] += 1
    matches.append({
        'round_name': f"{prefix}Elimination Final (3rd vs 4th)".strip(),
        'round_number': 100,
        'group_name': "Knockout",
        'stage_name': "Elimination Final",
        'home_team': seed3,
        'away_team': seed4,
        'match_date': ef_date,
        'kickoff_time': ef_time,
        'venue': ef_ven,
        'is_knockout': True
    })

    # STAGE 2:
    # Match 3: Preliminary Final (Loser QF vs Winner EF)
    last_stage1_date = max(stage1_dates) if stage1_dates else cur_date
    prelim_date = _calc_next_stage_date(last_stage1_date, 2, end_date, preferred_weekdays)
    if prelim_date <= last_stage1_date and (not end_date or last_stage1_date < end_date):
        prelim_date = _find_next_preferred_date(last_stage1_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
    while global_daily_counts[prelim_date] >= matches_per_day:
        prelim_date = _find_next_preferred_date(prelim_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

    prelim_min_time = _add_time(max(stage1_times), 150) if prelim_date <= last_stage1_date else None
    prelim_home = {
        'id': None,
        'name': "Loser of Qualifying Final",
        'team_name': "Loser of Qualifying Final",
        'short_name': "L-QF",
        'seed_label': "Loser QF",
        'is_placeholder': True,
        'get_logo_url': lambda: ""
    }
    prelim_away = {
        'id': None,
        'name': "Winner of Elimination Final",
        'team_name': "Winner of Elimination Final",
        'short_name': "W-EF",
        'seed_label': "Winner EF",
        'is_placeholder': True,
        'get_logo_url': lambda: ""
    }
    pf_slot = global_daily_counts[prelim_date]
    pf_date, pf_time, pf_ven = _allocate_conflict_free_slot(
        prelim_date, slot_times[pf_slot % len(slot_times)], venues[pf_slot % len(venues)], venues, slot_times, booked_slots,
        min_time=prelim_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    global_daily_counts[pf_date] += 1
    matches.append({
        'round_name': f"{prefix}Preliminary Final".strip(),
        'round_number': 101,
        'group_name': "Knockout",
        'stage_name': "Preliminary Final",
        'home_team': prelim_home,
        'away_team': prelim_away,
        'match_date': pf_date,
        'kickoff_time': pf_time,
        'venue': pf_ven,
        'is_knockout': True
    })

    # STAGE 3:
    # Match 4: Grand Final (Winner QF vs Winner PF)
    final_date = _calc_next_stage_date(pf_date, 1, end_date, preferred_weekdays)
    if final_date <= pf_date and (not end_date or pf_date < end_date):
        final_date = _find_next_preferred_date(pf_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
    while global_daily_counts[final_date] >= matches_per_day:
        final_date = _find_next_preferred_date(final_date + timedelta(days=1), preferred_weekdays, max_date=end_date)

    final_min_time = _add_time(pf_time, 150) if final_date <= pf_date else None
    final_home = {
        'id': None,
        'name': "Winner of Qualifying Final",
        'team_name': "Winner of Qualifying Final",
        'short_name': "W-QF",
        'seed_label': "Winner QF",
        'is_placeholder': True,
        'get_logo_url': lambda: ""
    }
    final_away = {
        'id': None,
        'name': "Winner of Preliminary Final",
        'team_name': "Winner of Preliminary Final",
        'short_name': "W-PF",
        'seed_label': "Winner PF",
        'is_placeholder': True,
        'get_logo_url': lambda: ""
    }
    gf_slot = global_daily_counts[final_date]
    gf_date, gf_time, gf_ven = _allocate_conflict_free_slot(
        final_date, slot_times[gf_slot % len(slot_times)], venues[gf_slot % len(venues)], venues, slot_times, booked_slots,
        min_time=final_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    global_daily_counts[gf_date] += 1
    matches.append({
        'round_name': f"{prefix}Grand Final".strip(),
        'round_number': 102,
        'group_name': "Knockout",
        'stage_name': "Championship Final",
        'home_team': final_home,
        'away_team': final_away,
        'match_date': gf_date,
        'kickoff_time': gf_time,
        'venue': gf_ven,
        'is_knockout': True
    })

    return matches


def advance_knockout_bracket(competition):
    """
    Automatically advances winners and losers into subsequent knockout / playoff rounds
    (e.g., Page-McIntyre Preliminary Final & Grand Final, or Single Elimination Finals).
    Only updates matches that are currently SCHEDULED (not yet played).
    """
    matches = list(competition.matches.all())

    # 0. Group Stage & League Qualification Progression:
    # Promote qualified teams into knockout placeholder fixtures (e.g. "1st Group A", "2nd Group B", "1st Place")
    # when group stage matches conclude.
    if getattr(competition, 'is_group_stage', False) or competition.groups.exists():
        from standings.models import StandingEntry
        by_group_rank = {}
        for grp in competition.groups.all():
            grp_matches = competition.matches.filter(group=grp)
            if grp_matches.exists() and not grp_matches.exclude(status=MatchStatus.COMPLETED).exists():
                entries = list(StandingEntry.objects.filter(competition=competition, group=grp).order_by('position'))
                for r, e in enumerate(entries, start=1):
                    by_group_rank[(grp.name.lower(), r)] = e.team

        # For single group / league table
        if competition.groups.count() <= 1:
            all_grp_matches = competition.matches.filter(group__isnull=False) if competition.groups.exists() else competition.matches.filter(tournament_round__icontains='Matchweek')
            if all_grp_matches.exists() and not all_grp_matches.exclude(status=MatchStatus.COMPLETED).exists():
                entries = list(StandingEntry.objects.filter(competition=competition).order_by('position'))
                for r, e in enumerate(entries, start=1):
                    by_group_rank[('league', r)] = e.team

        for m in matches:
            if m.status == MatchStatus.SCHEDULED:
                updated_fields = []
                for side, f_ph, f_team in [('home', m.placeholder_home, 'home_team'), ('away', m.placeholder_away, 'away_team')]:
                    if f_ph and not getattr(m, f_team):
                        ph = f_ph.strip().lower()
                        target_rank = None
                        if ph.startswith('1st') or ph.startswith('winner') or '1st' in ph:
                            target_rank = 1
                        elif ph.startswith('2nd') or ph.startswith('runner') or '2nd' in ph:
                            target_rank = 2
                        elif ph.startswith('3rd') or '3rd' in ph:
                            target_rank = 3
                        elif ph.startswith('4th') or '4th' in ph:
                            target_rank = 4

                        matched_team = None
                        if target_rank:
                            for grp in competition.groups.all():
                                if grp.name.lower() in ph:
                                    matched_team = by_group_rank.get((grp.name.lower(), target_rank))
                                    break
                            if not matched_team and ('place' in ph or 'seed' in ph):
                                matched_team = by_group_rank.get(('league', target_rank))

                        if matched_team:
                            setattr(m, f_team, matched_team)
                            setattr(m, f"placeholder_{side}", '')
                            updated_fields.extend([f_team, f"placeholder_{side}"])
                if updated_fields:
                    m.save(update_fields=list(set(updated_fields)))

    # 1. Page-McIntyre Playoff Progression
    qf = next((m for m in matches if 'Qualifying Final' in m.tournament_round), None)
    ef = next((m for m in matches if 'Elimination Final' in m.tournament_round), None)
    pf = next((m for m in matches if 'Preliminary Final' in m.tournament_round), None)
    gf = next((m for m in matches if any(k in m.tournament_round for k in ['Grand Final', 'Grand Championship Final']) or m.tournament_round.strip() == 'Final'), None)

    if qf and qf.status == MatchStatus.COMPLETED and qf.winner:
        qf_winner = qf.winner
        qf_loser = qf.home_team if qf_winner.id == qf.away_team_id else qf.away_team

        # Winner of QF advances directly to Grand Final (Home)
        if gf and gf.status == MatchStatus.SCHEDULED and gf.home_team_id != qf_winner.id:
            gf.home_team = qf_winner
            gf.placeholder_home = ''
            gf.save(update_fields=['home_team', 'placeholder_home'])

        # Loser of QF advances to Preliminary Final (Home)
        if pf and pf.status == MatchStatus.SCHEDULED and pf.home_team_id != qf_loser.id:
            pf.home_team = qf_loser
            pf.placeholder_home = ''
            pf.save(update_fields=['home_team', 'placeholder_home'])

    if ef and ef.status == MatchStatus.COMPLETED and ef.winner:
        ef_winner = ef.winner
        # Winner of EF advances to Preliminary Final (Away)
        if pf and pf.status == MatchStatus.SCHEDULED and pf.away_team_id != ef_winner.id:
            pf.away_team = ef_winner
            pf.placeholder_away = ''
            pf.save(update_fields=['away_team', 'placeholder_away'])

    if pf and pf.status == MatchStatus.COMPLETED and pf.winner:
        pf_winner = pf.winner
        # Winner of PF advances to Grand Final (Away)
        if gf and gf.status == MatchStatus.SCHEDULED and gf.away_team_id != pf_winner.id:
            gf.away_team = pf_winner
            gf.placeholder_away = ''
            gf.save(update_fields=['away_team', 'placeholder_away'])

    # 2. General Knockout Progression by placeholder label matching across all rounds:
    rounds_dict = {}
    for m in matches:
        rounds_dict.setdefault(m.tournament_round, []).append(m)

    winner_labels = {}
    for r_name, r_matches in rounds_dict.items():
        sorted_m = sorted(r_matches, key=lambda x: (x.match_date, x.kickoff_time, x.id))
        for idx, m in enumerate(sorted_m, 1):
            if m.status == MatchStatus.COMPLETED and m.winner:
                clean_r_name = r_name.replace(' (Leg 1)', '').replace(' (Leg 2)', '').strip()
                lbls = [
                    f"winner of {clean_r_name} match {idx}",
                    f"winner of {clean_r_name} {idx}",
                ]
                if clean_r_name in ["Semi-Finals", "Semi-Final"]:
                    lbls.extend([
                        f"winner of semi-final {idx}",
                        f"winner of semi-finals {idx}",
                        f"winner of semi final {idx}",
                    ])
                elif clean_r_name in ["Quarter-Finals", "Quarter-Final"]:
                    lbls.extend([
                        f"winner of quarter-final {idx}",
                        f"winner of quarter-finals {idx}",
                        f"winner of quarter final {idx}",
                    ])
                elif clean_r_name.startswith("Round of"):
                    suffix = clean_r_name.replace("Round of ", "").strip()
                    lbls.extend([
                        f"winner of round of {suffix} match {idx}",
                        f"winner of round of {suffix} {idx}",
                    ])

                for l in lbls:
                    winner_labels[l.lower()] = m.winner

    for m in matches:
        if m.status == MatchStatus.SCHEDULED:
            updated_fields = []
            if m.placeholder_home:
                p_clean = m.placeholder_home.strip().lower()
                p_base = p_clean.replace(' (knockout)', '').strip()
                w = winner_labels.get(p_clean) or winner_labels.get(p_base)
                if w and m.home_team_id != w.id:
                    m.home_team = w
                    m.placeholder_home = ''
                    updated_fields.extend(['home_team', 'placeholder_home'])
            if m.placeholder_away:
                p_clean = m.placeholder_away.strip().lower()
                p_base = p_clean.replace(' (knockout)', '').strip()
                w = winner_labels.get(p_clean) or winner_labels.get(p_base)
                if w and m.away_team_id != w.id:
                    m.away_team = w
                    m.placeholder_away = ''
                    updated_fields.extend(['away_team', 'placeholder_away'])
            if updated_fields:
                m.save(update_fields=list(set(updated_fields)))

    # 3. Standard Single Elimination Positional Fallback
    # Quarter-Finals -> Semi-Finals
    qfs = [m for m in matches if 'Quarter-Final' in m.tournament_round and 'Semi' not in m.tournament_round]
    sfs = [m for m in matches if 'Semi-Final' in m.tournament_round and 'Qualifying' not in m.tournament_round and 'Elimination' not in m.tournament_round]

    if qfs and len(qfs) >= 4 and len(sfs) >= 2:
        qfs_sorted = sorted(qfs, key=lambda m: (m.match_date, m.kickoff_time, m.id))
        sfs_sorted = sorted(sfs, key=lambda m: (m.match_date, m.kickoff_time, m.id))
        sf1, sf2 = sfs_sorted[0], sfs_sorted[1]

        if qfs_sorted[0].status == MatchStatus.COMPLETED and qfs_sorted[0].winner and sf1.status == MatchStatus.SCHEDULED:
            if sf1.home_team_id != qfs_sorted[0].winner.id:
                sf1.home_team = qfs_sorted[0].winner
                sf1.placeholder_home = ''
                sf1.save(update_fields=['home_team', 'placeholder_home'])

        if qfs_sorted[1].status == MatchStatus.COMPLETED and qfs_sorted[1].winner and sf1.status == MatchStatus.SCHEDULED:
            if sf1.away_team_id != qfs_sorted[1].winner.id:
                sf1.away_team = qfs_sorted[1].winner
                sf1.placeholder_away = ''
                sf1.save(update_fields=['away_team', 'placeholder_away'])

        if qfs_sorted[2].status == MatchStatus.COMPLETED and qfs_sorted[2].winner and sf2.status == MatchStatus.SCHEDULED:
            if sf2.home_team_id != qfs_sorted[2].winner.id:
                sf2.home_team = qfs_sorted[2].winner
                sf2.placeholder_home = ''
                sf2.save(update_fields=['home_team', 'placeholder_home'])

        if qfs_sorted[3].status == MatchStatus.COMPLETED and qfs_sorted[3].winner and sf2.status == MatchStatus.SCHEDULED:
            if sf2.away_team_id != qfs_sorted[3].winner.id:
                sf2.away_team = qfs_sorted[3].winner
                sf2.placeholder_away = ''
                sf2.save(update_fields=['away_team', 'placeholder_away'])

    # Semi-Finals -> Grand Final
    if sfs and gf and gf.status == MatchStatus.SCHEDULED:
        sf_leg2s = [m for m in sfs if 'Leg 2' in m.tournament_round]
        if sf_leg2s and len(sf_leg2s) >= 2:
            tie1_leg2 = sf_leg2s[0]
            tie2_leg2 = sf_leg2s[1]
            tie1_leg1 = next((m for m in sfs if 'Leg 1' in m.tournament_round and {m.home_team_id, m.away_team_id} == {tie1_leg2.home_team_id, tie1_leg2.away_team_id}), None)
            tie2_leg1 = next((m for m in sfs if 'Leg 1' in m.tournament_round and {m.home_team_id, m.away_team_id} == {tie2_leg2.home_team_id, tie2_leg2.away_team_id}), None)

            def get_aggregate_winner(leg1, leg2):
                if not leg1 or not leg2: return None
                if leg1.status != MatchStatus.COMPLETED or leg2.status != MatchStatus.COMPLETED: return None
                team_a = leg1.home_team
                team_b = leg1.away_team
                score_a = (leg1.home_score or 0) + (leg2.away_score or 0)
                score_b = (leg1.away_score or 0) + (leg2.home_score or 0)
                if score_a > score_b: return team_a
                if score_b > score_a: return team_b
                return leg2.winner or leg1.winner or team_a

            w1 = get_aggregate_winner(tie1_leg1, tie1_leg2)
            w2 = get_aggregate_winner(tie2_leg1, tie2_leg2)
            if w1 and gf.home_team_id != w1.id:
                gf.home_team = w1
                gf.placeholder_home = ''
                gf.save(update_fields=['home_team', 'placeholder_home'])
            if w2 and gf.away_team_id != w2.id:
                gf.away_team = w2
                gf.placeholder_away = ''
                gf.save(update_fields=['away_team', 'placeholder_away'])
        elif len(sfs) >= 2:
            sfs_sorted = sorted(sfs, key=lambda m: (m.match_date, m.kickoff_time, m.id))
            sf1, sf2 = sfs_sorted[0], sfs_sorted[1]
            if sf1.status == MatchStatus.COMPLETED and sf1.winner:
                if gf.home_team_id != sf1.winner.id:
                    gf.home_team = sf1.winner
                    gf.placeholder_home = ''
                    gf.save(update_fields=['home_team', 'placeholder_home'])
            if sf2.status == MatchStatus.COMPLETED and sf2.winner:
                if gf.away_team_id != sf2.winner.id:
                    gf.away_team = sf2.winner
                    gf.placeholder_away = ''
                    gf.save(update_fields=['away_team', 'placeholder_away'])


def commit_generated_fixtures(
    competition,
    matches_data,
    groups_data=None,
    tournament_format=None,
    constraints=None,
    overwrite_locked=False,
    user=None,
    strategy='optimized',
    config_snapshot=None
):
    """
    Atomically writes previewed/edited fixtures into database Match and TournamentGroup records.
    - Validates the complete draft before publishing when constraints are provided.
    - Preserves COMPLETED, LIVE, and manually locked (is_locked=True) matches unless overwrite_locked=True.
    - Prevents duplicate fixture creation.
    - Records ScheduleGenerationLog for auditability.
    """
    if competition.is_completed:
        return []

    validation_errors = []
    validation_warnings = []
    if constraints:
        v_report = validate_complete_schedule(matches_data, constraints)
        validation_errors = v_report.get('errors', [])
        validation_warnings = v_report.get('warnings', [])
        if not v_report.get('is_valid'):
            ScheduleGenerationLog.objects.create(
                competition=competition,
                created_by=user,
                strategy=strategy,
                config_snapshot=config_snapshot or {},
                total_matches=len(matches_data),
                dates_used=len(set(m.get('match_date') for m in matches_data if m.get('match_date'))),
                is_valid=False,
                validation_errors=validation_errors,
                validation_warnings=validation_warnings,
            )
            raise ValueError("; ".join(validation_errors))

    with transaction.atomic():
        if tournament_format:
            if tournament_format in dict(TournamentFormat.choices):
                competition.tournament_format = tournament_format
                competition.save(update_fields=['tournament_format'])
            elif tournament_format == 'KNOCKOUT':
                competition.tournament_format = TournamentFormat.SINGLE_ELIMINATION
                competition.save(update_fields=['tournament_format'])

        # If pure knockout tournament, remove any existing standings entries
        if competition.is_pure_knockout:
            from standings.models import StandingEntry
            StandingEntry.objects.filter(competition=competition).delete()

        # Preserve COMPLETED, LIVE, and locked matches unless explicitly authorized
        if overwrite_locked:
            competition.matches.filter(status=MatchStatus.SCHEDULED).delete()
        else:
            competition.matches.filter(status=MatchStatus.SCHEDULED, is_locked=False).delete()

        existing_preserved = set()
        for em in competition.matches.all():
            if em.home_team_id and em.away_team_id:
                existing_preserved.add((em.home_team_id, em.away_team_id, em.leg, em.tournament_round))

        group_objects_map = {}
        if groups_data and isinstance(groups_data, dict):
            for g_name, g_teams in groups_data.items():
                grp, _ = TournamentGroup.objects.get_or_create(competition=competition, name=g_name)
                group_objects_map[g_name] = grp
                for t_info in g_teams:
                    t_id = t_info.get('id')
                    if t_id:
                        ct = CompetitionTeam.objects.filter(competition=competition, team_id=t_id).first()
                        if ct:
                            ct.group = grp
                            ct.save(update_fields=['group'])

        created_matches = []
        teams_cache = {t.id: t for t in competition.teams.all()}
        seen_in_batch = set()

        for m in matches_data:
            home_id = m.get('home_team_id')
            away_id = m.get('away_team_id')

            # Do not predict/pre-assign teams for future knockout placeholder fixtures
            is_placeholder_match = bool(m.get('is_placeholder') or m.get('is_knockout_future'))
            if is_placeholder_match or m.get('home_is_placeholder'):
                home_team = None
            else:
                home_team = (teams_cache.get(home_id) or Team.objects.filter(id=home_id).first()) if home_id else None

            if is_placeholder_match or m.get('away_is_placeholder'):
                away_team = None
            else:
                away_team = (teams_cache.get(away_id) or Team.objects.filter(id=away_id).first()) if away_id else None

            placeholder_home = ""
            if not home_team:
                placeholder_home = m.get('placeholder_home') or m.get('home_team_name') or 'TBD'

            placeholder_away = ""
            if not away_team:
                placeholder_away = m.get('placeholder_away') or m.get('away_team_name') or 'TBD'

            if not home_team and not placeholder_home:
                continue
            if not away_team and not placeholder_away:
                continue

            m_date = parse_date_safe(m.get('match_date'))
            k_time = parse_time_safe(m.get('kickoff_time'))
            venue = m.get('venue', 'Central Stadium')
            round_name = m.get('round_name', 'Scheduled Fixture')
            round_num = int(m.get('round_number', 1) or 1)
            leg_num = int(m.get('leg', 1) or 1)
            is_locked_flag = bool(m.get('is_locked', False))
            grp_name = m.get('group_name', '')

            if home_team and away_team:
                dedup_key = (home_team.id, away_team.id, leg_num, round_name)
                if dedup_key in existing_preserved or dedup_key in seen_in_batch:
                    continue
                seen_in_batch.add(dedup_key)

            grp_obj = group_objects_map.get(grp_name) if grp_name else None
            if not grp_obj and grp_name and grp_name != 'Knockout':
                grp_obj, _ = TournamentGroup.objects.get_or_create(competition=competition, name=grp_name)
                group_objects_map[grp_name] = grp_obj

            if grp_obj and grp_name != 'Knockout':
                if home_team:
                    CompetitionTeam.objects.filter(competition=competition, team_id=home_team.id).update(group=grp_obj)
                if away_team:
                    CompetitionTeam.objects.filter(competition=competition, team_id=away_team.id).update(group=grp_obj)

            round_byes = m.get('round_byes', [])
            notes_str = ""
            if round_byes:
                notes_str = json.dumps({'byes': [b if isinstance(b, str) else b.get('name', '') for b in round_byes]})

            match_obj = Match.objects.create(
                competition=competition,
                tournament_round=round_name,
                round_number=round_num,
                leg=leg_num,
                is_locked=is_locked_flag,
                group=grp_obj,
                home_team=home_team,
                away_team=away_team,
                placeholder_home=placeholder_home,
                placeholder_away=placeholder_away,
                match_date=m_date,
                kickoff_time=k_time,
                venue=venue,
                status=MatchStatus.SCHEDULED,
                notes=notes_str
            )
            created_matches.append(match_obj)

        if competition.status == CompetitionStatus.UPCOMING:
            competition.status = CompetitionStatus.ACTIVE
            competition.save(update_fields=['status'])

        ScheduleGenerationLog.objects.create(
            competition=competition,
            created_by=user,
            strategy=strategy,
            config_snapshot=config_snapshot or {},
            total_matches=len(created_matches),
            dates_used=len(set(cm.match_date for cm in created_matches if cm.match_date)),
            is_valid=True,
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
        )

        return created_matches
