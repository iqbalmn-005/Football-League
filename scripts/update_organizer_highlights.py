import os

path_org = 'front/organizer_index.html'
with open(path_org, 'r', encoding='utf-8') as f:
    text = f.read().replace('\r\n', '\n')

css_insert = """
        /* HIGHLIGHT NEXT MATCH & LAST RESULT STYLES */
        .highlight-next-match-row {
            background: linear-gradient(90deg, rgba(180, 245, 107, 0.18) 0%, rgba(180, 245, 107, 0.04) 100%) !important;
            border-left: 4px solid var(--green, #b4f56b) !important;
        }

        .highlight-next-match-row:hover {
            background: linear-gradient(90deg, rgba(180, 245, 107, 0.26) 0%, rgba(180, 245, 107, 0.08) 100%) !important;
        }

        .highlight-last-match-row {
            background: linear-gradient(90deg, rgba(56, 189, 248, 0.16) 0%, rgba(56, 189, 248, 0.04) 100%) !important;
            border-left: 4px solid #0284c7 !important;
        }

        .highlight-last-match-row:hover {
            background: linear-gradient(90deg, rgba(56, 189, 248, 0.26) 0%, rgba(56, 189, 248, 0.08) 100%) !important;
        }

        .badge-next-match {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #101b16;
            color: #b4f56b;
            font-size: 10px;
            font-weight: 900;
            padding: 2px 7px;
            border-radius: 4px;
            letter-spacing: 0.4px;
            border: 1px solid rgba(180, 245, 107, 0.45);
            box-shadow: 0 0 10px rgba(180, 245, 107, 0.35);
            white-space: nowrap;
        }

        .badge-last-match {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #082f49;
            color: #7dd3fc;
            font-size: 10px;
            font-weight: 900;
            padding: 2px 7px;
            border-radius: 4px;
            letter-spacing: 0.4px;
            border: 1px solid rgba(56, 189, 248, 0.45);
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.3);
            white-space: nowrap;
        }
"""

# Insert CSS before </style>
style_close = "</style>"
idx = text.find(style_close)
assert idx != -1, "</style> not found in organizer_index.html"
text = text[:idx] + css_insert + text[idx:]

# 1. Update Overview upcoming preview
overview_old = """                                        {% for m in upcoming_matches|slice:":5" %}
                                        <tr>
                                            <td>
                                                <strong>{{ m.home_team.short_name }} vs {{ m.away_team.short_name }}</strong><br>
                                                <small style="color:var(--muted)">{{ m.tournament_round }}</small>
                                            </td>"""

overview_new = """                                        {% for m in upcoming_matches|slice:":5" %}
                                        <tr {% if next_match and m.id == next_match.id %}class="highlight-next-match-row"{% endif %}>
                                            <td>
                                                <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                                                    <strong>{{ m.home_team.short_name }} vs {{ m.away_team.short_name }}</strong>
                                                    {% if next_match and m.id == next_match.id %}
                                                    <span class="badge-next-match">⚡ NEXT MATCH</span>
                                                    {% endif %}
                                                </div>
                                                <small style="color:var(--muted)">{{ m.tournament_round }}</small>
                                            </td>"""

assert overview_old in text, "overview_old not found"
text = text.replace(overview_old, overview_new, 1)

# 2. Update Fixtures tab
fixtures_old = """                                    {% for m in all_matches %}
                                    <tr>
                                        <td><strong>{{ m.tournament_round }}</strong></td>"""

fixtures_new = """                                    {% for m in all_matches %}
                                    <tr {% if next_match and m.id == next_match.id %}class="highlight-next-match-row"{% endif %}>
                                        <td>
                                            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                                                <strong>{{ m.tournament_round }}</strong>
                                                {% if next_match and m.id == next_match.id %}
                                                <span class="badge-next-match">⚡ NEXT MATCH</span>
                                                {% endif %}
                                            </div>
                                        </td>"""

assert fixtures_old in text, "fixtures_old not found"
text = text.replace(fixtures_old, fixtures_new, 1)

# 3. Update Results tab
results_old = """                                    {% for m in all_matches %}
                                    <tr>
                                        <td><strong>{{ m.tournament_round }}</strong></td>"""

results_new = """                                    {% for m in all_matches %}
                                    <tr {% if last_match and m.id == last_match.id %}class="highlight-last-match-row"{% endif %}>
                                        <td>
                                            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                                                <strong>{{ m.tournament_round }}</strong>
                                                {% if last_match and m.id == last_match.id %}
                                                <span class="badge-last-match">🏆 LATEST RESULT</span>
                                                {% endif %}
                                            </div>
                                        </td>"""

assert results_old in text, "results_old not found in text"
text = text.replace(results_old, results_new, 1)

with open(path_org, 'w', encoding='utf-8') as f:
    f.write(text)

print("[OK] front/organizer_index.html updated with fixture and result highlighting.")

