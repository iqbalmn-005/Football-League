"""
Leagues application views - Unified export for public competition viewing and organizer administration.
"""
from leagues.public_views import landing_page, competition_viewer, team_profile, api_match_details, api_player_details
from leagues.organizer_views import (
    organizer_dashboard, organizer_create_competition, update_competition_view,
    generate_fixtures_view, add_fixture_view, update_match_view, enter_match_result_view,
    add_team_view, delete_team_view, add_player_view, recalculate_standings_view, invite_co_organizer_view
)

__all__ = [
    'landing_page',
    'competition_viewer',
    'team_profile',
    'api_match_details',
    'api_player_details',
    'organizer_dashboard',
    'organizer_create_competition',
    'update_competition_view',
    'generate_fixtures_view',
    'add_fixture_view',
    'update_match_view',
    'enter_match_result_view',
    'add_team_view',
    'delete_team_view',
    'add_player_view',
    'recalculate_standings_view',
    'invite_co_organizer_view',
]
