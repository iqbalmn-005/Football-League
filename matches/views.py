"""
Matches application views - Pure Django views for match scorecards, result entries, and events.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from accounts.decorators import approved_organizer_required
from matches.models import (
    Match, MatchStatus, MatchEvent, MatchEventType,
    PenaltyShootout, PenaltyShootoutAttempt,
    ShootoutPhase, ShootoutOutcome, ShootoutStatus
)
from teams.models import Player, PositionChoice
from standings.services import recalculate_competition_standings
from fixtures.services import advance_knockout_bracket
from matches.shootout_service import (
    get_or_create_shootout, get_shootout_state,
    record_shootout_attempt, undo_last_shootout_attempt,
    get_eligible_match_players
)
from datetime import datetime


def match_detail_view(request, match_id):
    """
    Django backend view: Renders full match details, team lineups, and match events timeline.
    """
    match = get_object_or_404(Match, id=match_id)
    home_events = match.events.filter(team=match.home_team).order_by('minute')
    away_events = match.events.filter(team=match.away_team).order_by('minute')
    all_events = match.events.all().order_by('minute')

    context = {
        'match': match,
        'home_events': home_events,
        'away_events': away_events,
        'all_events': all_events,
    }
    return render(request, 'match_detail.html', context) if request.headers.get('x-requested-with') != 'XMLHttpRequest' else JsonResponse({
        'id': match.id,
        'home_team': {'id': match.home_team.id, 'name': match.home_team.name, 'score': match.home_score},
        'away_team': {'id': match.away_team.id, 'name': match.away_team.name, 'score': match.away_score},
        'status': match.get_status_display(),
    })


def api_match_details(request, match_id):
    """
    Django JSON API endpoint: Returns structured match info, lineups, and timeline events.
    """
    match = get_object_or_404(Match, id=match_id)
    home_events = match.events.filter(team=match.home_team).order_by('minute')
    away_events = match.events.filter(team=match.away_team).order_by('minute')

    from standings.models import StandingEntry

    def get_ordinal(n):
        if 11 <= (n % 100) <= 13:
            suffix = 'th'
        else:
            suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
        return f"{n}{suffix}"

    home_standing = StandingEntry.objects.filter(competition=match.competition, team=match.home_team).first()
    away_standing = StandingEntry.objects.filter(competition=match.competition, team=match.away_team).first()

    home_rank = get_ordinal(home_standing.position) if home_standing and home_standing.position else ""
    away_rank = get_ordinal(away_standing.position) if away_standing and away_standing.position else ""

    data = {
        'id': match.id,
        'tournament_round': match.tournament_round,
        'match_date': match.match_date.strftime('%a, %d %b %Y') if match.match_date else '',
        'kickoff_time': match.kickoff_time.strftime('%H:%M') if match.kickoff_time else '',
        'venue': match.venue,
        'status': match.get_status_display(),
        'home_team': {
            'id': match.home_team.id,
            'name': match.home_team.name,
            'short_name': match.home_team.short_name,
            'score': match.home_score if match.home_score is not None else 0,
            'logo_url': match.home_team.get_logo_url(),
            'rank': home_rank,
            'players': [
                {'id': p.id, 'name': p.full_name, 'number': p.jersey_number, 'position': p.position}
                for p in match.home_team.players.filter(is_active=True).order_by('jersey_number', 'full_name')
            ]
        },
        'away_team': {
            'id': match.away_team.id,
            'name': match.away_team.name,
            'short_name': match.away_team.short_name,
            'score': match.away_score if match.away_score is not None else 0,
            'logo_url': match.away_team.get_logo_url(),
            'rank': away_rank,
            'players': [
                {'id': p.id, 'name': p.full_name, 'number': p.jersey_number, 'position': p.position}
                for p in match.away_team.players.filter(is_active=True).order_by('jersey_number', 'full_name')
            ]
        },
        'home_highlights': match.home_highlights,
        'away_highlights': match.away_highlights,
        'home_events': [
            {
                'id': e.id,
                'minute': e.minute,
                'event_type': e.event_type,
                'player_id': e.player_id,
                'player_name': e.player.full_name if e.player else 'Unknown',
                'assist_id': e.assist_player_id,
                'assist_name': e.assist_player.full_name if e.assist_player else '',
            }
            for e in home_events
        ],
        'away_events': [
            {
                'id': e.id,
                'minute': e.minute,
                'event_type': e.event_type,
                'player_id': e.player_id,
                'player_name': e.player.full_name if e.player else 'Unknown',
                'assist_id': e.assist_player_id,
                'assist_name': e.assist_player.full_name if e.assist_player else '',
            }
            for e in away_events
        ],
        'is_knockout': match.is_knockout,
        'extra_time_enabled': getattr(match.competition, 'extra_time_before_penalties', False),
        'extra_time_played': match.extra_time,
        'home_regular_score': match.home_regular_score,
        'away_regular_score': match.away_regular_score,
        'home_extra_time_score': match.home_extra_time_score,
        'away_extra_time_score': match.away_extra_time_score,
        'penalties': match.penalties,
        'home_penalties': match.home_penalties,
        'away_penalties': match.away_penalties,
        'has_shootout': hasattr(match, 'penalty_shootout') and match.penalty_shootout is not None,
        'shootout_completed': match.penalty_shootout.is_completed if (hasattr(match, 'penalty_shootout') and match.penalty_shootout) else False,
    }
    return JsonResponse(data)


@approved_organizer_required
def update_match_view(request, match_id):
    """
    Django backend view: Reschedule match date, kickoff time, venue, or status.
    """
    match = get_object_or_404(Match, id=match_id)

    if request.method == 'POST':
        date_str = request.POST.get('match_date')
        time_str = request.POST.get('kickoff_time')
        venue = request.POST.get('venue')
        status = request.POST.get('status')

        if date_str:
            match.match_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        if time_str:
            match.kickoff_time = datetime.strptime(time_str[:5], '%H:%M').time()
        if venue:
            match.venue = venue.strip()
        if status in [s.value for s in MatchStatus]:
            match.status = status

        match.save()
        messages.success(request, f"✓ Match {match.home_display_name} vs {match.away_display_name} updated successfully.")

    return redirect(f"/organizer/{match.competition.id}/?tab=fixtures")


@approved_organizer_required
def enter_match_result_view(request, match_id):
    """
    Django backend view: Records match final scores, goals, assists, penalty flags,
    and disciplinary cards. Automatically triggers standings recalculation in Django.
    """
    match = get_object_or_404(Match, id=match_id)

    if not match.home_team or not match.away_team:
        messages.error(request, "Cannot record results for a match where participating teams are not yet determined.")
        return redirect(f"/organizer/{match.competition.id}/?tab=fixtures")

    if request.method == 'POST':
        try:
            home_score = max(0, int(request.POST.get('home_score', 0)))
            away_score = max(0, int(request.POST.get('away_score', 0)))
        except (ValueError, TypeError):
            messages.error(request, "Invalid scores provided.")
            return redirect(f"/organizer/{match.competition.id}/?tab=fixtures")

        # Store regular-time and extra-time breakdown
        is_extra_time = (request.POST.get('extra_time') in ['1', 'true', 'on'])
        home_reg = request.POST.get('home_regular_score')
        away_reg = request.POST.get('away_regular_score')
        home_et = request.POST.get('home_extra_time_score')
        away_et = request.POST.get('away_extra_time_score')

        match.home_score = home_score
        match.away_score = away_score
        match.home_regular_score = int(home_reg) if (home_reg is not None and str(home_reg).strip().isdigit()) else home_score
        match.away_regular_score = int(away_reg) if (away_reg is not None and str(away_reg).strip().isdigit()) else away_score
        match.extra_time = is_extra_time
        if is_extra_time:
            match.home_extra_time_score = int(home_et) if (home_et is not None and str(home_et).strip().isdigit()) else home_score
            match.away_extra_time_score = int(away_et) if (away_et is not None and str(away_et).strip().isdigit()) else away_score
        else:
            match.home_extra_time_score = None
            match.away_extra_time_score = None

        is_tied = (home_score == away_score)
        is_knockout = match.is_knockout
        has_et_setting = getattr(match.competition, 'extra_time_before_penalties', False)

        if is_knockout and is_tied:
            # Knockout matches cannot end in a draw
            match.status = MatchStatus.LIVE
        else:
            match.status = MatchStatus.COMPLETED

        match.save()

        # Clear existing match events for clean replacement
        match.events.all().delete()

        # 1. Process Home Team Goals
        home_scorers = request.POST.getlist('home_goal_scorer')
        home_assists = request.POST.getlist('home_goal_assist')
        home_minutes = request.POST.getlist('home_goal_minute')

        for i in range(min(home_score, len(home_scorers))):
            scorer_val = home_scorers[i].strip()
            if not scorer_val:
                continue

            is_penalty = request.POST.get(f'home_goal_penalty_{i}') in ['1', 'on', 'true']
            event_type = MatchEventType.PENALTY if is_penalty else MatchEventType.GOAL

            # Resolve Scorer Player
            player = None
            try:
                player = Player.objects.get(id=int(scorer_val), team=match.home_team)
            except (ValueError, Player.DoesNotExist):
                player = Player.objects.filter(team=match.home_team, full_name__iexact=scorer_val).first()
                if not player and scorer_val:
                    player = Player.objects.create(
                        team=match.home_team,
                        full_name=scorer_val,
                        jersey_number=match.home_team.players.count() + 1
                    )

            # Resolve Assist Player (Optional)
            assist_player = None
            if i < len(home_assists) and home_assists[i].strip():
                try:
                    assist_player = Player.objects.get(id=int(home_assists[i].strip()), team=match.home_team)
                except (ValueError, Player.DoesNotExist):
                    pass

            # Resolve Minute (default 0 when omitted)
            minute = 0
            if i < len(home_minutes) and home_minutes[i].strip():
                try:
                    minute = max(1, min(130, int(home_minutes[i].strip())))
                except (ValueError, TypeError):
                    pass

            if player:
                MatchEvent.objects.create(
                    match=match,
                    team=match.home_team,
                    player=player,
                    assist_player=assist_player,
                    event_type=event_type,
                    minute=minute
                )

        # 2. Process Away Team Goals
        away_scorers = request.POST.getlist('away_goal_scorer')
        away_assists = request.POST.getlist('away_goal_assist')
        away_minutes = request.POST.getlist('away_goal_minute')

        for i in range(min(away_score, len(away_scorers))):
            scorer_val = away_scorers[i].strip()
            if not scorer_val:
                continue

            is_penalty = request.POST.get(f'away_goal_penalty_{i}') in ['1', 'on', 'true']
            event_type = MatchEventType.PENALTY if is_penalty else MatchEventType.GOAL

            player = None
            try:
                player = Player.objects.get(id=int(scorer_val), team=match.away_team)
            except (ValueError, Player.DoesNotExist):
                player = Player.objects.filter(team=match.away_team, full_name__iexact=scorer_val).first()
                if not player and scorer_val:
                    player = Player.objects.create(
                        team=match.away_team,
                        full_name=scorer_val,
                        jersey_number=match.away_team.players.count() + 1
                    )

            assist_player = None
            if i < len(away_assists) and away_assists[i].strip():
                try:
                    assist_player = Player.objects.get(id=int(away_assists[i].strip()), team=match.away_team)
                except (ValueError, Player.DoesNotExist):
                    pass

            minute = 0
            if i < len(away_minutes) and away_minutes[i].strip():
                try:
                    minute = max(1, min(130, int(away_minutes[i].strip())))
                except (ValueError, TypeError):
                    pass

            if player:
                MatchEvent.objects.create(
                    match=match,
                    team=match.away_team,
                    player=player,
                    assist_player=assist_player,
                    event_type=event_type,
                    minute=minute
                )

        # 3. Process Disciplinary Cards (Yellow & Red Cards)
        card_teams = request.POST.getlist('card_team')
        card_players = request.POST.getlist('card_player')
        card_types = request.POST.getlist('card_type')
        card_minutes = request.POST.getlist('card_minute')

        for i in range(len(card_players)):
            p_val = card_players[i].strip()
            if not p_val:
                continue
            t_side = card_teams[i].strip() if i < len(card_teams) else 'home'
            team = match.home_team if t_side == 'home' else match.away_team
            c_type = card_types[i].strip() if i < len(card_types) else MatchEventType.YELLOW_CARD
            if c_type not in [MatchEventType.YELLOW_CARD, MatchEventType.RED_CARD]:
                c_type = MatchEventType.YELLOW_CARD

            minute = 0
            if i < len(card_minutes) and card_minutes[i].strip():
                try:
                    minute = max(1, min(130, int(card_minutes[i].strip())))
                except (ValueError, TypeError):
                    pass

            player = None
            try:
                player = Player.objects.get(id=int(p_val))
            except (ValueError, Player.DoesNotExist):
                player = Player.objects.filter(team=team, full_name__iexact=p_val).first()

            if player:
                MatchEvent.objects.create(
                    match=match,
                    team=team,
                    player=player,
                    event_type=c_type,
                    minute=minute
                )

        # 4. Process Clean Sheets (MatchEventType.CLEAN_SHEET)
        # If opponent scored 0, the keeping team kept a clean sheet.
        # When team has multiple GKs, organizer selects which keeper earned the clean sheet.
        # If team has exactly 1 GK, it is assigned automatically to that keeper.

        # Home team clean sheet (away_score == 0)
        if away_score == 0:
            home_gks = list(match.home_team.players.filter(position=PositionChoice.GK))
            home_cs_keeper_id = request.POST.get('home_clean_sheet_keeper')
            keeper = None
            if home_cs_keeper_id:
                try:
                    keeper = match.home_team.players.get(id=int(home_cs_keeper_id))
                except (ValueError, Player.DoesNotExist):
                    keeper = None
            if not keeper and len(home_gks) == 1:
                keeper = home_gks[0]
            if keeper:
                MatchEvent.objects.create(
                    match=match,
                    team=match.home_team,
                    player=keeper,
                    event_type=MatchEventType.CLEAN_SHEET,
                    minute=90,
                    description=f"Clean sheet kept by {keeper.full_name}"
                )

        # Away team clean sheet (home_score == 0)
        if home_score == 0:
            away_gks = list(match.away_team.players.filter(position=PositionChoice.GK))
            away_cs_keeper_id = request.POST.get('away_clean_sheet_keeper')
            keeper = None
            if away_cs_keeper_id:
                try:
                    keeper = match.away_team.players.get(id=int(away_cs_keeper_id))
                except (ValueError, Player.DoesNotExist):
                    keeper = None
            if not keeper and len(away_gks) == 1:
                keeper = away_gks[0]
            if keeper:
                MatchEvent.objects.create(
                    match=match,
                    team=match.away_team,
                    player=keeper,
                    event_type=MatchEventType.CLEAN_SHEET,
                    minute=90,
                    description=f"Clean sheet kept by {keeper.full_name}"
                )

        # If knockout match ended in a tie, initiate or continue penalty shootout
        if is_knockout and is_tied:
            if has_et_setting and not is_extra_time:
                messages.warning(
                    request,
                    f"Regular time ended tied {home_score}–{away_score}. Extra Time is enabled for this tournament before penalties. Please record the extra-time score."
                )
                return redirect(f"/organizer/{match.competition.id}/?tab=fixtures")

            shootout = get_or_create_shootout(match)
            messages.info(
                request,
                f"Knockout match tied {home_score}–{away_score}! Proceeding to Penalty Shootout."
            )
            return redirect(f"/organizer/match/{match.id}/shootout/")

        # Trigger automatic standings recomputation
        recalculate_competition_standings(match.competition)

        # Advance knockout brackets (e.g. Page-McIntyre Preliminary & Grand Finals)
        advance_knockout_bracket(match.competition)

        messages.success(
            request,
            f"✓ Official Result Confirmed: {match.home_display_name} {home_score} - {away_score} {match.away_display_name}. Goals, assists, penalties, and cards updated!"
        )

    return redirect(f"/organizer/{match.competition.id}/?tab=fixtures")


@approved_organizer_required
def penalty_shootout_view(request, match_id):
    """
    Renders the dedicated Futbolix Stadium Night responsive Penalty Shootout interface.
    Available ONLY for knockout matches when tied.
    """
    match = get_object_or_404(Match, id=match_id)
    comp = match.competition

    # Validation: Only knockout matches
    if not match.is_knockout:
        messages.error(request, "Penalty shootouts are available only for knockout matches.")
        return redirect(f"/organizer/{comp.id}/?tab=fixtures")

    # Participating teams must be known
    if not match.home_team or not match.away_team:
        messages.error(request, "Cannot start shootout before participating teams are determined.")
        return redirect(f"/organizer/{comp.id}/?tab=fixtures")

    # Default to 0-0 if scores not yet entered
    if match.home_score is None or match.away_score is None:
        match.home_score = 0
        match.away_score = 0
        match.status = MatchStatus.LIVE
        match.save(update_fields=['home_score', 'away_score', 'status'])

    # Tied check: unless already completed with penalties, match score must be tied
    if match.home_score != match.away_score and not match.penalties:
        messages.error(request, f"Cannot start penalty shootout: Match score is not tied ({match.home_score} - {match.away_score}).")
        return redirect(f"/organizer/{comp.id}/?tab=fixtures")

    shootout = get_or_create_shootout(match)
    state = get_shootout_state(shootout)

    context = {
        'match': match,
        'competition': comp,
        'shootout': shootout,
        'state': state,
    }
    return render(request, 'penalty_shootout.html', context)


@approved_organizer_required
def api_record_penalty_attempt(request, match_id):
    """
    JSON API: Records a single penalty attempt with strict backend validation
    (alternating teams, eligible players, player rotation rules, sudden death).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    match = get_object_or_404(Match, id=match_id)
    if not match.is_knockout:
        return JsonResponse({'success': False, 'error': 'Penalty shootouts are available only for knockout matches.'}, status=400)

    shootout = get_or_create_shootout(match)
    player_id = request.POST.get('player_id')
    outcome = request.POST.get('outcome')

    if not player_id:
        return JsonResponse({'success': False, 'error': 'Player ID is required.'}, status=400)
    if not outcome:
        return JsonResponse({'success': False, 'error': 'Attempt outcome is required.'}, status=400)

    res = record_shootout_attempt(shootout, player_id, outcome)
    if not res.get('success'):
        return JsonResponse(res, status=400)

    state = get_shootout_state(shootout)
    return JsonResponse({
        'success': True,
        'is_completed': state['is_completed'],
        'winner_id': state['winner'].id if state['winner'] else None,
        'winner_name': state['winner'].name if state['winner'] else None,
        'home_score': state['home_score'],
        'away_score': state['away_score'],
        'current_round': state['current_round'],
        'current_phase': state['current_phase'],
        'next_team_id': state['next_team'].id if state['next_team'] else None,
        'next_team_name': state['next_team'].name if state['next_team'] else None,
        'available_players': [
            {'id': p.id, 'name': p.full_name, 'number': p.jersey_number, 'position': p.position}
            for p in state['available_players']
        ],
    })


