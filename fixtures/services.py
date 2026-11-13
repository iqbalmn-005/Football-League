"""
Fixtures application services - Streamlined Fixture Scheduling & Generation Engine for Touchline.
Automatically includes all league teams, divides groups equally, and schedules fixtures
by user-specified matches per day and daily slot kickoff times.
"""
from datetime import timedelta, date, time, datetime
import json
from django.db import transaction
from matches.models import Match, MatchStatus
from leagues.models import Competition, TournamentGroup, CompetitionTeam, TournamentFormat, CompetitionStatus
from teams.models import Team

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


def generate_round_robin_fixtures(competition, start_date=None, double_round=False):
    """
    Standard round-robin generator wrapper.
    """
    config = {
        'tournament_format': TournamentFormat.ROUND_ROBIN,
        'start_date': start_date or competition.start_date or date.today(),
        'round_robin_type': 'double' if double_round else 'single',
        'matches_per_day': 2,
        'daily_kickoff_times': ["15:00", "17:30"],
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
    matches_per_day = int(config.get('matches_per_day', 2) or 2)
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

    # Build pairings by format
    groups_info = {}
    scheduled_matches = []
    booked_slots = set()

    if format_type in [TournamentFormat.PAGE_MCINTYRE, 'PAGE_MCINTYRE'] or (format_type in [TournamentFormat.SINGLE_ELIMINATION, 'KNOCKOUT'] and knockout_system == 'page_mcintyre'):
        if len(teams_qs) < 4:
            return {
                'success': False,
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
            matches_per_day=matches_per_day
        )
        scheduled_matches.extend(knockout_matches)

    elif format_type == TournamentFormat.ROUND_ROBIN or format_type == 'ROUND_ROBIN':
        raw_rounds = _build_round_robin_rounds(teams_qs, double_round=(round_robin_type == 'double'))
        scheduled_matches = _schedule_daily_slots(
            rounds=raw_rounds,
            start_date=start_date,
            preferred_weekdays=preferred_weekdays,
            matches_per_day=matches_per_day,
            slot_times=slot_times,
            venues=venues,
            end_date=end_date,
            booked_slots=booked_slots
        )

    elif format_type in [TournamentFormat.GROUP_KNOCKOUT, 'GROUP_KNOCKOUT', TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT']:
        is_league_knockout = (format_type in [TournamentFormat.LEAGUE_KNOCKOUT, 'LEAGUE_KNOCKOUT'])
        num_groups = 1 if is_league_knockout else int(config.get('num_groups', 2) or 2)
        default_q = 4 if is_league_knockout else 2
        q_per_group = int(config.get('qualifiers_per_group', default_q) or default_q)
        groups_dict = _allocate_groups_equally(teams_qs, num_groups)
        groups_info = {
            g_name: [{'id': t.id, 'name': t.name, 'short_name': t.short_name, 'logo_url': t.get_logo_url()} for t in t_list]
            for g_name, t_list in groups_dict.items()
        }

        # Build group / league stage rounds
        all_group_rounds = []
        for g_name, g_teams in groups_dict.items():
            round_prefix = "" if num_groups == 1 else f"{g_name} - "
            g_rounds = _build_round_robin_rounds(g_teams, double_round=(round_robin_type == 'double'), prefix=round_prefix)
            all_group_rounds.append((g_name, g_rounds))

        merged_rounds = _merge_concurrent_group_rounds(all_group_rounds)

        total_qualifiers = num_groups * q_per_group
        use_page_mcintyre = (knockout_system == 'page_mcintyre')

        # Apportion timeline between group stage and knockout stage
        if use_page_mcintyre:
            ko_rounds_count = 3  # Stage 1: QF & EF, Stage 2: Prelim Final, Stage 3: Grand Final
        elif total_qualifiers <= 2:
            ko_rounds_count = 1
        elif total_qualifiers <= 4:
            ko_rounds_count = 3 if two_legged_ko else 2
        elif total_qualifiers <= 8:
            ko_rounds_count = 5 if two_legged_ko else 3
        else:
            ko_rounds_count = 7 if two_legged_ko else 4

        num_group_rounds = len(merged_rounds)
        total_stages = num_group_rounds + ko_rounds_count

        if end_date:
            total_days = max(1, (end_date - start_date).days)
            if (total_stages - 1) * 7 <= total_days:
                group_end_target = start_date + timedelta(days=num_group_rounds * 7)
            else:
                group_days = max(1, (total_days * num_group_rounds) // total_stages)
                group_end_target = min(start_date + timedelta(days=group_days), end_date - timedelta(days=max(1, ko_rounds_count)))
        else:
            group_end_target = None

        group_matches = _schedule_daily_slots(
            rounds=merged_rounds,
            start_date=start_date,
            preferred_weekdays=preferred_weekdays,
            matches_per_day=matches_per_day,
            slot_times=slot_times,
            venues=venues,
            end_date=group_end_target,
            booked_slots=booked_slots
        )
        scheduled_matches.extend(group_matches)

        # Knockout Stage following the group stage
        last_group_date = max([m['match_date'] for m in group_matches], default=start_date)
        if end_date:
            days_left = max(1, (end_date - last_group_date).days)
            ko_step = 7 if ko_rounds_count * 7 <= days_left else max(1, days_left // max(1, ko_rounds_count + 1))
            ko_start_target = min(last_group_date + timedelta(days=ko_step), end_date)
            knockout_start_date = _find_next_preferred_date(ko_start_target, preferred_weekdays, max_date=end_date)
            if knockout_start_date <= last_group_date and end_date > last_group_date:
                knockout_start_date = last_group_date + timedelta(days=1)
        else:
            knockout_start_date = _find_next_preferred_date(last_group_date + timedelta(days=7), preferred_weekdays)

        if use_page_mcintyre:
            if num_groups == 1:
                q_teams = groups_dict[list(groups_dict.keys())[0]][:4]
            elif num_groups == 2:
                g_keys = sorted(list(groups_dict.keys()))
                gA = groups_dict[g_keys[0]]
                gB = groups_dict[g_keys[1]]
                q_teams = [
                    gA[0] if len(gA) > 0 else None,
                    gB[0] if len(gB) > 0 else None,
                    gA[1] if len(gA) > 1 else None,
                    gB[1] if len(gB) > 1 else None,
                ]
            else:
                g_keys = sorted(list(groups_dict.keys()))
                q_teams = [groups_dict[g_keys[i]][0] if len(groups_dict[g_keys[i]]) > 0 else None for i in range(min(4, len(g_keys)))]
            knockout_matches = _generate_page_mcintyre_fixtures(
                teams=q_teams,
                start_date=knockout_start_date,
                preferred_weekdays=preferred_weekdays,
                slot_times=slot_times,
                venues=venues,
                end_date=end_date,
                booked_slots=booked_slots,
                matches_per_day=matches_per_day
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
                matches_per_day=matches_per_day
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
            matches_per_day=matches_per_day
        )
        scheduled_matches.extend(knockout_matches)

    # FINAL SAFETY GUARANTEE: Under no circumstances do fixtures exceed end_date
    if end_date:
        for m in scheduled_matches:
            if m['match_date'] > end_date:
                m['match_date'] = end_date

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
        'format_name': fmt_label,
        'matches_per_day': matches_per_day,
        'group_count': len(groups_info) if groups_info else 0,
        'venues_used': len(set(m['venue'] for m in scheduled_matches)),
        'byes_by_round': {m['round_name']: m['round_byes'] for m in scheduled_matches if m.get('round_byes')},
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
            'round_name': m['round_name'],
            'round_number': m.get('round_number', 1),
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
            'round_byes': m.get('round_byes', [])
        })

    return {
        'success': True,
        'summary': summary,
        'groups': groups_info,
        'matches': formatted_matches,
        'errors': []
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
    Finds earliest date on or after start_from that matches preferred weekdays,
    strictly capped by max_date if specified.
    """
    cur = start_from
    for _ in range(365):
        if max_date and cur > max_date:
            return max_date
        if cur.weekday() in preferred_weekdays:
            return cur
        cur += timedelta(days=1)
    return min(start_from, max_date) if max_date else start_from


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

        # If all existing slots are booked on cur_date, try generating another evening slot
        last_t = valid_times[-1] if valid_times else time(15, 0)
        extra_t = _add_time(last_t, 150)
        if extra_t <= time(21, 30):
            available_slot_times.append(extra_t)
            continue

        # If day is full, advance to next day
        cand_date = cur_date + timedelta(days=1)
        if end_date and cand_date > end_date:
            cur_date = end_date
            extra_t = _add_time(last_t, 150)
            slot_key = (cur_date, extra_t, all_venues[0])
            booked_slots.add(slot_key)
            return cur_date, extra_t, all_venues[0]

        if preferred_weekdays:
            cur_date = _find_next_preferred_date(cand_date, preferred_weekdays, max_date=end_date)
        else:
            cur_date = cand_date
        min_time = None
        available_slot_times = list(slot_times) if slot_times else [time(15, 0)]

    booked_slots.add((cur_date, desired_time, desired_venue))
    return cur_date, desired_time, desired_venue


def _calc_next_stage_date(current_stage_date, stages_remaining, end_date, preferred_weekdays):
    """
    Calculates the next stage target date so all remaining stages fit before end_date.
    Guarantees next stage is on a subsequent date (> current_stage_date) whenever end_date allows.
    """
    if not end_date:
        return _find_next_preferred_date(current_stage_date + timedelta(days=7), preferred_weekdays)
    
    if end_date <= current_stage_date:
        return current_stage_date

    earliest_next = current_stage_date + timedelta(days=1)
    days_left = (end_date - current_stage_date).days

    if stages_remaining * 7 <= days_left:
        step = 7
    else:
        step = max(1, days_left // max(1, stages_remaining))

    target = min(current_stage_date + timedelta(days=step), end_date)
    nxt = _find_next_preferred_date(target, preferred_weekdays, max_date=end_date)
    if nxt <= current_stage_date:
        nxt = earliest_next
    return min(nxt, end_date)


def _schedule_daily_slots(rounds, start_date, preferred_weekdays, matches_per_day, slot_times, venues, end_date=None, booked_slots=None):
    """
    Schedules matches into daily capacity slots using user-defined kickoff times.
    Guarantees no team plays multiple matches on the same date and no match date exceeds end_date.
    """
    if booked_slots is None:
        booked_slots = set()

    scheduled = []
    current_date = _find_next_preferred_date(start_date, preferred_weekdays, max_date=end_date)
    daily_slot_index = 0
    teams_played_on_date = set()
    num_rounds = len(rounds)

    for r_idx, r in enumerate(rounds):
        round_name = r['round_name']
        round_num = r.get('round_number', 1)

        pairs = r.get('pairs') or [(item[0], item[1]) for item in r.get('pairs_with_group', [])]
        groups_tag = [item[2] if len(item) > 2 else '' for item in r.get('pairs_with_group', [])]

        for p_idx, (home, away) in enumerate(pairs):
            g_tag = groups_tag[p_idx] if p_idx < len(groups_tag) else ''

            # If either team already played today or daily slots full, advance to next matchday
            if (home.id in teams_played_on_date) or (away.id in teams_played_on_date) or (daily_slot_index >= matches_per_day):
                advance_cand = current_date + timedelta(days=1)
                if end_date and advance_cand > end_date:
                    advance_cand = end_date
                current_date = _find_next_preferred_date(advance_cand, preferred_weekdays, max_date=end_date)
                daily_slot_index = 0
                teams_played_on_date = set()

            # Assign time according to current slot index
            desired_time = slot_times[daily_slot_index % len(slot_times)]
            desired_venue = getattr(home, 'home_venue', '') or venues[daily_slot_index % len(venues)]
            match_d = min(current_date, end_date) if end_date else current_date

            final_d, final_t, final_v = _allocate_conflict_free_slot(
                match_d, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )

            scheduled.append({
                'round_name': round_name,
                'round_number': round_num,
                'group_name': g_tag,
                'home_team': home,
                'away_team': away,
                'match_date': final_d,
                'kickoff_time': final_t,
                'venue': final_v,
                'is_knockout': False
            })

            teams_played_on_date.add(home.id)
            teams_played_on_date.add(away.id)
            daily_slot_index += 1

        # Advance current_date for the next matchweek
        if r_idx < num_rounds - 1:
            if end_date:
                rounds_remaining = num_rounds - r_idx - 1
                days_remaining = max(1, (end_date - current_date).days)
                if rounds_remaining * 7 <= days_remaining:
                    step_days = 7
                else:
                    step_days = max(1, days_remaining // (rounds_remaining + 1))
                next_target = min(current_date + timedelta(days=step_days), end_date)
                current_date = _find_next_preferred_date(next_target, preferred_weekdays, max_date=end_date)
                if current_date > end_date:
                    current_date = end_date
            else:
                next_week_target = current_date + timedelta(days=7)
                current_date = _find_next_preferred_date(next_week_target, preferred_weekdays)

            daily_slot_index = 0
            teams_played_on_date = set()

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


def _generate_knockout_stage_for_groups(groups_dict, start_date, preferred_weekdays, slot_times, venues, qualifiers_per_group=2, two_legged=False, end_date=None, booked_slots=None, matches_per_day=2):
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

    knockout_matches = []
    group_names = sorted(list(groups_dict.keys()))
    num_groups = len(group_names)
    cur_date = _find_next_preferred_date(start_date, preferred_weekdays, max_date=end_date)
    if end_date and cur_date > end_date:
        cur_date = end_date

    max_teams = max((len(t) for t in groups_dict.values()), default=1)
    q_per_group = max(1, min(int(qualifiers_per_group or 2), max_teams))

    seeds = {}
    for g in group_names:
        g_teams = groups_dict[g]
        seeds[g] = []
        for q in range(q_per_group):
            suf = {1: 'st', 2: 'nd', 3: 'rd'}.get(q + 1, 'th')
            rank_str = f"{q + 1}{suf} Place" if num_groups == 1 else f"{q + 1}{suf} {g}"
            if q < len(g_teams):
                t = g_teams[q]
                seeds[g].append({
                    'id': t.id,
                    'name': f"{rank_str} ({t.name})",
                    'seed_label': rank_str,
                    'team_name': t.name,
                    'short_name': t.short_name,
                    'get_logo_url': t.get_logo_url,
                    'home_venue': getattr(t, 'home_venue', '')
                })
            else:
                fallback_t = g_teams[-1] if g_teams else None
                seeds[g].append({
                    'id': fallback_t.id if fallback_t else None,
                    'name': rank_str,
                    'seed_label': rank_str,
                    'team_name': rank_str,
                    'short_name': f"P{q + 1}" if num_groups == 1 else f"{q + 1}{g[-1]}",
                    'get_logo_url': fallback_t.get_logo_url if fallback_t else (lambda: ""),
                    'home_venue': getattr(fallback_t, 'home_venue', '') if fallback_t else ''
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

        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            cur_date, slot_times[0], home.get('home_venue') or venues[0], venues, slot_times, booked_slots,
            preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 100,
            'group_name': "Knockout",
            'home_team': home,
            'away_team': away,
            'match_date': f_date,
            'kickoff_time': f_time,
            'venue': f_ven,
            'is_knockout': True
        })
        return knockout_matches

    # CASE B: 4 TOTAL QUALIFIERS -> Semi-Finals (2 matches) -> Grand Championship Final (1 match)
    if total_q == 4:
        if num_groups == 2:
            # Classic 1A vs 2B and 1B vs 2A cross-pairing
            sf1 = (seeds['Group A'][0], seeds['Group B'][1])
            sf2 = (seeds['Group B'][0], seeds['Group A'][1])
        elif num_groups == 4:
            sf1 = (seeds['Group A'][0], seeds['Group B'][0])
            sf2 = (seeds['Group C'][0], seeds['Group D'][0])
        else:
            # 1 Group with top 4 qualifiers: 1st vs 4th, 2nd vs 3rd
            sf1 = (seeds['Group A'][0], seeds['Group A'][3])
            sf2 = (seeds['Group A'][1], seeds['Group A'][2])

        sf_pairs = [sf1, sf2]
        sf_times = []
        daily_match_count = 0
        for idx, (h, a) in enumerate(sf_pairs):
            if daily_match_count >= matches_per_day:
                next_cand = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
                if next_cand > cur_date:
                    days_avail = _count_preferred_days(next_cand, end_date, preferred_weekdays)
                    rem_sf = len(sf_pairs) - idx
                    days_needed_sf = (rem_sf + matches_per_day - 1) // matches_per_day
                    subsequent_days = 1 * (2 if two_legged else 1)
                    if days_avail >= (days_needed_sf + subsequent_days):
                        cur_date = next_cand
                        daily_match_count = 0
                        sf_times = []

            desired_time = slot_times[daily_match_count % len(slot_times)]
            desired_venue = h.get('home_venue') or venues[daily_match_count % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            sf_times.append(k_time)
            daily_match_count += 1
            knockout_matches.append({
                'round_name': "Semi-Finals" if not two_legged else "Semi-Finals (Leg 1)",
                'round_number': 100,
                'group_name': "Knockout",
                'home_team': h,
                'away_team': a,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        if two_legged:
            leg2_date = _calc_next_stage_date(cur_date, 2, end_date, preferred_weekdays)
            leg2_times = []
            for idx, (h, a) in enumerate(sf_pairs):
                desired_time = slot_times[idx % len(slot_times)]
                desired_venue = a.get('home_venue') or venues[(idx + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    leg2_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                leg2_times.append(l2_time)
                knockout_matches.append({
                    'round_name': "Semi-Finals (Leg 2)",
                    'round_number': 100,
                    'group_name': "Knockout",
                    'home_team': a,
                    'away_team': h,
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
                    'is_knockout': True
                })
            final_date = _calc_next_stage_date(leg2_date, 1, end_date, preferred_weekdays)
            min_time = _add_time(max(leg2_times), 150) if final_date <= leg2_date else None
        else:
            final_date = _calc_next_stage_date(cur_date, 1, end_date, preferred_weekdays)
            min_time = _add_time(max(sf_times), 150) if final_date <= cur_date else None

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
        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            final_date, slot_times[0], venues[0], venues, slot_times, booked_slots,
            min_time=min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 101,
            'group_name': "Knockout",
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
            qf1 = (seeds['Group A'][1], seeds['Group B'][2])  # 2A vs 3B
            qf2 = (seeds['Group B'][1], seeds['Group A'][2])  # 2B vs 3A
            bye1 = seeds['Group A'][0]
            bye2 = seeds['Group B'][0]
        else:
            # 1 Group: 1st & 2nd bye to SF; 3rd vs 6th & 4th vs 5th in QF
            qf1 = (seeds['Group A'][2], seeds['Group A'][5])
            qf2 = (seeds['Group A'][3], seeds['Group A'][4])
            bye1 = seeds['Group A'][0]
            bye2 = seeds['Group A'][1]

        qf_pairs = [qf1, qf2]
        qf_times = []
        for idx, (h, a) in enumerate(qf_pairs):
            desired_time = slot_times[idx % len(slot_times)]
            desired_venue = h.get('home_venue') or venues[idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            qf_times.append(k_time)
            knockout_matches.append({
                'round_name': "Play-In / Quarter-Finals" if not two_legged else "Play-In / Quarter-Finals (Leg 1)",
                'round_number': 100,
                'group_name': "Knockout",
                'home_team': h,
                'away_team': a,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        if two_legged:
            qf_leg2_date = _calc_next_stage_date(cur_date, 4, end_date, preferred_weekdays)
            qf_l2_times = []
            for idx, (h, a) in enumerate(qf_pairs):
                desired_time = slot_times[idx % len(slot_times)]
                desired_venue = a.get('home_venue') or venues[(idx + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    qf_leg2_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                qf_l2_times.append(l2_time)
                knockout_matches.append({
                    'round_name': "Play-In / Quarter-Finals (Leg 2)",
                    'round_number': 100,
                    'group_name': "Knockout",
                    'home_team': a,
                    'away_team': h,
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
                    'is_knockout': True
                })
            sf_date = _calc_next_stage_date(qf_leg2_date, 3, end_date, preferred_weekdays)
            sf_min_time = _add_time(max(qf_l2_times), 150) if sf_date <= qf_leg2_date else None
        else:
            sf_date = _calc_next_stage_date(cur_date, 2, end_date, preferred_weekdays)
            sf_min_time = _add_time(max(qf_times), 150) if sf_date <= cur_date else None

        sf1_away = {
            'id': None,
            'name': "Winner of Play-In 1",
            'team_name': "Winner of Play-In 1",
            'short_name': "W-PI1",
            'seed_label': "Winner of Play-In 1",
            'is_placeholder': True,
            'get_logo_url': lambda: ""
        }
        sf2_away = {
            'id': None,
            'name': "Winner of Play-In 2",
            'team_name': "Winner of Play-In 2",
            'short_name': "W-PI2",
            'seed_label': "Winner of Play-In 2",
            'is_placeholder': True,
            'get_logo_url': lambda: ""
        }
        sf_ties = [(bye1, sf1_away), (bye2, sf2_away)]
        sf_times = []

        for idx, (h, a) in enumerate(sf_ties):
            desired_time = slot_times[idx % len(slot_times)]
            desired_venue = (h.get('home_venue') if isinstance(h, dict) else getattr(h, 'home_venue', '')) or venues[idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                sf_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                min_time=sf_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            sf_times.append(k_time)
            knockout_matches.append({
                'round_name': "Semi-Finals" if not two_legged else "Semi-Finals (Leg 1)",
                'round_number': 101,
                'group_name': "Knockout",
                'home_team': h,
                'away_team': a,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        if two_legged:
            sf_leg2_date = _calc_next_stage_date(sf_date, 2, end_date, preferred_weekdays)
            sf_l2_times = []
            for idx, (h, a) in enumerate(sf_ties):
                desired_time = slot_times[idx % len(slot_times)]
                desired_venue = venues[(idx + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    sf_leg2_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                sf_l2_times.append(l2_time)
                knockout_matches.append({
                    'round_name': "Semi-Finals (Leg 2)",
                    'round_number': 101,
                    'group_name': "Knockout",
                    'home_team': a,
                    'away_team': h,
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
                    'is_knockout': True
                })
            final_date = _calc_next_stage_date(sf_leg2_date, 1, end_date, preferred_weekdays)
            final_min_time = _add_time(max(sf_l2_times), 150) if final_date <= sf_leg2_date else None
        else:
            final_date = _calc_next_stage_date(sf_date, 1, end_date, preferred_weekdays)
            final_min_time = _add_time(max(sf_times), 150) if final_date <= sf_date else None

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
        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            final_date, slot_times[0], venues[0], venues, slot_times, booked_slots,
            min_time=final_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 102,
            'group_name': "Knockout",
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
            qfs = [
                (seeds['Group A'][0], seeds['Group B'][1]),  # 1A vs 2B
                (seeds['Group C'][0], seeds['Group D'][1]),  # 1C vs 2D
                (seeds['Group B'][0], seeds['Group A'][1]),  # 1B vs 2A
                (seeds['Group D'][0], seeds['Group C'][1]),  # 1D vs 2C
            ]
        elif num_groups == 2:
            qfs = [
                (seeds['Group A'][0], seeds['Group B'][3]),  # 1A vs 4B
                (seeds['Group A'][1], seeds['Group B'][2]),  # 2A vs 3B
                (seeds['Group B'][0], seeds['Group A'][3]),  # 1B vs 4A
                (seeds['Group B'][1], seeds['Group A'][2]),  # 2B vs 3A
            ]
        else:
            qfs = [
                (seeds['Group A'][0], seeds['Group A'][7]),
                (seeds['Group A'][1], seeds['Group A'][6]),
                (seeds['Group A'][2], seeds['Group A'][5]),
                (seeds['Group A'][3], seeds['Group A'][4]),
            ]

        qf_times = []
        daily_match_count = 0
        for idx, (h, a) in enumerate(qfs):
            if daily_match_count >= matches_per_day:
                next_cand = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
                if next_cand > cur_date:
                    days_avail = _count_preferred_days(next_cand, end_date, preferred_weekdays)
                    rem_qf = len(qfs) - idx
                    days_needed_qf = (rem_qf + matches_per_day - 1) // matches_per_day
                    subsequent_days = 2 * (2 if two_legged else 1)
                    if days_avail >= (days_needed_qf + subsequent_days):
                        cur_date = next_cand
                        daily_match_count = 0
                        qf_times = []

            desired_time = slot_times[daily_match_count % len(slot_times)]
            desired_venue = h.get('home_venue') or venues[daily_match_count % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            qf_times.append(k_time)
            daily_match_count += 1
            knockout_matches.append({
                'round_name': "Quarter-Finals" if not two_legged else "Quarter-Finals (Leg 1)",
                'round_number': 100,
                'group_name': "Knockout",
                'home_team': h,
                'away_team': a,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        if two_legged:
            qf_leg2_date = _calc_next_stage_date(cur_date, 4, end_date, preferred_weekdays)
            qf_l2_times = []
            for idx, (h, a) in enumerate(qfs):
                desired_time = slot_times[idx % len(slot_times)]
                desired_venue = a.get('home_venue') or venues[(idx + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    qf_leg2_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                qf_l2_times.append(l2_time)
                knockout_matches.append({
                    'round_name': "Quarter-Finals (Leg 2)",
                    'round_number': 100,
                    'group_name': "Knockout",
                    'home_team': a,
                    'away_team': h,
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
                    'is_knockout': True
                })
            sf_date = _calc_next_stage_date(qf_leg2_date, 3, end_date, preferred_weekdays)
            sf_min_time = _add_time(max(qf_l2_times), 150) if sf_date <= qf_leg2_date else None
        else:
            sf_date = _calc_next_stage_date(cur_date, 2, end_date, preferred_weekdays)
            sf_min_time = _add_time(max(qf_times), 150) if sf_date <= cur_date else None

        sf1_home = {'id': None, 'name': "Winner of Quarter-Final 1", 'team_name': "Winner of Quarter-Final 1", 'short_name': "W-QF1", 'seed_label': "Winner of QF 1", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf1_away = {'id': None, 'name': "Winner of Quarter-Final 2", 'team_name': "Winner of Quarter-Final 2", 'short_name': "W-QF2", 'seed_label': "Winner of QF 2", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf2_home = {'id': None, 'name': "Winner of Quarter-Final 3", 'team_name': "Winner of Quarter-Final 3", 'short_name': "W-QF3", 'seed_label': "Winner of QF 3", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf2_away = {'id': None, 'name': "Winner of Quarter-Final 4", 'team_name': "Winner of Quarter-Final 4", 'short_name': "W-QF4", 'seed_label': "Winner of QF 4", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        sf_ties = [(sf1_home, sf1_away), (sf2_home, sf2_away)]
        sf_times = []

        for idx, (h, a) in enumerate(sf_ties):
            desired_time = slot_times[idx % len(slot_times)]
            desired_venue = venues[idx % len(venues)]
            m_date, k_time, v_name = _allocate_conflict_free_slot(
                sf_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                min_time=sf_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            sf_times.append(k_time)
            knockout_matches.append({
                'round_name': "Semi-Finals" if not two_legged else "Semi-Finals (Leg 1)",
                'round_number': 101,
                'group_name': "Knockout",
                'home_team': h,
                'away_team': a,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

        if two_legged:
            sf_leg2_date = _calc_next_stage_date(sf_date, 2, end_date, preferred_weekdays)
            sf_l2_times = []
            for idx, (h, a) in enumerate(sf_ties):
                desired_time = slot_times[idx % len(slot_times)]
                desired_venue = venues[(idx + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    sf_leg2_date, desired_time, desired_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                sf_l2_times.append(l2_time)
                knockout_matches.append({
                    'round_name': "Semi-Finals (Leg 2)",
                    'round_number': 101,
                    'group_name': "Knockout",
                    'home_team': a,
                    'away_team': h,
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
                    'is_knockout': True
                })
            final_date = _calc_next_stage_date(sf_leg2_date, 1, end_date, preferred_weekdays)
            final_min_time = _add_time(max(sf_l2_times), 150) if final_date <= sf_leg2_date else None
        else:
            final_date = _calc_next_stage_date(sf_date, 1, end_date, preferred_weekdays)
            final_min_time = _add_time(max(sf_times), 150) if final_date <= sf_date else None

        final_home = {'id': None, 'name': "Winner of Semi-Final 1", 'team_name': "Winner of Semi-Final 1", 'short_name': "W-SF1", 'seed_label': "Winner of Semi-Final 1", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        final_away = {'id': None, 'name': "Winner of Semi-Final 2", 'team_name': "Winner of Semi-Final 2", 'short_name': "W-SF2", 'seed_label': "Winner of Semi-Final 2", 'is_placeholder': True, 'get_logo_url': lambda: ""}
        f_date, f_time, f_ven = _allocate_conflict_free_slot(
            final_date, slot_times[0], venues[0], venues, slot_times, booked_slots,
            min_time=final_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
        )
        knockout_matches.append({
            'round_name': "Grand Championship Final",
            'round_number': 102,
            'group_name': "Knockout",
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

        min_time = None
        if prev_stage_date and cur_date <= prev_stage_date and prev_stage_latest_time:
            min_time = _add_time(prev_stage_latest_time, 150)

        cur_stage_times = []
        for i in range(half):
            t1 = cur_teams[i]
            t2 = cur_teams[n - 1 - i]

            desired_time = slot_times[i % len(slot_times)]
            t1_venue = (t1.get('home_venue') if isinstance(t1, dict) else getattr(t1, 'home_venue', '')) or venues[i % len(venues)]

            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, t1_venue, venues, slot_times, booked_slots,
                min_time=min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            cur_stage_times.append(k_time)

            knockout_matches.append({
                'round_name': stage_name if not stage_two_legged else f"{stage_name} (Leg 1)",
                'round_number': stage_idx,
                'group_name': "Knockout",
                'home_team': t1,
                'away_team': t2,
                'match_date': m_date,
                'kickoff_time': k_time,
                'venue': v_name,
                'is_knockout': True
            })

            if stage_two_legged:
                leg2_date = _calc_next_stage_date(cur_date, max(1, half * 2), end_date, preferred_weekdays)
                t2_venue = (t2.get('home_venue') if isinstance(t2, dict) else getattr(t2, 'home_venue', '')) or venues[(i + 1) % len(venues)]
                l2_date, l2_time, l2_ven = _allocate_conflict_free_slot(
                    leg2_date, desired_time, t2_venue, venues, slot_times, booked_slots,
                    preferred_weekdays=preferred_weekdays, end_date=end_date
                )
                knockout_matches.append({
                    'round_name': f"{stage_name} (Leg 2)",
                    'round_number': stage_idx,
                    'group_name': "Knockout",
                    'home_team': t2,
                    'away_team': t1,
                    'match_date': l2_date,
                    'kickoff_time': l2_time,
                    'venue': l2_ven,
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


def _generate_single_elimination_bracket(teams, start_date, preferred_weekdays, slot_times, venues, two_legged=False, end_date=None, booked_slots=None, matches_per_day=2):
    """
    Generates single elimination knockout bracket for pure knockout tournaments,
    guaranteed to conclude on or before end_date.
    Implements a distributed BYE system (max 3 BYEs per round, starting from Round 1,
    0 BYEs in SF/Final) when team count is not a power of 2.
    Ensures subsequent rounds use placeholder seeds, conflict-free venues,
    and sequential timing adhering to matches_per_day capacity.
    """
    if booked_slots is None:
        booked_slots = set()

    matches = []
    n = len(teams)
    if n < 2:
        return []

    cur_teams = list(teams)
    cur_date = _find_next_preferred_date(start_date, preferred_weekdays, max_date=end_date)
    if end_date and cur_date > end_date:
        cur_date = end_date

    plan = plan_knockout_byes(n)
    stage_names = get_knockout_stage_names(n, plan)

    prev_stage_date = None
    prev_stage_latest_time = None

    for stage_idx, step in enumerate(plan):
        stage_name = stage_names[stage_idx]
        b_count = step['byes']
        m_count = step['matches']
        is_final = (stage_name == "Final" or stage_idx == len(plan) - 1)
        stage_two_legged = (two_legged and not is_final)

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
        daily_match_count = 0

        for i in range(m_count):
            t1 = playing_teams[i]
            t2 = playing_teams[len(playing_teams) - 1 - i]

            # If daily match capacity reached, advance to next matchday if calendar permits
            if daily_match_count >= matches_per_day:
                next_cand = _find_next_preferred_date(cur_date + timedelta(days=1), preferred_weekdays, max_date=end_date)
                if next_cand > cur_date:
                    days_avail = _count_preferred_days(next_cand, end_date, preferred_weekdays)
                    rem_matches_this_stage = m_count - i
                    days_needed_this_stage = (rem_matches_this_stage + matches_per_day - 1) // matches_per_day
                    subsequent_stages_count = len(stage_names) - stage_idx - 1
                    days_needed_subsequent = subsequent_stages_count * (2 if stage_two_legged else 1)
                    if days_avail >= (days_needed_this_stage + days_needed_subsequent):
                        cur_date = next_cand
                        daily_match_count = 0
                        min_time = None
                        current_stage_times = []

            desired_time = slot_times[daily_match_count % len(slot_times)]
            t1_venue = (t1.get('home_venue') if isinstance(t1, dict) else getattr(t1, 'home_venue', '')) or venues[daily_match_count % len(venues)]

            m_date, k_time, v_name = _allocate_conflict_free_slot(
                cur_date, desired_time, t1_venue, venues, slot_times, booked_slots,
                min_time=min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
            )
            current_stage_times.append(k_time)
            daily_match_count += 1

            matches.append({
                'round_name': stage_name if not stage_two_legged else f"{stage_name} (Leg 1)",
                'round_number': stage_idx + 1,
                'group_name': "Knockout",
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
                matches.append({
                    'round_name': f"{stage_name} (Leg 2)",
                    'round_number': stage_idx + 1,
                    'group_name': "Knockout",
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
        prev_stage_date = cur_date
        prev_stage_latest_time = max(current_stage_times) if current_stage_times else time(15, 0)
        cur_date = _calc_next_stage_date(cur_date, max(1, len(stage_names) - stage_idx), end_date, preferred_weekdays)

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


def _generate_page_mcintyre_fixtures(teams, start_date, preferred_weekdays, slot_times, venues, end_date=None, prefix="", booked_slots=None, matches_per_day=2):
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

    cur_date = _find_next_preferred_date(start_date, preferred_weekdays, max_date=end_date)
    if end_date and cur_date > end_date:
        cur_date = end_date

    seed1 = _normalize_team_seed(teams[0], "1st Place", "1st")
    seed2 = _normalize_team_seed(teams[1], "2nd Place", "2nd")
    seed3 = _normalize_team_seed(teams[2], "3rd Place", "3rd")
    seed4 = _normalize_team_seed(teams[3], "4th Place", "4th")

    matches = []
    stage1_times = []

    # STAGE 1 (Matchday 1):
    # Match 1: Qualifying Final (1st vs 2nd)
    qf_venue = seed1.get('home_venue') or venues[0]
    qf_date, qf_time, qf_ven = _allocate_conflict_free_slot(
        cur_date, slot_times[0], qf_venue, venues, slot_times, booked_slots,
        preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    stage1_times.append(qf_time)
    matches.append({
        'round_name': f"{prefix}Qualifying Final (1st vs 2nd)".strip(),
        'round_number': 100,
        'group_name': "Knockout",
        'home_team': seed1,
        'away_team': seed2,
        'match_date': qf_date,
        'kickoff_time': qf_time,
        'venue': qf_ven,
        'is_knockout': True
    })

    # Match 2: Elimination Final (3rd vs 4th)
    ef_venue = seed3.get('home_venue') or venues[1 % len(venues)]
    ef_time_des = slot_times[1 % len(slot_times)] if len(slot_times) > 1 else slot_times[0]
    ef_date, ef_time, ef_ven = _allocate_conflict_free_slot(
        cur_date, ef_time_des, ef_venue, venues, slot_times, booked_slots,
        preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    stage1_times.append(ef_time)
    matches.append({
        'round_name': f"{prefix}Elimination Final (3rd vs 4th)".strip(),
        'round_number': 100,
        'group_name': "Knockout",
        'home_team': seed3,
        'away_team': seed4,
        'match_date': ef_date,
        'kickoff_time': ef_time,
        'venue': ef_ven,
        'is_knockout': True
    })

    # STAGE 2 (Matchday 2):
    # Match 3: Preliminary Final (Loser QF vs Winner EF)
    prelim_date = _calc_next_stage_date(cur_date, 2, end_date, preferred_weekdays)
    prelim_min_time = _add_time(max(stage1_times), 150) if prelim_date <= cur_date else None
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
    pf_date, pf_time, pf_ven = _allocate_conflict_free_slot(
        prelim_date, slot_times[0], venues[0], venues, slot_times, booked_slots,
        min_time=prelim_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    matches.append({
        'round_name': f"{prefix}Preliminary Final".strip(),
        'round_number': 101,
        'group_name': "Knockout",
        'home_team': prelim_home,
        'away_team': prelim_away,
        'match_date': pf_date,
        'kickoff_time': pf_time,
        'venue': pf_ven,
        'is_knockout': True
    })

    # STAGE 3 (Matchday 3):
    # Match 4: Grand Final (Winner QF vs Winner PF)
    final_date = _calc_next_stage_date(prelim_date, 1, end_date, preferred_weekdays)
    final_min_time = _add_time(pf_time, 150) if final_date <= prelim_date else None
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
    gf_date, gf_time, gf_ven = _allocate_conflict_free_slot(
        final_date, slot_times[0], venues[0], venues, slot_times, booked_slots,
        min_time=final_min_time, preferred_weekdays=preferred_weekdays, end_date=end_date
    )
    matches.append({
        'round_name': f"{prefix}Grand Final".strip(),
        'round_number': 102,
        'group_name': "Knockout",
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


def commit_generated_fixtures(competition, matches_data, groups_data=None, tournament_format=None):
    """
    Atomically writes previewed/edited fixtures into database Match and TournamentGroup records.
    Supports placeholder fixtures (e.g. Finals with placeholder_home / placeholder_away before SFs conclude).
    """
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

        competition.matches.filter(status=MatchStatus.SCHEDULED).delete()

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

        for m in matches_data:
            home_id = m.get('home_team_id')
            away_id = m.get('away_team_id')

            home_team = (teams_cache.get(home_id) or Team.objects.filter(id=home_id).first()) if home_id else None
            away_team = (teams_cache.get(away_id) or Team.objects.filter(id=away_id).first()) if away_id else None

            placeholder_home = ""
            if not home_team:
                placeholder_home = m.get('home_team_name') or m.get('placeholder_home') or 'TBD'

            placeholder_away = ""
            if not away_team:
                placeholder_away = m.get('away_team_name') or m.get('placeholder_away') or 'TBD'

            if not home_team and not placeholder_home:
                continue
            if not away_team and not placeholder_away:
                continue

            m_date = parse_date_safe(m.get('match_date'))
            k_time = parse_time_safe(m.get('kickoff_time'))
            venue = m.get('venue', 'Central Stadium')
            round_name = m.get('round_name', 'Scheduled Fixture')
            round_num = int(m.get('round_number', 1) or 1)
            grp_name = m.get('group_name', '')
            grp_obj = group_objects_map.get(grp_name) if grp_name else None

            round_byes = m.get('round_byes', [])
            notes_str = ""
            if round_byes:
                notes_str = json.dumps({'byes': [b if isinstance(b, str) else b.get('name', '') for b in round_byes]})

            match_obj = Match.objects.create(
                competition=competition,
                tournament_round=round_name,
                round_number=round_num,
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

        return created_matches
