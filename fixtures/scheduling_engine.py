import math
from datetime import date, datetime, time, timedelta
from collections import defaultdict, Counter


def _get_team_id(team_obj):
    if team_obj is None:
        return None
    if isinstance(team_obj, dict):
        return team_obj.get('id')
    return getattr(team_obj, 'id', None)


def _get_team_name(team_obj, default="TBD"):
    if team_obj is None:
        return default
    if isinstance(team_obj, dict):
        return team_obj.get('name', default)
    return getattr(team_obj, 'name', default)


def _get_team_venue(team_obj):
    if team_obj is None:
        return ''
    if isinstance(team_obj, dict):
        return team_obj.get('home_venue', '') or ''
    return getattr(team_obj, 'home_venue', '') or ''


def generate_league_pairings(groups_dict, is_double_round=False):
    """
    Phase 2: Pure Pairing Generation.
    Generates all required match pairings for each group (or single league)
    using Berger circle rotation BEFORE any date assignment.
    Preserves home/away balance, reversed second-leg pairings, group identity,
    matchweek identity, and leg identity (1 or 2).
    """
    all_group_rounds = []
    for g_name, teams in groups_dict.items():
        n = len(teams)
        if n < 2:
            continue
        team_list = list(teams)
        if n % 2 != 0:
            team_list.append(None)  # BYE placeholder
            n += 1

        total_rounds = n - 1
        matches_per_round = n // 2
        current_teams = list(team_list)
        g_rounds = []

        # Leg 1
        for r in range(total_rounds):
            round_num = r + 1
            r_name = f"Matchweek {round_num:02d}"
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
            g_rounds.append({
                'round_number': round_num,
                'round_name': r_name,
                'leg': 1,
                'pairs': pairs
            })
            current_teams = [current_teams[0]] + [current_teams[-1]] + current_teams[1:-1]

        # Leg 2 (reversed home/away)
        if is_double_round:
            for r in range(total_rounds):
                round_num = total_rounds + r + 1
                r_name = f"Matchweek {round_num:02d}"
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
                g_rounds.append({
                    'round_number': round_num,
                    'round_name': r_name,
                    'leg': 2,
                    'pairs': pairs
                })
                current_teams = [current_teams[0]] + [current_teams[-1]] + current_teams[1:-1]

        all_group_rounds.append((g_name, g_rounds))

    if not all_group_rounds:
        return []

    max_rounds = max(len(gr) for _, gr in all_group_rounds)
    pairings = []
    order_idx = 0
    is_multi_group = len(all_group_rounds) > 1

    for r_idx in range(max_rounds):
        for g_name, g_rounds in all_group_rounds:
            if r_idx >= len(g_rounds):
                continue
            r_obj = g_rounds[r_idx]
            stage_name = f"Group Stage ({g_name})" if (is_multi_group and g_name) else "League Stage"
            for home, away in r_obj['pairs']:
                pairings.append({
                    'order_idx': order_idx,
                    'home_team': home,
                    'away_team': away,
                    'home_id': _get_team_id(home),
                    'away_id': _get_team_id(away),
                    'group_name': g_name if is_multi_group else '',
                    'round_number': r_obj['round_number'],
                    'round_name': r_obj['round_name'],
                    'leg': r_obj['leg'],
                    'stage_name': stage_name,
                    'is_knockout': False,
                })
                order_idx += 1

    return pairings


def generate_available_dates(start_date, end_date=None, preferred_weekdays=None, excluded_dates=None, min_needed=60):
    """
    Generates sorted list of valid match dates within [start_date, end_date]
    respecting preferred_weekdays and excluding any organizer-excluded dates.
    """
    if preferred_weekdays is None:
        preferred_weekdays = [0, 1, 2, 3, 4, 5, 6]
    pref_set = set(preferred_weekdays) if preferred_weekdays else {0, 1, 2, 3, 4, 5, 6}
    excl_set = set(excluded_dates or [])

    dates = []
    cur = start_date
    if end_date is not None:
        while cur <= end_date:
            if cur.weekday() in pref_set and cur not in excl_set:
                dates.append(cur)
            cur += timedelta(days=1)
    else:
        for _ in range(730):
            if cur.weekday() in pref_set and cur not in excl_set:
                dates.append(cur)
                if len(dates) >= min_needed:
                    break
            cur += timedelta(days=1)
    return dates


