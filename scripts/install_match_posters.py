import os

# 1. Update front/organizer_index.html
path_org = 'front/organizer_index.html'
with open(path_org, 'r', encoding='utf-8') as f:
    text_org = f.read().replace('\r\n', '\n')

poster_css = """
        /* MATCH FIXTURE POSTER (MATCHING USER REFERENCE DESIGN) */
        .match-fixture-poster {
            position: relative;
            background: radial-gradient(ellipse at 50% 15%, rgba(220, 38, 38, 0.14), transparent 70%),
                        linear-gradient(135deg, #0d1210 0%, #161c18 50%, #0d1210 100%);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 12px;
            padding: 24px 28px 22px;
            margin-bottom: 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            color: #ffffff;
            box-shadow: 0 16px 36px rgba(0, 0, 0, 0.45);
            overflow: hidden;
        }

        .poster-top-header {
            margin-bottom: 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .poster-title {
            font-family: var(--font-heading, "Barlow Condensed", sans-serif);
            font-size: 16px;
            font-weight: 900;
            letter-spacing: 2.5px;
            color: #ffffff;
            text-transform: uppercase;
        }

        .poster-title-line {
            width: 38px;
            height: 2px;
            background: #dc2626;
            margin-top: 4px;
            border-radius: 2px;
        }

        .poster-matchup {
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 18px;
            margin-bottom: 18px;
        }

        .poster-team {
            display: flex;
            align-items: center;
            gap: 14px;
            flex: 1;
        }

        .poster-team-home {
            justify-content: flex-end;
            text-align: right;
        }

        .poster-team-away {
            justify-content: flex-start;
            text-align: left;
        }

        .poster-crest-wrap {
            width: 78px;
            height: 78px;
            min-width: 78px;
            min-height: 78px;
            border-radius: 50%;
            background: #1c221e;
            border: 2px solid rgba(255, 255, 255, 0.25);
            box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            flex-shrink: 0;
            padding: 4px;
        }

        .poster-crest-wrap img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }

        .poster-crest-fallback {
            font-family: var(--font-heading, "Barlow Condensed", sans-serif);
            font-size: 26px;
            font-weight: 900;
            color: #ffffff;
            letter-spacing: 0.5px;
        }

        .poster-team-name {
            font-family: var(--font-heading, "Barlow Condensed", sans-serif);
            font-size: 20px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: 0.8px;
            text-transform: uppercase;
            line-height: 1.15;
            max-width: 220px;
        }

        .poster-vs-wrap {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0 12px;
            flex-shrink: 0;
        }

        .poster-vs-text {
            font-family: var(--font-heading, "Barlow Condensed", sans-serif);
            font-size: 42px;
            font-weight: 900;
            color: #ffffff;
            letter-spacing: 1.5px;
            line-height: 1;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
        }

        .poster-score-text {
            font-family: var(--font-heading, "Barlow Condensed", sans-serif);
            font-size: 44px;
            font-weight: 900;
            color: #ffffff;
            letter-spacing: 2px;
            line-height: 1;
            text-shadow: 0 2px 12px rgba(0, 0, 0, 0.5);
            white-space: nowrap;
        }

        .poster-info-pill {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            background: rgba(0, 0, 0, 0.55);
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 30px;
            padding: 7px 22px;
            font-size: 12px;
            font-weight: 700;
            color: rgba(255, 255, 255, 0.92);
            letter-spacing: 0.6px;
            text-transform: uppercase;
            margin-bottom: 16px;
            backdrop-filter: blur(4px);
        }

        .poster-pill-divider {
            color: rgba(255, 255, 255, 0.4);
            font-weight: 400;
        }

        .poster-actions {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            flex-wrap: wrap;
        }

        .poster-btn {
            font-family: var(--font-heading, "Barlow Condensed", sans-serif);
            font-size: 14px;
            font-weight: 900;
            letter-spacing: 1px;
            text-transform: uppercase;
            padding: 10px 26px;
            border-radius: 28px;
            border: none;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .poster-btn-primary {
            background: #dc2626;
            color: #ffffff;
            box-shadow: 0 4px 16px rgba(220, 38, 38, 0.45);
        }

        .poster-btn-primary:hover {
            background: #b91c1c;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(220, 38, 38, 0.6);
        }

        .poster-btn-secondary {
            background: rgba(255, 255, 255, 0.12);
            color: #ffffff;
            border: 1.5px solid rgba(255, 255, 255, 0.3);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        }

        .poster-btn-secondary:hover {
            background: rgba(255, 255, 255, 0.22);
            border-color: rgba(255, 255, 255, 0.5);
            transform: translateY(-2px);
        }

        /* Non-green row highlights */
        .highlight-next-match-row {
            background: rgba(220, 38, 38, 0.05) !important;
            border-left: 4px solid #dc2626 !important;
        }

        .highlight-next-match-row:hover {
            background: rgba(220, 38, 38, 0.1) !important;
        }

        .highlight-last-match-row {
            background: rgba(2, 132, 199, 0.06) !important;
            border-left: 4px solid #0284c7 !important;
        }

        .highlight-last-match-row:hover {
            background: rgba(2, 132, 199, 0.12) !important;
        }

        .badge-next-match {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #dc2626;
            color: #ffffff;
            font-size: 10px;
            font-weight: 900;
            padding: 2px 7px;
            border-radius: 4px;
            letter-spacing: 0.4px;
            white-space: nowrap;
        }

        .badge-last-match {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #0284c7;
            color: #ffffff;
            font-size: 10px;
            font-weight: 900;
            padding: 2px 7px;
            border-radius: 4px;
            letter-spacing: 0.4px;
            white-space: nowrap;
        }

        @media (max-width: 768px) {
            .match-fixture-poster {
                padding: 20px 16px;
            }

            .poster-matchup {
                flex-direction: column;
                gap: 12px;
            }

            .poster-team {
                width: 100%;
                justify-content: center !important;
                text-align: center !important;
            }

            .poster-team-home {
                flex-direction: column;
            }

            .poster-team-away {
                flex-direction: column-reverse;
            }

            .poster-team-name {
                max-width: 100%;
                font-size: 18px;
            }

            .poster-crest-wrap {
                width: 64px;
                height: 64px;
                min-width: 64px;
                min-height: 64px;
            }

            .poster-vs-text {
                font-size: 32px;
            }

            .poster-score-text {
                font-size: 36px;
            }

            .poster-info-pill {
                flex-direction: column;
                gap: 4px;
                border-radius: 12px;
                padding: 8px 14px;
                font-size: 11px;
            }

            .poster-pill-divider {
                display: none;
            }

            .poster-actions {
                width: 100%;
            }

            .poster-btn {
                width: 100%;
                justify-content: center;
            }
        }
"""

