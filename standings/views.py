"""
Standings application views - Pure Django views for standings calculation and table viewing.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import approved_organizer_required
from leagues.models import Competition
from standings.models import StandingEntry
from standings.services import recalculate_competition_standings


def standings_view(request, comp_id):
    """
    Django backend view: Renders the points table for a competition.
    """
    competition = get_object_or_404(Competition, id=comp_id)
    standings = StandingEntry.objects.filter(competition=competition).select_related('team').order_by('position')
    return render(request, 'standings_table.html', {
        'competition': competition,
        'standings': standings,
    })


@approved_organizer_required
def recalculate_standings_view(request, comp_id):
    """
    Django backend view: Explicitly triggers full recalculation of points, GD, GF, and 5-match form in Django.
    """
    comp = get_object_or_404(Competition, id=comp_id)
    updated = recalculate_competition_standings(comp)
    messages.success(request, f"✓ Standings recomputed in Django: {len(updated)} team positions refreshed.")
    return redirect(f"/organizer/{comp.id}/?tab=standings")