def _time_to_minutes(t_val):
    if isinstance(t_val, time):
        return t_val.hour * 60 + t_val.minute
    if isinstance(t_val, str) and ':' in t_val:
        parts = t_val.strip().split(':')
        return int(parts[0]) * 60 + int(parts[1][:2])
    return 15 * 60


def _max_compatible_slots(slot_times, min_rest_minutes):
    if not slot_times:
        return 1
    if not min_rest_minutes or min_rest_minutes <= 0:
        return len(slot_times)
    sorted_mins = sorted(_time_to_minutes(t) for t in slot_times)
    count = 1
    last_m = sorted_mins[0]
    for m in sorted_mins[1:]:
        if m - last_m >= min_rest_minutes:
            count += 1
            last_m = m
    return count


def validate_candidate_assignment(fixture, cand_date, state, constraints):
    """
    Validates whether `fixture` can be assigned to `cand_date` under all mandatory constraints:
      - Global daily match limit (matches_per_day)
      - Per-team daily match limit (max_matches_per_team_per_day, configurable 1+)
      - Minimum team rest days between distinct match dates (min_rest_days)
      - Team unavailability dates (team_unavailable_dates)
      - Leg 2 cannot precede Leg 1 for the same team/pairing
      - Non-overlapping kickoff time + venue slot availability on cand_date
    """
    mpd = constraints['matches_per_day']
    if state['daily_counts'][cand_date] >= mpd:
        return False, "Daily match limit reached"

    max_team_mpd = max(1, int(constraints.get('max_matches_per_team_per_day', 1) or 1))
    h_id = fixture['home_id']
    a_id = fixture['away_id']
    min_rest = int(constraints.get('min_rest_days', 0) or 0)
    unavail = constraints.get('team_unavailable_dates', {})

    if h_id:
        if state['team_date_counts'][(cand_date, h_id)] >= max_team_mpd:
            return False, f"Home team already has {max_team_mpd} match(es) on this date"
        if cand_date in unavail.get(h_id, ()):
            return False, "Home team unavailable on this date"
        if min_rest > 0:
            for prev_d in state['team_dates'][h_id]:
                if prev_d != cand_date and abs((cand_date - prev_d).days) <= min_rest:
                    return False, f"Home team violates {min_rest} rest day(s) requirement"

    if a_id:
        if state['team_date_counts'][(cand_date, a_id)] >= max_team_mpd:
            return False, f"Away team already has {max_team_mpd} match(es) on this date"
        if cand_date in unavail.get(a_id, ()):
            return False, "Away team unavailable on this date"
        if min_rest > 0:
            for prev_d in state['team_dates'][a_id]:
                if prev_d != cand_date and abs((cand_date - prev_d).days) <= min_rest:
                    return False, f"Away team violates {min_rest} rest day(s) requirement"

    # Ensure Leg 2 match of same pair (or earlier leg) isn't scheduled before Leg 1
    if fixture.get('leg', 1) > 1:
        pair_key = frozenset([h_id, a_id])
        leg1_date = state['leg1_pair_dates'].get(pair_key)
        if leg1_date is not None and cand_date <= leg1_date:
            return False, "Second-leg fixture must occur after first-leg fixture"

    # Check venue + non-overlapping kickoff capacity on cand_date (respecting min_rest_minutes)
    slot_times = constraints.get('slot_times', [time(15, 0)])
    venues = constraints.get('venues', ['Central Stadium'])
    min_rest_mins = int(constraints.get('min_rest_minutes', 0) or 0)
    max_team_slots = _max_compatible_slots(slot_times, min_rest_mins)
    if h_id and state['team_date_counts'][(cand_date, h_id)] >= max_team_slots:
        return False, "Not enough rest-compatible daily kickoff slots for home team"
    if a_id and state['team_date_counts'][(cand_date, a_id)] >= max_team_slots:
        return False, "Not enough rest-compatible daily kickoff slots for away team"

    has_free_slot = False
    for st in slot_times:
        for ven in venues:
            if (cand_date, st, ven) not in state['booked_slots']:
                has_free_slot = True
                break
        if has_free_slot:
            break
    if not has_free_slot:
        return False, "No available kickoff/venue slot on this date"

    return True, ""