@approved_organizer_required
def api_undo_penalty_attempt(request, match_id):
    """
    JSON API: Reverts the most recent penalty attempt.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    match = get_object_or_404(Match, id=match_id)
    shootout = get_or_create_shootout(match)
    res = undo_last_shootout_attempt(shootout)
    if not res.get('success'):
        return JsonResponse(res, status=400)

    state = get_shootout_state(shootout)
    return JsonResponse({
        'success': True,
        'home_score': state['home_score'],
        'away_score': state['away_score'],
        'current_round': state['current_round'],
        'current_phase': state['current_phase'],
        'next_team_id': state['next_team'].id if state['next_team'] else None,
        'next_team_name': state['next_team'].name if state['next_team'] else None,
        'available_players': [
            {'id': p.id, 'name': p.full_name, 'number': p.jersey_number, 'position': p.position}
            for p in state['available_players']
        ],
    })


def api_shootout_state(request, match_id):
    """
    JSON API: Returns the live serialized shootout state for a match.
    """
    match = get_object_or_404(Match, id=match_id)
    shootout = get_or_create_shootout(match)
    state = get_shootout_state(shootout)

    data = {
        'match_id': match.id,
        'is_completed': state['is_completed'],
        'winner': {'id': state['winner'].id, 'name': state['winner'].name} if state['winner'] else None,
        'home_team': {'id': match.home_team.id, 'name': match.home_team.name, 'score': state['home_score']},
        'away_team': {'id': match.away_team.id, 'name': match.away_team.name, 'score': state['away_score']},
        'current_round': state['current_round'],
        'current_phase': state['current_phase'],
        'next_team': {'id': state['next_team'].id, 'name': state['next_team'].name} if state['next_team'] else None,
        'available_players': [
            {'id': p.id, 'name': p.full_name, 'number': p.jersey_number, 'position': p.position}
            for p in state['available_players']
        ],
        'attempts': [
            {
                'id': a.id,
                'order': a.attempt_order,
                'round': a.shootout_round,
                'phase': a.shootout_phase,
                'team_id': a.team_id,
                'team_name': a.team.name,
                'player_id': a.player_id,
                'player_name': a.player.full_name,
                'player_number': a.player.jersey_number,
                'outcome': a.outcome,
                'is_successful': a.is_successful,
            }
            for a in state['attempts']
        ]
    }
    return JsonResponse(data)
