with open('front/organizer_index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace button area
old_btn_block = """                            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                                <form method="post" action="/organizer/{{ active_competition.id }}/generate-fixtures/"
                                    style="display:inline;">
                                    {% csrf_token %}
                                    <button class="btn btn-outline" type="submit"
                                        onclick="return confirm('Generate round-robin fixtures for all {{ comp_teams.count }} registered teams?');">
                                        ⚡ Generate Fixtures (Berger Algorithm)
                                    </button>
                                </form>
                                <button class="btn btn-primary" onclick="openAddFixtureModal()">+ Add Match</button>
                            </div>"""

new_btn_block = """                            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                                <a href="/organizer/{{ active_competition.id }}/fixture-generator/" class="btn btn-primary">
                                    ⚡ Smart Fixture Generator Wizard
                                </a>
                                <button class="btn btn-outline" type="button" onclick="openAddFixtureModal()">+ Add Match Manually</button>
                            </div>"""

content = content.replace(old_btn_block, new_btn_block)

# Replace empty state
old_empty = """                                    {% empty %}
                                    <tr>
                                        <td colspan="7" style="text-align:center;padding:30px;color:var(--muted)">
                                            No fixtures created yet. Click "Generate Fixtures" to automatically generate
                                            round-robin matchweeks!
                                        </td>
                                    </tr>"""

new_empty = """                                    {% empty %}
                                    <tr>
                                        <td colspan="7" style="text-align:center;padding:40px 20px;color:var(--muted)">
                                            <div style="font-size:36px;margin-bottom:8px;">📅</div>
                                            <strong style="display:block;font-size:16px;color:var(--dark);margin-bottom:4px;">No fixtures scheduled yet</strong>
                                            <p style="font-size:12px;margin:0 auto 16px;max-width:500px;">Use the Touchline Smart Fixture Generator to configure format, rest days, venues, and blackout dates to generate a balanced schedule automatically.</p>
                                            <a href="/organizer/{{ active_competition.id }}/fixture-generator/" class="btn btn-primary" style="font-size:13px;padding:9px 20px;">
                                                ⚡ Open Fixture Generation Wizard →
                                            </a>
                                        </td>
                                    </tr>"""

content = content.replace(old_empty, new_empty)

with open('front/organizer_index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated front/organizer_index.html fixtures tab successfully!")