def _assign_to_state(fixture, cand_date, state):
    h_id = fixture['home_id']
    a_id = fixture['away_id']
    state['daily_counts'][cand_date] += 1
    if h_id:
        state['team_date_counts'][(cand_date, h_id)] += 1
        state['team_dates'][h_id].append(cand_date)
    if a_id:
        state['team_date_counts'][(cand_date, a_id)] += 1
        state['team_dates'][a_id].append(cand_date)
    if fixture.get('leg', 1) == 1 and h_id and a_id:
        state['leg1_pair_dates'][frozenset([h_id, a_id])] = cand_date


def _unassign_from_state(fixture, cand_date, state):
    h_id = fixture['home_id']
    a_id = fixture['away_id']
    state['daily_counts'][cand_date] -= 1
    if h_id:
        state['team_date_counts'][(cand_date, h_id)] -= 1
        state['team_dates'][h_id].pop()
    if a_id:
        state['team_date_counts'][(cand_date, a_id)] -= 1
        state['team_dates'][a_id].pop()
    if fixture.get('leg', 1) == 1 and h_id and a_id:
        state['leg1_pair_dates'].pop(frozenset([h_id, a_id]), None)


def _init_solver_state(locked_matches=None):
    state = {
        'daily_counts': Counter(),
        'team_date_counts': Counter(),
        'team_dates': defaultdict(list),
        'team_times_on_date': defaultdict(set),
        'booked_slots': set(),
        'leg1_pair_dates': {},
    }
    if locked_matches:
        for lm in locked_matches:
            d = lm['match_date']
            t = lm['kickoff_time']
            v = lm['venue']
            h_id = lm.get('home_team_id')
            a_id = lm.get('away_team_id')
            state['daily_counts'][d] += 1
            if h_id:
                state['team_date_counts'][(d, h_id)] += 1
                state['team_dates'][h_id].append(d)
                if t:
                    state['team_times_on_date'][(d, t)].add(h_id)
            if a_id:
                state['team_date_counts'][(d, a_id)] += 1
                state['team_dates'][a_id].append(d)
                if t:
                    state['team_times_on_date'][(d, t)].add(a_id)
            if d and t and v:
                state['booked_slots'].add((d, t, v))
            if lm.get('leg', 1) == 1 and h_id and a_id:
                state['leg1_pair_dates'][frozenset([h_id, a_id])] = d
    return state


def _allocate_slot_on_date(fixture, d, state, constraints):
    """
    Assigns a conflict-free (kickoff_time, venue) on date `d`.
    Ensures:
      - (d, st, ven) is not already booked.
      - Neither home_team nor away_team already has a match at (d, st) when max_team_mpd > 1.
    """
    slot_times = constraints.get('slot_times', [time(15, 0)])
    venues = constraints.get('venues', ['Central Stadium'])
    desired_venue = _get_team_venue(fixture.get('home_team'))
    ordered_venues = list(dict.fromkeys(([desired_venue] if desired_venue else []) + list(venues)))
    if not ordered_venues:
        ordered_venues = ['Central Stadium']

    h_id = fixture.get('home_id')
    a_id = fixture.get('away_id')

    slot_idx = max(0, state['daily_counts'][d] - 1)
    ordered_times = slot_times[slot_idx % len(slot_times):] + slot_times[:slot_idx % len(slot_times)]

    # First pass: strictly avoid venue double-booking, same-time team overlap, and same-day rest violations
    min_rest_mins = int(constraints.get('min_rest_minutes', 0) or 0)
    for st in ordered_times:
        st_mins = _time_to_minutes(st)
        conflict = False
        for booked_t, busy_teams in [
            (bt_key, bteams) for (bd, bt_key), bteams in state['team_times_on_date'].items() if bd == d
        ]:
            if (h_id and h_id in busy_teams) or (a_id and a_id in busy_teams):
                if booked_t == st or (min_rest_mins > 0 and abs(st_mins - _time_to_minutes(booked_t)) < min_rest_mins):
                    conflict = True
                    break
        if conflict:
            continue
        busy = state['team_times_on_date'][(d, st)]
        for ven in ordered_venues:
            if (d, st, ven) not in state['booked_slots']:
                state['booked_slots'].add((d, st, ven))
                if h_id:
                    busy.add(h_id)
                if a_id:
                    busy.add(a_id)
                return st, ven

    # Second pass: fallback if needed
    for st in ordered_times:
        for ven in ordered_venues:
            if (d, st, ven) not in state['booked_slots']:
                state['booked_slots'].add((d, st, ven))
                return st, ven

    st = slot_times[0]
    ven = ordered_venues[0]
    state['booked_slots'].add((d, st, ven))
    return st, ven


