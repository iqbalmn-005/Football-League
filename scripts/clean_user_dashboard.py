import os

path_user = 'front/user_dashboard.html'
with open(path_user, 'r', encoding='utf-8') as f:
    text = f.read().replace('\r\n', '\n')

# 1. Clean upcoming orphaned remnant
remnant_up = """                {% endif %}
                            </div>
                            <span class="match-vs-badge">VS</span>
                            <div class="league-crest" title="{{ next_match.away_team.name }}">
                                {% if next_match.away_team.get_logo_url %}
                                <img src="{{ next_match.away_team.get_logo_url }}" alt="{{ next_match.away_team.name }}">
                                {% else %}
                                <span class="league-crest-fallback" style="font-weight:900;color:var(--green);font-size:22px;">{{ next_match.away_team.short_name|default:next_match.away_team.name|slice:":3"|upper }}</span>
                                {% endif %}
                            </div>
                        </div>
                        <div class="league-info">
                            <span class="status-pill live" style="margin-bottom:4px;display:inline-block;">⚡ Next Match</span>
                            <h2>{{ next_match.home_team.name }} <span style="color:var(--green);font-weight:600;font-size:20px;">vs</span> {{ next_match.away_team.name }}</h2>
                            <div class="league-meta">
                                <span>◷ {{ next_match.match_date|date:"D, d M Y" }} · {{ next_match.kickoff_time|time:"H:i A" }}</span>
                                <span>📍 {{ next_match.venue|default:"Community Pitch" }}</span>
                                <span>🏆 {{ next_match.tournament_round }}</span>
                            </div>
                        </div>
                    </div>
                    <div class="banner-actions">
                        <button class="btn btn-primary" type="button" onclick="openMatchModal('{{ next_match.id }}')">
                            👁 Match Details
                        </button>
                    </div>
                </section>
                {% endif %}"""

assert remnant_up in text, "remnant_up not found"
text = text.replace(remnant_up, "                {% endif %}", 1)

# 2. Clean results orphaned remnant
remnant_res = """                {% endif %}
                            </div>
                            <div class="banner-score-display">
                                <span>{{ last_match.home_score }}</span>
                                <span style="opacity:0.6;font-size:16px;">:</span>
                                <span>{{ last_match.away_score }}</span>
                            </div>
                            <div class="league-crest" title="{{ last_match.away_team.name }}">
                                {% if last_match.away_team.get_logo_url %}
                                <img src="{{ last_match.away_team.get_logo_url }}" alt="{{ last_match.away_team.name }}">
                                {% else %}
                                <span class="league-crest-fallback" style="font-weight:900;color:var(--green);font-size:22px;">{{ last_match.away_team.short_name|default:last_match.away_team.name|slice:":3"|upper }}</span>
                                {% endif %}
                            </div>
                        </div>
                        <div class="league-info">
                            <span class="status-pill live" style="margin-bottom:4px;display:inline-block;">🏆 Last Match Result</span>
                            <h2>{{ last_match.home_team.name }} <span style="color:var(--green);font-weight:900;margin:0 4px;">{{ last_match.home_score }} - {{ last_match.away_score }}</span> {{ last_match.away_team.name }}</h2>
                            <div class="league-meta">
                                <span>◷ Full Time · {{ last_match.match_date|date:"D, d M Y" }}</span>
                                <span>📍 {{ last_match.venue|default:"Community Pitch" }}</span>
                                <span>🏆 {{ last_match.tournament_round }}</span>
                            </div>
                        </div>
                    </div>
                    <div class="banner-actions">
                        <button class="btn btn-primary" type="button" onclick="openMatchModal('{{ last_match.id }}')">
                            👁 Match Report
                        </button>
                    </div>
                </section>
                {% endif %}"""

assert remnant_res in text, "remnant_res not found"
text = text.replace(remnant_res, "                {% endif %}", 1)

with open(path_user, 'w', encoding='utf-8') as f:
    f.write(text)

print("[OK] user_dashboard.html cleaned up successfully.")