style_tag = "</style>"
idx = text_org.find(style_tag)
assert idx != -1
text_org = text_org[:idx] + poster_css + text_org[idx:]

# Replace next_match banner in Tab 2
old_next_block_start = text_org.find('{% if next_match %}\n                    <!-- NEXT MATCH HERO BANNER')
old_next_block_end = text_org.find('{% endif %}', old_next_block_start) + len('{% endif %}')
assert old_next_block_start != -1

new_next_poster = """{% if next_match %}
                    <!-- NEXT MATCH FIXTURE POSTER (LIKE USER REFERENCE IMAGE) -->
                    <section class="match-fixture-poster next-match-hero-poster">
                        <div class="poster-top-header">
                            <span class="poster-title">NEXT MATCH</span>
                            <div class="poster-title-line"></div>
                        </div>

                        <div class="poster-matchup">
                            <div class="poster-team poster-team-home">
                                <div class="poster-crest-wrap" title="{{ next_match.home_team.name }}">
                                    {% if next_match.home_team.get_logo_url %}
                                    <img src="{{ next_match.home_team.get_logo_url }}" alt="{{ next_match.home_team.name }}">
                                    {% else %}
                                    <span class="poster-crest-fallback">{{ next_match.home_team.short_name|default:next_match.home_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                                <div class="poster-team-name">{{ next_match.home_team.name }}</div>
                            </div>

                            <div class="poster-vs-wrap">
                                <span class="poster-vs-text">VS</span>
                            </div>

                            <div class="poster-team poster-team-away">
                                <div class="poster-team-name">{{ next_match.away_team.name }}</div>
                                <div class="poster-crest-wrap" title="{{ next_match.away_team.name }}">
                                    {% if next_match.away_team.get_logo_url %}
                                    <img src="{{ next_match.away_team.get_logo_url }}" alt="{{ next_match.away_team.name }}">
                                    {% else %}
                                    <span class="poster-crest-fallback">{{ next_match.away_team.short_name|default:next_match.away_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                            </div>
                        </div>

                        <div class="poster-info-pill">
                            <span>📅 {{ next_match.match_date|date:"M d, h:i A"|upper }}</span>
                            <span class="poster-pill-divider">|</span>
                            <span>📍 {{ next_match.venue|default:"Payyanad Stadium"|upper }}</span>
                        </div>

                        <div class="poster-actions">
                            <button class="poster-btn poster-btn-primary" type="button"
                                onclick="openRecordResultModal('{{ next_match.id }}', '{{ next_match.home_team.name|escapejs }}', '{{ next_match.away_team.name|escapejs }}', '{{ next_match.tournament_round }}')">
                                ⚡ ENTER SCORE
                            </button>
                            <button class="poster-btn poster-btn-secondary" type="button"
                                onclick="openRescheduleModal('{{ next_match.id }}', '{{ next_match.home_team.name|escapejs }} vs {{ next_match.away_team.name|escapejs }}', '{{ next_match.match_date.isoformat }}', '{{ next_match.kickoff_time.isoformat }}', '{{ next_match.venue|escapejs }}', '{{ next_match.status }}', '{{ next_match.tournament_round|escapejs }}')">
                                📅 RESCHEDULE
                            </button>
                        </div>
                    </section>
                    {% endif %}"""

