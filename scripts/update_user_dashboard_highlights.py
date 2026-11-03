import os

path_user = 'front/user_dashboard.html'
with open(path_user, 'r', encoding='utf-8') as f:
    text = f.read().replace('\r\n', '\n')

css_insert = """
        /* HIGHLIGHT NEXT MATCH & LAST RESULT CARDS */
        .highlight-next-match-card {
            border: 2px solid var(--green-dark, #245d3c) !important;
            background: linear-gradient(180deg, #ffffff 0%, #f7fee7 100%) !important;
            box-shadow: 0 10px 28px rgba(36, 93, 60, 0.18) !important;
            position: relative;
        }

        .status-badge-next {
            background: #101b16;
            color: #b4f56b;
            font-size: 10px;
            font-weight: 900;
            padding: 3px 8px;
            border-radius: 4px;
            letter-spacing: 0.5px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            border: 1px solid rgba(180, 245, 107, 0.45);
            box-shadow: 0 0 10px rgba(180, 245, 107, 0.35);
        }

        .highlight-last-match-card {
            border: 2px solid #0284c7 !important;
            background: linear-gradient(180deg, #ffffff 0%, #f0f9ff 100%) !important;
            box-shadow: 0 10px 28px rgba(2, 132, 199, 0.18) !important;
            position: relative;
        }

        .status-badge-latest {
            background: #0c4a6e;
            color: #bae6fd;
            font-size: 10px;
            font-weight: 900;
            padding: 3px 8px;
            border-radius: 4px;
            letter-spacing: 0.5px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            border: 1px solid rgba(56, 189, 248, 0.45);
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.25);
        }
"""

style_close = "</style>"
idx = text.find(style_close)
assert idx != -1, "</style> not found in user_dashboard.html"
text = text[:idx] + css_insert + text[idx:]

# 1. Update upcoming matches in user_dashboard
upcoming_old = """                    {% for m in upcoming_matches %}
                    <div class="fixture-card" onclick="openMatchModal('{{ m.id }}')"
                        title="Click to view match details">
                        <div>
                            <div class="fixture-card-header">
                                <span>{{ m.match_date|date:"D, d M"|upper }} · {{ m.kickoff_time|time:"H:i A" }}</span>
                                <span class="status-badge-upcoming">UPCOMING</span>
                            </div>"""

upcoming_new = """                    {% for m in upcoming_matches %}
                    <div class="fixture-card {% if next_match and m.id == next_match.id or forloop.first %}highlight-next-match-card{% endif %}" onclick="openMatchModal('{{ m.id }}')"
                        title="Click to view match details">
                        <div>
                            <div class="fixture-card-header">
                                <span>{{ m.match_date|date:"D, d M"|upper }} · {{ m.kickoff_time|time:"H:i A" }}</span>
                                {% if next_match and m.id == next_match.id or forloop.first %}
                                <span class="status-badge-next">⚡ NEXT MATCH</span>
                                {% else %}
                                <span class="status-badge-upcoming">UPCOMING</span>
                                {% endif %}
                            </div>"""

assert upcoming_old in text, "upcoming_old not found in user_dashboard.html"
text = text.replace(upcoming_old, upcoming_new, 1)

# 2. Update results in user_dashboard
results_old = """                    {% for m in completed_matches %}
                    <div class="fixture-card" onclick="openMatchModal('{{ m.id }}')" title="Click to view scorecard">
                        <div>
                            <div class="fixture-card-header">
                                <span>{{ m.match_date|date:"D, d M"|upper }}</span>
                                <span class="status-badge-ft">FULL TIME</span>
                            </div>"""

results_new = """                    {% for m in completed_matches %}
                    <div class="fixture-card {% if last_match and m.id == last_match.id or forloop.first %}highlight-last-match-card{% endif %}" onclick="openMatchModal('{{ m.id }}')" title="Click to view scorecard">
                        <div>
                            <div class="fixture-card-header">
                                <span>{{ m.match_date|date:"D, d M"|upper }}</span>
                                {% if last_match and m.id == last_match.id or forloop.first %}
                                <span class="status-badge-latest">🏆 LATEST RESULT</span>
                                {% else %}
                                <span class="status-badge-ft">FULL TIME</span>
                                {% endif %}
                            </div>"""

assert results_old in text, "results_old not found in user_dashboard.html"
text = text.replace(results_old, results_new, 1)

with open(path_user, 'w', encoding='utf-8') as f:
    f.write(text)

print("[OK] front/user_dashboard.html updated with fixture and result highlighting.")