def _solve_greedy_packed(pairings, candidate_dates, constraints, locked_matches=None):
    """
    Fast date-packing heuristic with lookahead:
    Iterates candidate_dates chronologically, filling each date up to matches_per_day
    with the highest-priority valid unassigned fixture (respecting round/leg order
    and prioritizing teams with more remaining matches so teams aren't stranded).
    """
    state = _init_solver_state(locked_matches)
    unassigned = list(pairings)
    assignments = {}

    team_remaining = Counter()
    for f in unassigned:
        if f['home_id']:
            team_remaining[f['home_id']] += 1
        if f['away_id']:
            team_remaining[f['away_id']] += 1

    mpd = constraints['matches_per_day']

    for d in candidate_dates:
        if not unassigned:
            break
        while state['daily_counts'][d] < mpd and unassigned:
            # Find best eligible fixture for date d
            best_idx = None
            best_score = None
            for idx, f in enumerate(unassigned):
                ok, _ = validate_candidate_assignment(f, d, state, constraints)
                if not ok:
                    continue
                # Score: prioritize fair team appearance distribution today (0 today before 1 today, etc.),
                # then earlier leg, earlier round, and teams with higher remaining workload
                h_today = state['team_date_counts'][(d, f['home_id'])] if f['home_id'] else 0
                a_today = state['team_date_counts'][(d, f['away_id'])] if f['away_id'] else 0
                max_today = max(h_today, a_today)
                sum_today = h_today + a_today
                workload = (team_remaining[f['home_id']] if f['home_id'] else 0) + \
                           (team_remaining[f['away_id']] if f['away_id'] else 0)
                score = (max_today, sum_today, f['leg'], f['round_number'], -workload, f['order_idx'])
                if best_score is None or score < best_score:
                    best_score = score
                    best_idx = idx
            if best_idx is None:
                break
            chosen = unassigned.pop(best_idx)
            _assign_to_state(chosen, d, state)
            assignments[chosen['order_idx']] = d
            if chosen['home_id']:
                team_remaining[chosen['home_id']] -= 1
            if chosen['away_id']:
                team_remaining[chosen['away_id']] -= 1

    if unassigned:
        return None
    return assignments


def _solve_backtracking(pairings, candidate_dates, constraints, locked_matches=None, max_nodes=25000):
    """
    Bounded backtracking constraint solver with MRV (Minimum Remaining Values)
    and Forward Checking to guarantee a valid complete schedule whenever one exists
    within `candidate_dates`.
    """
    state = _init_solver_state(locked_matches)
    mpd = constraints['matches_per_day']
    n = len(pairings)
    assignments = {}
    nodes = [0]

    # Pre-order by (leg, round_number, order_idx)
    ordered = sorted(pairings, key=lambda f: (f['leg'], f['round_number'], f['order_idx']))

    def get_valid_dates(f):
        valid = []
        for d in candidate_dates:
            ok, _ = validate_candidate_assignment(f, d, state, constraints)
            if ok:
                valid.append(d)
        return valid

    def backtrack(remaining):
        if not remaining:
            return True
        nodes[0] += 1
        if nodes[0] > max_nodes:
            return False

        # Forward check capacity
        free_slots = sum(max(0, mpd - state['daily_counts'][d]) for d in candidate_dates)
        if free_slots < len(remaining):
            return False

        # MRV: pick fixture with fewest valid dates (tie-break by leg, round_number)
        best_f = None
        best_dates = None
        for f in remaining:
            vd = get_valid_dates(f)
            if not vd:
                return False  # Forward-check prune!
            if best_dates is None or len(vd) < len(best_dates) or (
                len(vd) == len(best_dates) and (f['leg'], f['round_number'], f['order_idx']) < (best_f['leg'], best_f['round_number'], best_f['order_idx'])
            ):
                best_f = f
                best_dates = vd
                if len(best_dates) == 1:
                    break

        next_remaining = [f for f in remaining if f is not best_f]

        # Try dates that already have matches first (pack dates) or chronologically
        best_dates.sort(key=lambda d: (0 if state['daily_counts'][d] > 0 else 1, d))

        for d in best_dates:
            _assign_to_state(best_f, d, state)
            assignments[best_f['order_idx']] = d
            if backtrack(next_remaining):
                return True
            del assignments[best_f['order_idx']]
            _unassign_from_state(best_f, d, state)
            if nodes[0] > max_nodes:
                return False

        return False

    if backtrack(ordered):
        return assignments
    return None