text_org = text_org[:old_next_block_start] + new_next_poster + text_org[old_next_block_end:]

# Replace last_match banner in Tab 3
old_last_block_start = text_org.find('{% if last_match %}\n                    <!-- LAST MATCH HERO BANNER')
old_last_block_end = text_org.find('{% endif %}', old_last_block_start) + len('{% endif %}')
assert old_last_block_start != -1

new_last_poster = """{% if last_match %}
                    <!-- LAST MATCH FIXTURE POSTER (LIKE USER REFERENCE IMAGE) -->
                    <section class="match-fixture-poster last-match-hero-poster">
                        <div class="poster-top-header">
                            <span class="poster-title">LAST MATCH RESULT</span>
                            <div class="poster-title-line" style="background:#0284c7;"></div>
                        </div>

                        <div class="poster-matchup">
                            <div class="poster-team poster-team-home">
                                <div class="poster-crest-wrap" title="{{ last_match.home_team.name }}">
                                    {% if last_match.home_team.get_logo_url %}
                                    <img src="{{ last_match.home_team.get_logo_url }}" alt="{{ last_match.home_team.name }}">
                                    {% else %}
                                    <span class="poster-crest-fallback">{{ last_match.home_team.short_name|default:last_match.home_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                                <div class="poster-team-name">{{ last_match.home_team.name }}</div>
                            </div>

                            <div class="poster-vs-wrap">
                                <span class="poster-score-text">{{ last_match.home_score }} - {{ last_match.away_score }}</span>
                            </div>

                            <div class="poster-team poster-team-away">
                                <div class="poster-team-name">{{ last_match.away_team.name }}</div>
                                <div class="poster-crest-wrap" title="{{ last_match.away_team.name }}">
                                    {% if last_match.away_team.get_logo_url %}
                                    <img src="{{ last_match.away_team.get_logo_url }}" alt="{{ last_match.away_team.name }}">
                                    {% else %}
                                    <span class="poster-crest-fallback">{{ last_match.away_team.short_name|default:last_match.away_team.name|slice:":3"|upper }}</span>
                                    {% endif %}
                                </div>
                            </div>
                        </div>

                        <div class="poster-info-pill">
                            <span>📅 FULL TIME · {{ last_match.match_date|date:"M d, Y"|upper }}</span>
                            <span class="poster-pill-divider">|</span>
                            <span>📍 {{ last_match.venue|default:"Payyanad Stadium"|upper }}</span>
                        </div>

                        <div class="poster-actions">
                            <button class="poster-btn poster-btn-primary" type="button" style="background:#0284c7;box-shadow:0 4px 16px rgba(2,132,199,0.45);"
                                onclick="openRecordResultModal('{{ last_match.id }}', '{{ last_match.home_team.name|escapejs }}', '{{ last_match.away_team.name|escapejs }}', '{{ last_match.tournament_round }}', '{{ last_match.home_score|default_if_none:0 }}', '{{ last_match.away_score|default_if_none:0 }}')">
                                ✎ EDIT SCORE &amp; EVENTS
                            </button>
                        </div>
                    </section>
                    {% endif %}"""

text_org = text_org[:old_last_block_start] + new_last_poster + text_org[old_last_block_end:]

with open(path_org, 'w', encoding='utf-8') as f:
    f.write(text_org)

print("[OK] front/organizer_index.html updated with poster design!")

# 2. Update front/user_dashboard.html
path_user = 'front/user_dashboard.html'
with open(path_user, 'r', encoding='utf-8') as f:
    text_user = f.read().replace('\r\n', '\n')

idx_u = text_user.find(style_tag)
assert idx_u != -1
text_user = text_user[:idx_u] + poster_css + text_user[idx_u:]

# Replace next_match banner in user_dashboard
old_u_next_start = text_user.find('{% if next_match %}\n                <!-- FEATURED NEXT MATCH HERO BANNER -->')
old_u_next_end = text_user.find('{% endif %}', old_u_next_start) + len('{% endif %}')
assert old_u_next_start != -1

