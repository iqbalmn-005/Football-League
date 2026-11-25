"""
URL configuration for Football project (FUTBOLIX).
Pure Django application routing across all modular Django apps.
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from accounts import views as account_views
from accounts import admin_views
from leagues import views as league_views
from fixtures import views as fixture_views
from matches import views as match_views
from standings import views as standing_views
from teams import views as team_views

urlpatterns = [
    # Built-in Django Admin
    path('admin/', admin.site.urls),

    # Public / Viewer Routes (leagues & teams apps)
    path('', league_views.landing_page, name='landing_page'),
    path('competitions/', league_views.all_competitions_view, name='all_competitions'),
    path('leagues/', league_views.all_competitions_view, name='all_leagues'),
    path('competition/<int:comp_id>/', league_views.competition_viewer, name='competition_viewer'),
    path('league/<int:comp_id>/', league_views.competition_viewer, name='league_viewer'),
    path('team/<int:team_id>/', team_views.team_profile, name='team_profile'),
    path('404/', league_views.custom_404_view, name='custom_404'),
    path('500/', league_views.custom_500_view, name='custom_500'),

    # JSON APIs for Interactive Modals (matches & teams apps)
    path('api/match/<int:match_id>/', match_views.api_match_details, name='api_match_details'),
    path('api/player/<int:player_id>/', team_views.api_player_details, name='api_player_details'),

    # Authentication & Accounts (accounts app)
    path('login/', account_views.login_view, name='login'),
    path('register/', account_views.register_view, name='register'),
    path('logout/', account_views.logout_view, name='logout'),
    path('dashboard/', account_views.dashboard_dispatch, name='dashboard_dispatch'),
    path('organizer/apply/', account_views.organizer_apply_view, name='organizer_apply'),
    path('organizer/status/', account_views.organizer_status_view, name='organizer_status'),

    # Super Admin Console (accounts app)
    path('super-admin/', admin_views.super_admin_dashboard, name='super_admin_dashboard'),
    path('super-admin/application/<int:app_id>/approve/', admin_views.approve_application, name='approve_application'),
    path('super-admin/application/<int:app_id>/reject/', admin_views.reject_application, name='reject_application'),
    path('super-admin/organizer/<int:user_id>/toggle-status/', admin_views.toggle_organizer_status, name='toggle_organizer_status'),
    path('organizer/<int:user_id>/details/', admin_views.organizer_detail_page, name='organizer_detail_page'),
    path('organizer/profile/<int:user_id>/', admin_views.organizer_detail_page, name='organizer_profile_view'),
    path('super-admin/organizer/<int:user_id>/', admin_views.organizer_detail_page, name='super_admin_organizer_detail'),
    path('super-admin/competition/create/', admin_views.create_competition, name='create_competition'),
    path('super-admin/competition/<int:comp_id>/assign/', admin_views.assign_competition, name='assign_competition'),
    path('super-admin/competition/<int:comp_id>/transfer/', admin_views.transfer_competition, name='transfer_competition'),
    path('super-admin/competition/<int:comp_id>/approve/', admin_views.approve_competition, name='approve_competition'),
    path('super-admin/competition/<int:comp_id>/reject/', admin_views.reject_competition, name='reject_competition'),
    path('super-admin/settings/update/', admin_views.update_platform_settings, name='update_platform_settings'),

    # League Organizer Console (leagues, fixtures, matches, teams, standings apps)
    path('organizer/', league_views.organizer_dashboard, name='organizer_dashboard'),
    path('organizer.html', league_views.organizer_dashboard, name='organizer_html'),
    path('organizer/<int:comp_id>/', league_views.organizer_dashboard, name='organizer_competition_dashboard'),
    path('organizer/competition/create/', league_views.organizer_create_competition, name='organizer_create_competition'),
    path('organizer/<int:comp_id>/generate-fixtures/', fixture_views.generate_fixtures_view, name='generate_fixtures'),
    path('organizer/<int:comp_id>/fixture-generator/', fixture_views.fixture_generator_page, name='fixture_generator_page'),
    path('organizer/<int:comp_id>/api/generate-preview/', fixture_views.api_generate_fixture_preview, name='api_generate_fixture_preview'),
    path('organizer/<int:comp_id>/api/revalidate-fixtures/', fixture_views.api_revalidate_fixtures, name='api_revalidate_fixtures'),
    path('organizer/<int:comp_id>/api/publish-fixtures/', fixture_views.api_publish_fixtures, name='api_publish_fixtures'),
    path('organizer/<int:comp_id>/fixture/add/', fixture_views.add_fixture_view, name='add_fixture'),
    path('organizer/match/<int:match_id>/update/', match_views.update_match_view, name='update_match'),
    path('organizer/match/<int:match_id>/result/', match_views.enter_match_result_view, name='enter_match_result'),
    path('organizer/match/<int:match_id>/shootout/', match_views.penalty_shootout_view, name='penalty_shootout'),
    path('organizer/match/<int:match_id>/shootout/attempt/', match_views.api_record_penalty_attempt, name='api_record_penalty_attempt'),
    path('organizer/match/<int:match_id>/shootout/undo/', match_views.api_undo_penalty_attempt, name='api_undo_penalty_attempt'),
    path('api/match/<int:match_id>/shootout/', match_views.api_shootout_state, name='api_shootout_state'),
    path('organizer/<int:comp_id>/team/add/', team_views.add_team_view, name='add_team'),
    path('organizer/<int:comp_id>/team/<int:team_id>/delete/', team_views.delete_team_view, name='delete_team'),
    path('organizer/team/<int:team_id>/delete/', team_views.delete_team_view, name='delete_team_direct'),
    path('organizer/team/<int:team_id>/', team_views.organizer_team_detail, name='organizer_team_detail'),
    path('organizer/team/<int:team_id>/player/add/', team_views.add_player_view, name='add_player'),
    path('organizer/team/<int:team_id>/player/<int:player_id>/edit/', team_views.edit_player_view, name='edit_player'),
    path('organizer/team/<int:team_id>/player/<int:player_id>/delete/', team_views.delete_player_view, name='delete_player'),
    path('organizer/<int:comp_id>/recalculate-standings/', standing_views.recalculate_standings_view, name='recalculate_standings'),
    path('organizer/<int:comp_id>/invite-organizer/', league_views.invite_co_organizer_view, name='invite_co_organizer'),
    path('organizer/<int:comp_id>/groups/distribute/', league_views.api_distribute_teams, name='api_distribute_teams'),
    path('organizer/<int:comp_id>/groups/confirm/', league_views.api_confirm_groups, name='api_confirm_groups'),
    path('organizer/<int:comp_id>/groups/generate-fixtures/', league_views.api_generate_group_fixtures, name='api_generate_group_fixtures'),
    path('organizer/<int:comp_id>/groups/qualification/', league_views.api_update_qualification_settings, name='api_update_qualification_settings'),
    path('organizer/<int:comp_id>/groups/generate-knockout/', league_views.api_generate_knockout_stage, name='api_generate_knockout_stage'),
    path('api/competition/<int:comp_id>/groups/status/', league_views.api_group_status, name='api_group_status'),
    path('organizer/<int:comp_id>/update/', league_views.update_competition_view, name='update_competition'),
    path('organizer/<int:comp_id>/edit/', league_views.update_competition_view, name='edit_competition'),
    path('organizer/<int:comp_id>/delete/', league_views.delete_competition_view, name='delete_competition'),
    path('super-admin/competition/<int:comp_id>/delete/', league_views.delete_competition_view, name='delete_competition_admin'),
]

from django.views.static import serve
from django.urls import re_path

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATICFILES_DIRS[0]}),
]

# Custom production error handlers
handler404 = 'leagues.public_views.custom_404_view'
handler500 = 'leagues.public_views.custom_500_view'

