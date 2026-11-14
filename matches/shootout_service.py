"""
Penalty Shootout Service for Futbolix Knockout Matches.
Enforces:
- Mandatory first five penalties alternating between teams.
- Game-format-based player rotation (7-a-side: 7 players; 11-a-side: 11 players).
- Sudden death system when tied after five penalties.
- Accurate validation on eligible match players and attempt order.
- Automatic bracket advancement upon completion.
"""
from django.db import transaction
from django.utils import timezone
from matches.models import (
    Match, MatchStatus, MatchEvent, MatchEventType,
    PenaltyShootout, PenaltyShootoutAttempt,
    ShootoutPhase, ShootoutOutcome, ShootoutStatus
)
from teams.models import Player
from fixtures.services import advance_knockout_bracket


def get_game_format_capacity(competition):
    """
    Returns the maximum on-field players per team based on competition category.
    Defaults to 11 for 11-a-side/youth, 7 for 7-a-side, 5 for 5-a-side.
    """
    cat = (competition.category or '').lower() if competition else ''
    if '7' in cat:
        return 7
    if '5' in cat:
        return 5
    return 11


def get_eligible_match_players(match, team):
    """
    Retrieves the list of active, eligible players for a team in a knockout match,
    excluding any player who received a RED_CARD in this match.
    Caps the pool to the tournament's game format capacity (7 for 7-a-side, 11 for 11-a-side).
    Guarantees consistent ordering and preserves players who have already taken penalties.
    """
    capacity = get_game_format_capacity(match.competition)

    red_carded_ids = set(
        MatchEvent.objects.filter(
            match=match,
            team=team,
            event_type=MatchEventType.RED_CARD
        ).values_list('player_id', flat=True)
    )

    all_active = list(
        team.players.filter(is_active=True)
        .exclude(id__in=red_carded_ids)
        .order_by('jersey_number', 'full_name')
    )

    # If shootout attempts already exist, prioritize players who have participated
    existing_taker_ids = list(
        PenaltyShootoutAttempt.objects.filter(
            match=match,
            team=team
        ).values_list('player_id', flat=True).distinct()
    )

    already_participated = [p for p in all_active if p.id in existing_taker_ids]
    not_yet_participated = [p for p in all_active if p.id not in existing_taker_ids]

    ordered_pool = already_participated + not_yet_participated

    # Cap to game format capacity if more players exist
    if len(ordered_pool) > capacity:
        ordered_pool = ordered_pool[:capacity]

    return ordered_pool


def get_or_create_shootout(match):
    """
    Initializes or retrieves the PenaltyShootout record for a tied knockout match.
    """
    shootout, created = PenaltyShootout.objects.get_or_create(match=match)
    return shootout


