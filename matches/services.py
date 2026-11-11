from django.db.models import Count, Q
from matches.models import Match, MatchEvent, MatchEventType, MatchStatus
from teams.models import Player, Team


def get_competition_statistics(competition):
    """
    Computes top scorers, assist leaders, clean sheet records, disciplinary stats,
    and competition overview KPIs.
    """
    completed_matches = competition.matches.filter(status=MatchStatus.COMPLETED)
    total_matches_played = completed_matches.count()

    total_goals = 0
    for m in completed_matches:
        total_goals += (m.home_score or 0) + (m.away_score or 0)

    avg_goals_per_game = round(total_goals / total_matches_played, 2) if total_matches_played > 0 else 0.0

    # Top goal scorers in this competition
    top_scorers_qs = (
        MatchEvent.objects.filter(
            match__competition=competition,
            event_type__in=[MatchEventType.GOAL, MatchEventType.PENALTY]
        )
        .values('player_id', 'player__full_name', 'player__jersey_number', 'player__position', 'player__photo', 'player__photo_url', 'team_id', 'team__name', 'team__short_name')
        .annotate(
            goals_count=Count('id'),
            penalties_count=Count('id', filter=Q(event_type=MatchEventType.PENALTY))
        )
        .order_by('-goals_count', 'player__full_name')[:10]
    )

    top_scorers = []
    for rank, p in enumerate(top_scorers_qs, start=1):
        top_scorers.append({
            'rank': rank,
            'id': p['player_id'],
            'full_name': p['player__full_name'],
            'jersey_number': p['player__jersey_number'],
            'position': p['player__position'],
            'team_id': p['team_id'],
            'team_name': p['team__name'],
            'team_short_name': p['team__short_name'],
            'photo_url': p['player__photo_url'] or "/static/img/players/p1.jpg",
            'goals': p['goals_count'],
            'penalties': p['penalties_count']
        })

    # Top assist providers
    top_assists_qs = (
        MatchEvent.objects.filter(
            match__competition=competition,
            assist_player__isnull=False,
            event_type__in=[MatchEventType.GOAL, MatchEventType.PENALTY]
        )
        .values('assist_player_id', 'assist_player__full_name', 'assist_player__jersey_number', 'team_id', 'team__name', 'team__short_name')
        .annotate(assists_count=Count('id'))
        .order_by('-assists_count', 'assist_player__full_name')[:10]
    )

    top_assists = []
    for rank, a in enumerate(top_assists_qs, start=1):
        top_assists.append({
            'rank': rank,
            'id': a['assist_player_id'],
            'full_name': a['assist_player__full_name'],
            'jersey_number': a['assist_player__jersey_number'],
            'team_id': a['team_id'],
            'team_name': a['team__name'],
            'team_short_name': a['team__short_name'],
            'assists': a['assists_count']
        })

    # Disciplinary: Yellow and Red cards (Separate leaderboards + combined)
    yellows_qs = (
        MatchEvent.objects.filter(
            match__competition=competition,
            event_type=MatchEventType.YELLOW_CARD
        )
        .values('player_id', 'player__full_name', 'player__jersey_number', 'team_id', 'team__name')
        .annotate(yellows_count=Count('id'))
        .order_by('-yellows_count', 'player__full_name')[:10]
    )

    yellow_cards = []
    for rank, y in enumerate(yellows_qs, start=1):
        yellow_cards.append({
            'rank': rank,
            'id': y['player_id'],
            'full_name': y['player__full_name'],
            'jersey_number': y['player__jersey_number'],
            'team_id': y['team_id'],
            'team_name': y['team__name'],
            'yellow_cards': y['yellows_count'],
        })

    reds_qs = (
        MatchEvent.objects.filter(
            match__competition=competition,
            event_type=MatchEventType.RED_CARD
        )
        .values('player_id', 'player__full_name', 'player__jersey_number', 'team_id', 'team__name')
        .annotate(reds_count=Count('id'))
        .order_by('-reds_count', 'player__full_name')[:10]
    )

    red_cards = []
    for rank, r in enumerate(reds_qs, start=1):
        red_cards.append({
            'rank': rank,
            'id': r['player_id'],
            'full_name': r['player__full_name'],
            'jersey_number': r['player__jersey_number'],
            'team_id': r['team_id'],
            'team_name': r['team__name'],
            'red_cards': r['reds_count'],
        })

    cards_qs = (
        MatchEvent.objects.filter(
            match__competition=competition,
            event_type__in=[MatchEventType.YELLOW_CARD, MatchEventType.RED_CARD]
        )
        .values('player_id', 'player__full_name', 'player__jersey_number', 'team_id', 'team__name')
        .annotate(
            yellows=Count('id', filter=Q(event_type=MatchEventType.YELLOW_CARD)),
            reds=Count('id', filter=Q(event_type=MatchEventType.RED_CARD))
        )
        .order_by('-reds', '-yellows')[:10]
    )

    disciplinary = []
    for rank, c in enumerate(cards_qs, start=1):
        disciplinary.append({
            'rank': rank,
            'id': c['player_id'],
            'full_name': c['player__full_name'],
            'jersey_number': c['player__jersey_number'],
            'team_id': c['team_id'],
            'team_name': c['team__name'],
            'yellow_cards': c['yellows'],
            'red_cards': c['reds']
        })

    # Clean sheets: count for goalkeepers where opponent score was 0
    teams = competition.teams.all()
    clean_sheets = []
    for t in teams:
        gks = list(t.players.filter(position='GK'))
        if not gks:
            home_cs = completed_matches.filter(home_team=t, away_score=0).count()
            away_cs = completed_matches.filter(away_team=t, home_score=0).count()
            total_cs = home_cs + away_cs
            if total_cs > 0:
                clean_sheets.append({
                    'team': t,
                    'clean_sheets': total_cs,
                    'goalkeeper_name': f"{t.name} Goalkeeper"
                })
        else:
            for gk in gks:
                explicit = MatchEvent.objects.filter(
                    match__in=completed_matches,
                    team=t,
                    player=gk,
                    event_type=MatchEventType.CLEAN_SHEET
                ).count()
                if len(gks) == 1:
                    unassigned_home = completed_matches.filter(home_team=t, away_score=0).exclude(events__event_type=MatchEventType.CLEAN_SHEET, events__team=t).count()
                    unassigned_away = completed_matches.filter(away_team=t, home_score=0).exclude(events__event_type=MatchEventType.CLEAN_SHEET, events__team=t).count()
                    total = explicit + unassigned_home + unassigned_away
                else:
                    total = explicit

                if total > 0:
                    clean_sheets.append({
                        'team': t,
                        'clean_sheets': total,
                        'goalkeeper_name': gk.full_name
                    })
    clean_sheets = sorted(clean_sheets, key=lambda x: -x['clean_sheets'])[:8]
    for rank, cs in enumerate(clean_sheets, start=1):
        cs['rank'] = rank

    return {
        'total_matches_played': total_matches_played,
        'total_goals': total_goals,
        'avg_goals_per_game': avg_goals_per_game,
        'top_scorers': top_scorers,
        'top_assists': top_assists,
        'yellow_cards': yellow_cards,
        'red_cards': red_cards,
        'disciplinary': disciplinary,
        'clean_sheets': clean_sheets,
    }