new_u_next_poster = """{% if next_match %}
                <!-- FEATURED NEXT MATCH POSTER -->
                <section class="match-fixture-poster next-match-hero-poster">
                    <div class="poster-top-header">
                        <span class="poster-title">NEXT MATCH</span>
                        <div class="poster-title-line"></div>
                    </div>

                    <div class="poster-matchup">
                        <div class="poster-team poster-team-home">
                            <div class="poster-crest-wrap" title="{{ next_match.home_team.name }}">
                                {% if next_match.home_team.get_logo_url %}
                                <img src="{{ next_match.home_team.get_logo_url }}" alt="{{ next_match.home_team.name }}">
                                {% else %}
                                <span class="poster-crest-fallback">{{ next_match.home_team.short_name|default:next_match.home_team.name|slice:":3"|upper }}</span>
                                {% endif %}
                            </div>
                            <div class="poster-team-name">{{ next_match.home_team.name }}</div>
                        </div>

                        <div class="poster-vs-wrap">
                            <span class="poster-vs-text">VS</span>
                        </div>

                        <div class="poster-team poster-team-away">
                            <div class="poster-team-name">{{ next_match.away_team.name }}</div>
                            <div class="poster-crest-wrap" title="{{ next_match.away_team.name }}">
                                {% if next_match.away_team.get_logo_url %}
                                <img src="{{ next_match.away_team.get_logo_url }}" alt="{{ next_match.away_team.name }}">
                                {% else %}
                                <span class="poster-crest-fallback">{{ next_match.away_team.short_name|default:next_match.away_team.name|slice:":3"|upper }}</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>

                    <div class="poster-info-pill">
                        <span>📅 {{ next_match.match_date|date:"M d, h:i A"|upper }}</span>
                        <span class="poster-pill-divider">|</span>
                        <span>📍 {{ next_match.venue|default:"Payyanad Stadium"|upper }}</span>
                    </div>

                    <div class="poster-actions">
                        <button class="poster-btn poster-btn-primary" type="button" onclick="openMatchModal('{{ next_match.id }}')">
                            👁 MATCH DETAILS
                        </button>
                    </div>
                </section>
                {% endif %}"""

text_user = text_user[:old_u_next_start] + new_u_next_poster + text_user[old_u_next_end:]

# Replace last_match banner in user_dashboard
old_u_last_start = text_user.find('{% if last_match %}\n                <!-- FEATURED LAST MATCH RESULT HERO BANNER -->')
old_u_last_end = text_user.find('{% endif %}', old_u_last_start) + len('{% endif %}')
assert old_u_last_start != -1

new_u_last_poster = """{% if last_match %}
                <!-- FEATURED LAST MATCH RESULT POSTER -->
                <section class="match-fixture-poster last-match-hero-poster">
                    <div class="poster-top-header">
                        <span class="poster-title">LAST MATCH RESULT</span>
                        <div class="poster-title-line" style="background:#0284c7;"></div>
                    </div>

                    <div class="poster-matchup">
                        <div class="poster-team poster-team-home">
                            <div class="poster-crest-wrap" title="{{ last_match.home_team.name }}">
                                {% if last_match.home_team.get_logo_url %}
                                <img src="{{ last_match.home_team.get_logo_url }}" alt="{{ last_match.home_team.name }}">
                                {% else %}
                                <span class="poster-crest-fallback">{{ last_match.home_team.short_name|default:last_match.home_team.name|slice:":3"|upper }}</span>
                                {% endif %}
                            </div>
                            <div class="poster-team-name">{{ last_match.home_team.name }}</div>
                        </div>

                        <div class="poster-vs-wrap">
                            <span class="poster-score-text">{{ last_match.home_score }} - {{ last_match.away_score }}</span>
                        </div>

                        <div class="poster-team poster-team-away">
                            <div class="poster-team-name">{{ last_match.away_team.name }}</div>
                            <div class="poster-crest-wrap" title="{{ last_match.away_team.name }}">
                                {% if last_match.away_team.get_logo_url %}
                                <img src="{{ last_match.away_team.get_logo_url }}" alt="{{ last_match.away_team.name }}">
                                {% else %}
                                <span class="poster-crest-fallback">{{ last_match.away_team.short_name|default:last_match.away_team.name|slice:":3"|upper }}</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>

                    <div class="poster-info-pill">
                        <span>📅 FULL TIME · {{ last_match.match_date|date:"M d, Y"|upper }}</span>
                        <span class="poster-pill-divider">|</span>
                        <span>📍 {{ last_match.venue|default:"Payyanad Stadium"|upper }}</span>
                    </div>

                    <div class="poster-actions">
                        <button class="poster-btn poster-btn-primary" type="button" style="background:#0284c7;box-shadow:0 4px 16px rgba(2,132,199,0.45);" onclick="openMatchModal('{{ last_match.id }}')">
                            👁 MATCH REPORT
                        </button>
                    </div>
                </section>
                {% endif %}"""

text_user = text_user[:old_u_last_start] + new_u_last_poster + text_user[old_u_last_end:]

with open(path_user, 'w', encoding='utf-8') as f:
    f.write(text_user)

print("[OK] front/user_dashboard.html updated with poster design!")