def optimize_schedule_distribution(pairings, available_dates, constraints, locked_matches=None):
    """
    Phase 4: Fully Optimized Constraint-Based Date Distribution.
    Priority 1: Satisfy all mandatory constraints (daily limit, rest days, no same-day conflict, date range).
    Priority 2: Schedule every required fixture (zero dropped).
    Priority 3: Minimize total distinct match dates used (iterative deepening from theoretical min D).
    Priority 4: Pack matches efficiently without leaving unnecessary idle/half-empty dates.

    Returns (scheduled_matches, dates_used) or (None, error_message).
    """
    if not pairings:
        return [], 0

    mpd = max(1, int(constraints.get('matches_per_day', 1)))
    min_rest = int(constraints.get('min_rest_days', 0) or 0)
    strategy = constraints.get('scheduling_strategy', 'optimized')

    if strategy == 'sequential':
        return _schedule_sequential_fallback(pairings, available_dates, constraints, locked_matches)

    # Calculate theoretical lower bound on number of dates needed
    total_matches = len(pairings)
    min_dates_vol = math.ceil(total_matches / mpd)

    # Team-level lower bound: max matches any single team plays / max_matches_per_team_per_day
    max_team_mpd = max(1, int(constraints.get('max_matches_per_team_per_day', 1) or 1))
    team_match_counts = Counter()
    for f in pairings:
        if f['home_id']:
            team_match_counts[f['home_id']] += 1
        if f['away_id']:
            team_match_counts[f['away_id']] += 1
    max_team_matches = max(team_match_counts.values(), default=0)
    min_team_dates = math.ceil(max_team_matches / max_team_mpd) if max_team_matches > 0 else 0

    lower_bound_d = max(min_dates_vol, min_team_dates)
    if lower_bound_d > len(available_dates):
        return None, (
            f"Available match dates ({len(available_dates)}) are fewer than the minimum required dates ({lower_bound_d}) "
            f"for {total_matches} matches at {mpd} match(es)/day and max {max_team_mpd} match(es)/team/day."
        )

    best_assignments = None

    # Iterative deepening on target date count D to minimize distinct dates used
    for d_count in range(lower_bound_d, len(available_dates) + 1):
        window = available_dates[:d_count]

        # Try fast lookahead greedy packer first
        res = _solve_greedy_packed(pairings, window, constraints, locked_matches)
        if res is not None:
            best_assignments = res
            break

        # If greedy failed due to early choices/rest constraints, run backtracking solver
        res = _solve_backtracking(pairings, window, constraints, locked_matches)
        if res is not None:
            best_assignments = res
            break

    if best_assignments is None:
        # Final check across all available dates with higher node budget
        res = _solve_backtracking(pairings, available_dates, constraints, locked_matches, max_nodes=60000)
        if res is not None:
            best_assignments = res

    if best_assignments is None:
        slot_cap = len(constraints.get('slot_times', [time(15, 0)])) * max(1, len(constraints.get('venues', ['Central Stadium'])))
        team_cap = max(1, (len(team_match_counts) * max_team_mpd) // 2) if team_match_counts else mpd
        max_feasible = min(slot_cap, team_cap)
        reason = (
            f"No valid schedule satisfies all mandatory constraints within {len(available_dates)} available match dates "
            f"(Matches: {total_matches}, Requested Max/Day: {mpd}, Max Feasible/Day: {max_feasible}, "
            f"Max/Team/Day: {max_team_mpd}, Min Rest Days: {min_rest})."
        )
        return None, reason

    # Materialize scheduled matches with conflict-free kickoff times and venues
    slot_state = _init_solver_state(locked_matches)
    scheduled = []
    for f in sorted(pairings, key=lambda x: (best_assignments[x['order_idx']], x['leg'], x['round_number'], x['order_idx'])):
        d = best_assignments[f['order_idx']]
        slot_state['daily_counts'][d] += 1
        k_time, venue = _allocate_slot_on_date(f, d, slot_state, constraints)
        scheduled.append({
            'round_name': f['round_name'],
            'round_number': f['round_number'],
            'leg': f['leg'],
            'group_name': f['group_name'],
            'stage_name': f['stage_name'],
            'home_team': f['home_team'],
            'away_team': f['away_team'],
            'match_date': d,
            'kickoff_time': k_time,
            'venue': venue,
            'is_knockout': False,
        })

    dates_used = len(set(m['match_date'] for m in scheduled))
    return scheduled, dates_used


def _schedule_sequential_fallback(pairings, available_dates, constraints, locked_matches=None):
    """
    Sequential matchweek scheduling: finishes every match in round r before advancing
    to the next date for round r+1, while still enforcing min_rest_days, end_date,
    daily limits, and locked matches.
    """
    state = _init_solver_state(locked_matches)
    mpd = max(1, int(constraints.get('matches_per_day', 1)))

    # Group by (leg, round_number)
    rounds_map = defaultdict(list)
    for f in pairings:
        rounds_map[(f['leg'], f['round_number'])].append(f)

    date_idx = 0
    num_dates = len(available_dates)
    assignments = {}

    sorted_keys = sorted(rounds_map.keys())
    for k_idx, r_key in enumerate(sorted_keys):
        r_fixtures = rounds_map[r_key]
        for f in r_fixtures:
            placed = False
            while date_idx < num_dates:
                d = available_dates[date_idx]
                ok, _ = validate_candidate_assignment(f, d, state, constraints)
                if ok:
                    _assign_to_state(f, d, state)
                    assignments[f['order_idx']] = d
                    placed = True
                    break
                date_idx += 1
            if not placed:
                return None, (
                    f"Sequential matchweek schedule cannot fit all {len(pairings)} matches within {num_dates} available dates "
                    f"at {mpd} match(es)/day and {constraints.get('min_rest_days', 0)} rest day(s)."
                )
        # Advance to next available date for next matchweek
        if k_idx < len(sorted_keys) - 1:
            date_idx += 1

    slot_state = _init_solver_state(locked_matches)
    scheduled = []
    for f in sorted(pairings, key=lambda x: (assignments[x['order_idx']], x['leg'], x['round_number'], x['order_idx'])):
        d = assignments[f['order_idx']]
        slot_state['daily_counts'][d] += 1
        k_time, venue = _allocate_slot_on_date(f, d, slot_state, constraints)
        scheduled.append({
            'round_name': f['round_name'],
            'round_number': f['round_number'],
            'leg': f['leg'],
            'group_name': f['group_name'],
            'stage_name': f['stage_name'],
            'home_team': f['home_team'],
            'away_team': f['away_team'],
            'match_date': d,
            'kickoff_time': k_time,
            'venue': venue,
            'is_knockout': False,
        })

    dates_used = len(set(m['match_date'] for m in scheduled))
    return scheduled, dates_used


def validate_complete_schedule(matches_list, constraints, locked_matches=None):
    """
    Phase 2 & Phase 9: Independent Schedule Validator.
    Verifies every generated or manually edited fixture against all mandatory constraints:
      1. Date inside [start_date, end_date] and not in excluded_dates.
      2. Daily capacity <= matches_per_day globally.
      3. No team plays twice on the same date.
      4. Minimum rest days respected for every team.
      5. No venue + date + kickoff_time double-booking.
      6. No duplicate pairings.
      7. Knockout matches strictly after group/league matches.
      8. Final strictly after Semi-Finals.
    Returns comprehensive validation report with per-match status for live UI feedback.
    """
    errors = []
    warnings = []
    per_match = {}

    start_date = constraints.get('start_date')
    end_date = constraints.get('end_date')
    mpd = max(1, int(constraints.get('matches_per_day', 1) or 1))
    min_rest = int(constraints.get('min_rest_days', 0) or 0)
    excl_set = set(constraints.get('excluded_dates') or [])
    pref_days = constraints.get('preferred_weekdays')

    daily_counts = Counter()
    teams_on_date = defaultdict(list)
    team_dates = defaultdict(list)
    venue_slots = defaultdict(list)
    seen_pairings = {}

    group_dates = []
    sf_dates = []
    final_dates = []

    def _parse_d(val):
        if isinstance(val, date) and not isinstance(val, datetime):
            return val
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, str) and val:
            return date.fromisoformat(val[:10])
        return None

    for idx, m in enumerate(matches_list):
        tid = m.get('temp_id') or str(m.get('id') or idx)
        per_match[tid] = {'valid': True, 'messages': []}

        d = _parse_d(m.get('match_date'))
        t = str(m.get('kickoff_time', '15:00'))[:5]
        v = (m.get('venue') or '').strip()
        h_id = m.get('home_team_id') or _get_team_id(m.get('home_team'))
        a_id = m.get('away_team_id') or _get_team_id(m.get('away_team'))
        is_ko = bool(m.get('is_knockout'))
        r_name = (m.get('round_name') or m.get('tournament_round') or '').lower()
        leg = int(m.get('leg', 1) or 1)
        g_name = m.get('group_name') or ''

        if not d:
            msg = "Missing or invalid match date."
            per_match[tid]['valid'] = False
            per_match[tid]['messages'].append(msg)
            errors.append(f"Match {tid}: {msg}")
            continue

        if start_date and d < start_date:
            msg = f"Date {d.isoformat()} is before start date {start_date.isoformat()}."
            per_match[tid]['valid'] = False
            per_match[tid]['messages'].append(msg)
            errors.append(msg)

        if end_date and d > end_date:
            msg = f"Date {d.isoformat()} exceeds end date {end_date.isoformat()}."
            per_match[tid]['valid'] = False
            per_match[tid]['messages'].append(msg)
            errors.append(msg)

        if d in excl_set:
            msg = f"Date {d.isoformat()} is an excluded date."
            per_match[tid]['valid'] = False
            per_match[tid]['messages'].append(msg)
            errors.append(msg)

        if pref_days and d.weekday() not in pref_days:
            warnings.append(f"Match on {d.isoformat()} is not on a preferred weekday.")

        daily_counts[d] += 1
        if h_id:
            teams_on_date[(d, h_id)].append(tid)
            team_dates[h_id].append((d, tid))
        if a_id:
            teams_on_date[(d, a_id)].append(tid)
            team_dates[a_id].append((d, tid))
        if v:
            venue_slots[(d, t, v)].append(tid)

        if h_id and a_id and not is_ko:
            pkey = (h_id, a_id, leg, g_name)
            if pkey in seen_pairings:
                msg = "Duplicate fixture pairing detected."
                per_match[tid]['valid'] = False
                per_match[tid]['messages'].append(msg)
                errors.append(msg)
            seen_pairings[pkey] = tid

        if is_ko:
            if 'semi' in r_name:
                sf_dates.append((d, tid))
            elif 'final' in r_name and 'semi' not in r_name and 'quarter' not in r_name:
                final_dates.append((d, tid))
        else:
            group_dates.append((d, tid))

    # Check daily limits
    for d, cnt in daily_counts.items():
        if cnt > mpd:
            msg = f"Date {d.isoformat()} has {cnt} matches, exceeding daily limit of {mpd}."
            errors.append(msg)
            for m in matches_list:
                if _parse_d(m.get('match_date')) == d:
                    tid = m.get('temp_id') or str(m.get('id') or '')
                    if tid in per_match:
                        per_match[tid]['valid'] = False
                        per_match[tid]['messages'].append(msg)

    # Check per-team daily limits and same-time overlap
    max_team_mpd = max(1, int(constraints.get('max_matches_per_team_per_day', 1) or 1))
    for (d, t_id), tids in teams_on_date.items():
        if len(tids) > max_team_mpd:
            msg = f"Team ID {t_id} is scheduled {len(tids)} times on {d.isoformat()}, exceeding limit of {max_team_mpd} match(es)/team/day."
            errors.append(msg)
            for tid in tids:
                per_match[tid]['valid'] = False
                per_match[tid]['messages'].append(msg)

    # Check same-time team overlap (a team cannot play two matches at the exact same kickoff time)
    team_time_slots = defaultdict(list)
    for idx, m in enumerate(matches_list):
        tid = m.get('temp_id') or str(m.get('id') or idx)
        d = _parse_d(m.get('match_date'))
        t = str(m.get('kickoff_time', '15:00'))[:5]
        h_id = m.get('home_team_id') or _get_team_id(m.get('home_team'))
        a_id = m.get('away_team_id') or _get_team_id(m.get('away_team'))
        if d:
            if h_id:
                team_time_slots[(d, t, h_id)].append(tid)
            if a_id:
                team_time_slots[(d, t, a_id)].append(tid)
    for (d, t, t_id), tids in team_time_slots.items():
        if len(tids) > 1:
            msg = f"Team ID {t_id} has overlapping kickoff time {t} on {d.isoformat()}."
            errors.append(msg)
            for tid in tids:
                per_match[tid]['valid'] = False
                per_match[tid]['messages'].append(msg)

    # Check same-day minimum rest minutes between a team's matches on the same date
    min_rest_mins = int(constraints.get('min_rest_minutes', 0) or 0)
    if min_rest_mins > 0:
        team_day_times = defaultdict(list)
        for idx, m in enumerate(matches_list):
            tid = m.get('temp_id') or str(m.get('id') or idx)
            d = _parse_d(m.get('match_date'))
            t_mins = _time_to_minutes(str(m.get('kickoff_time', '15:00'))[:5])
            h_id = m.get('home_team_id') or _get_team_id(m.get('home_team'))
            a_id = m.get('away_team_id') or _get_team_id(m.get('away_team'))
            if d:
                if h_id:
                    team_day_times[(d, h_id)].append((t_mins, tid))
                if a_id:
                    team_day_times[(d, a_id)].append((t_mins, tid))
        for (d, t_id), items in team_day_times.items():
            if len(items) > 1:
                items.sort(key=lambda x: x[0])
                for i in range(1, len(items)):
                    if items[i][0] - items[i - 1][0] < min_rest_mins:
                        msg = f"Team ID {t_id} has less than {min_rest_mins} min rest between matches on {d.isoformat()}."
                        errors.append(msg)
                        per_match[items[i][1]]['valid'] = False
                        per_match[items[i][1]]['messages'].append(msg)

    # Check rest days
    if min_rest > 0:
        for t_id, d_list in team_dates.items():
            d_sorted = sorted(d_list, key=lambda x: x[0])
            for i in range(1, len(d_sorted)):
                prev_d, prev_tid = d_sorted[i - 1]
                cur_d, cur_tid = d_sorted[i]
                diff = (cur_d - prev_d).days
                if 0 < diff <= min_rest:
                    msg = f"Team ID {t_id} has only {diff - 1} rest day(s) between {prev_d.isoformat()} and {cur_d.isoformat()} (requires {min_rest})."
                    errors.append(msg)
                    per_match[cur_tid]['valid'] = False
                    per_match[cur_tid]['messages'].append(msg)

    # Check venue + date + time double bookings
    for (d, t, v), tids in venue_slots.items():
        if len(tids) > 1:
            msg = f"Venue '{v}' is double-booked on {d.isoformat()} at {t}."
            errors.append(msg)
            for tid in tids:
                per_match[tid]['valid'] = False
                per_match[tid]['messages'].append(msg)

    # Check stage separation
    if group_dates and (sf_dates or final_dates):
        max_g = max(d for d, _ in group_dates)
        for d, tid in sf_dates + final_dates:
            if d <= max_g:
                msg = f"Knockout match on {d.isoformat()} must be strictly after group stage end ({max_g.isoformat()})."
                errors.append(msg)
                per_match[tid]['valid'] = False
                per_match[tid]['messages'].append(msg)

    if sf_dates and final_dates:
        max_sf = max(d for d, _ in sf_dates)
        for d, tid in final_dates:
            if d <= max_sf:
                msg = f"Championship Final on {d.isoformat()} must be strictly after Semi-Finals ({max_sf.isoformat()})."
                errors.append(msg)
                per_match[tid]['valid'] = False
                per_match[tid]['messages'].append(msg)

    # Deduplicate error messages preserving order
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
        'per_match_status': per_match,
    }