def get_shootout_state(shootout):
    """
    Computes and returns the complete state of the shootout:
    - Current round (1..5 in initial five, 6+ in sudden death)
    - Next team kicking
    - Next attempt order
    - Available unused eligible players for the kicking team in the current rotation cycle
    - Attempts history grouped by initial five and sudden death
    - Both teams' scores and player counts
    """
    if hasattr(shootout, 'refresh_from_db'):
        shootout.refresh_from_db()
    match = shootout.match
    if hasattr(match, 'refresh_from_db'):
        match.refresh_from_db()
    attempts = list(shootout.attempts.select_related('player', 'team').order_by('attempt_order'))
    total_attempts = len(attempts)

    home_team = match.home_team
    away_team = match.away_team

    home_attempts = [a for a in attempts if a.team_id == home_team.id]
    away_attempts = [a for a in attempts if a.team_id == away_team.id]

    home_score = sum(1 for a in home_attempts if a.is_successful)
    away_score = sum(1 for a in away_attempts if a.is_successful)

    # Sync scores if needed
    if shootout.home_score != home_score or shootout.away_score != away_score:
        shootout.home_score = home_score
        shootout.away_score = away_score
        shootout.save(update_fields=['home_score', 'away_score'])

    is_completed = (shootout.status == ShootoutStatus.COMPLETED)

    # Determine next kicker and round if in progress
    if is_completed:
        next_team = None
        next_attempt_order = None
        current_round = (total_attempts + 1) // 2 if total_attempts > 0 else 1
        current_phase = ShootoutPhase.INITIAL_FIVE if current_round <= 5 else ShootoutPhase.SUDDEN_DEATH
        available_players = []
    else:
        # Alternating: Home (attempt 1, 3, 5...), Away (attempt 2, 4, 6...)
        if total_attempts % 2 == 0:
            next_team = home_team
            current_round = (total_attempts // 2) + 1
        else:
            next_team = away_team
            current_round = (total_attempts // 2) + 1

        next_attempt_order = total_attempts + 1
        current_phase = ShootoutPhase.INITIAL_FIVE if current_round <= 5 else ShootoutPhase.SUDDEN_DEATH

        # Compute player rotation for next_team
        eligible_players = get_eligible_match_players(match, next_team)
        next_team_attempts = home_attempts if next_team.id == home_team.id else away_attempts

        # Count how many times each eligible player has taken a penalty
        taken_counts = {p.id: 0 for p in eligible_players}
        for a in next_team_attempts:
            if a.player_id in taken_counts:
                taken_counts[a.player_id] += 1

        # The minimum number of penalties taken by any eligible player
        min_taken = min(taken_counts.values()) if taken_counts else 0

        # Available players are those who have taken min_taken penalties
        available_players = [p for p in eligible_players if taken_counts.get(p.id, 0) == min_taken]

    # Organize history for display
    # 1. Initial Five (Rounds 1 - 5)
    initial_five_rounds = []
    for r in range(1, 6):
        h_att = next((a for a in home_attempts if a.shootout_round == r), None)
        a_att = next((a for a in away_attempts if a.shootout_round == r), None)
        initial_five_rounds.append({
            'round': r,
            'home_attempt': h_att,
            'away_attempt': a_att,
        })

    # 2. Sudden Death (Rounds 6+)
    max_round = max([a.shootout_round for a in attempts] + [current_round if not is_completed else 5])
    sudden_death_rounds = []
    if max_round >= 6:
        for r in range(6, max_round + 1):
            h_att = next((a for a in home_attempts if a.shootout_round == r), None)
            a_att = next((a for a in away_attempts if a.shootout_round == r), None)
            if h_att or a_att or (not is_completed and r == current_round):
                sudden_death_rounds.append({
                    'round': r,
                    'home_attempt': h_att,
                    'away_attempt': a_att,
                })

    # Summary of eligible and used players for rotation inspection
    home_eligible = get_eligible_match_players(match, home_team)
    away_eligible = get_eligible_match_players(match, away_team)

    home_taken_counts = {p.id: 0 for p in home_eligible}
    for a in home_attempts:
        if a.player_id in home_taken_counts:
            home_taken_counts[a.player_id] += 1
    home_min = min(home_taken_counts.values()) if home_taken_counts else 0
    home_unused_in_cycle = [p for p in home_eligible if home_taken_counts.get(p.id, 0) == home_min]

    away_taken_counts = {p.id: 0 for p in away_eligible}
    for a in away_attempts:
        if a.player_id in away_taken_counts:
            away_taken_counts[a.player_id] += 1
    away_min = min(away_taken_counts.values()) if away_taken_counts else 0
    away_unused_in_cycle = [p for p in away_eligible if away_taken_counts.get(p.id, 0) == away_min]

    return {
        'shootout': shootout,
        'match': match,
        'is_completed': is_completed,
        'winner': shootout.winner,
        'home_team': home_team,
        'away_team': away_team,
        'home_score': home_score,
        'away_score': away_score,
        'current_round': current_round,
        'current_phase': current_phase,
        'next_team': next_team,
        'next_attempt_order': next_attempt_order,
        'available_players': available_players,
        'initial_five_rounds': initial_five_rounds,
        'sudden_death_rounds': sudden_death_rounds,
        'home_eligible': home_eligible,
        'away_eligible': away_eligible,
        'home_unused_in_cycle': home_unused_in_cycle,
        'away_unused_in_cycle': away_unused_in_cycle,
        'game_format_capacity': get_game_format_capacity(match.competition),
        'attempts': attempts,
    }


def record_shootout_attempt(shootout, player_id, outcome):
    """
    Records a penalty attempt with strict backend validation:
    1. Shootout must be IN_PROGRESS.
    2. Next team is alternating (Team A, then Team B).
    3. Player must be eligible for next_team.
    4. Player rotation rule: cannot pick already-used player if unused eligible players remain in cycle.
    5. Valid outcome: GOAL, MISS, SAVED, POST.
    6. Outcome GOAL is marked successful (+1 goal).
    7. Evaluates initial five (after 5 kicks each) or sudden death round completion.
    8. Advances winner automatically upon completion.
    """
    with transaction.atomic():
        # Reload shootout with lock
        shootout = PenaltyShootout.objects.select_for_update().get(id=shootout.id)
        match = shootout.match

        if shootout.status == ShootoutStatus.COMPLETED:
            return {'success': False, 'error': "This penalty shootout is already completed."}

        state = get_shootout_state(shootout)
        next_team = state['next_team']
        current_round = state['current_round']
        current_phase = state['current_phase']
        attempt_order = state['next_attempt_order']
        available_players = state['available_players']

        # Validate outcome
        outcome = (outcome or '').upper().strip()
        valid_outcomes = dict(ShootoutOutcome.choices)
        if outcome not in valid_outcomes:
            return {'success': False, 'error': f"Invalid attempt outcome '{outcome}'."}

        # Validate player
        try:
            player = Player.objects.get(id=int(player_id), team=next_team)
        except (ValueError, TypeError, Player.DoesNotExist):
            return {'success': False, 'error': f"Player not found or does not belong to {next_team.name}."}

        available_ids = [p.id for p in available_players]
        if player.id not in available_ids:
            return {
                'success': False,
                'error': f"{player.full_name} is not eligible for this penalty attempt under the player rotation rules. Unused eligible players must take their penalty first."
            }

        # Calculate attempt number for this team
        this_team_attempts_count = PenaltyShootoutAttempt.objects.filter(
            shootout=shootout,
            team=next_team
        ).count()
        team_attempt_number = this_team_attempts_count + 1

        is_successful = (outcome == ShootoutOutcome.GOAL)

        # Create attempt
        attempt = PenaltyShootoutAttempt.objects.create(
            shootout=shootout,
            match=match,
            team=next_team,
            player=player,
            attempt_order=attempt_order,
            attempt_number=team_attempt_number,
            shootout_round=current_round,
            shootout_phase=current_phase,
            outcome=outcome,
            is_successful=is_successful
        )

        # Update shootout cumulative score
        if is_successful:
            if next_team.id == match.home_team_id:
                shootout.home_score += 1
            else:
                shootout.away_score += 1

        # Check completion condition:
        # Initial Five: both teams must complete all 5 attempts (total 10 attempts)
        winner = None

        if attempt_order == 10:
            # Both teams have finished Round 5
            if shootout.home_score > shootout.away_score:
                winner = match.home_team
            elif shootout.away_score > shootout.home_score:
                winner = match.away_team
            # If tied, winner remains None and next attempt will enter Sudden Death (Round 6)
        elif attempt_order > 10 and attempt_order % 2 == 0:
            # Sudden death round concluded (Team B just completed Round K >= 6)
            round_attempts = list(shootout.attempts.filter(shootout_round=current_round))
            home_att = next((a for a in round_attempts if a.team_id == match.home_team_id), None)
            away_att = next((a for a in round_attempts if a.team_id == match.away_team_id), None)
            if home_att and away_att:
                if home_att.is_successful and not away_att.is_successful:
                    winner = match.home_team
                elif away_att.is_successful and not home_att.is_successful:
                    winner = match.away_team
                # If both scored or both missed, tied! Next round continues.

        if winner:
            shootout.status = ShootoutStatus.COMPLETED
            shootout.winner = winner
            shootout.completed_at = timezone.now()
            shootout.save()

            # Update match record
            match.status = MatchStatus.COMPLETED
            match.penalties = True
            match.home_penalties = shootout.home_score
            match.away_penalties = shootout.away_score
            match.save(update_fields=['status', 'penalties', 'home_penalties', 'away_penalties'])

            # Automatic Knockout Progression
            advance_knockout_bracket(match.competition)
        else:
            shootout.save(update_fields=['home_score', 'away_score'])

        return {
            'success': True,
            'attempt': attempt,
            'is_completed': (shootout.status == ShootoutStatus.COMPLETED),
            'winner': winner,
            'shootout': shootout
        }


def undo_last_shootout_attempt(shootout):
    """
    Safely reverts the most recent penalty attempt and re-evaluates shootout state.
    """
    with transaction.atomic():
        shootout = PenaltyShootout.objects.select_for_update().get(id=shootout.id)
        last_attempt = shootout.attempts.order_by('-attempt_order').first()
        if not last_attempt:
            return {'success': False, 'error': "No penalty attempts to undo."}

        match = shootout.match
        last_attempt.delete()

        # Recalculate scores
        home_score = PenaltyShootoutAttempt.objects.filter(
            shootout=shootout,
            team_id=match.home_team_id,
            is_successful=True
        ).count()
        away_score = PenaltyShootoutAttempt.objects.filter(
            shootout=shootout,
            team_id=match.away_team_id,
            is_successful=True
        ).count()

        shootout.home_score = home_score
        shootout.away_score = away_score
        shootout.status = ShootoutStatus.IN_PROGRESS
        shootout.winner = None
        shootout.completed_at = None
        shootout.save()

        # Revert match status if it was completed by this shootout
        match.home_penalties = home_score
        match.away_penalties = away_score
        match.save(update_fields=['home_penalties', 'away_penalties'])

        return {'success': True}
