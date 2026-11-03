const fs = require('fs');
const path = require('path');

const filePath = path.resolve('c:/Users/iqbal/OneDrive/Desktop/front/organizer_index.html');
let html = fs.readFileSync(filePath, 'utf8');

// Normalize line endings
html = html.replace(/\r\n/g, '\n');

// 1. Add CSS for League Logo
const logoCss = `
        /* LEAGUE LOGO STYLING */
        .league-brand-wrapper {
            display: flex;
            align-items: center;
            gap: 18px;
            min-width: 0;
        }

        .league-logo-box {
            position: relative;
            width: 76px;
            height: 76px;
            border-radius: 12px;
            background: rgba(16, 27, 22, 0.85);
            border: 2px solid rgba(180, 245, 107, 0.45);
            box-shadow: 0 6px 18px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.2);
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            overflow: hidden;
            transition: all 0.2s ease;
        }

        .league-logo-box:hover {
            border-color: var(--green);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(180, 245, 107, 0.3);
        }

        .league-logo-placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 2px;
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, rgba(36, 93, 60, 0.55), rgba(16, 27, 22, 0.95));
            border-radius: inherit;
        }

        .league-logo-icon {
            font-size: 28px;
            line-height: 1;
            filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.4));
        }

        .league-logo-code {
            font-family: var(--font-heading);
            font-size: 11px;
            font-weight: 900;
            letter-spacing: 0.8px;
            color: var(--green);
        }

        .league-logo-edit-hint {
            position: absolute;
            inset: 0;
            background: rgba(16, 27, 22, 0.85);
            color: var(--green);
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.18s ease;
            backdrop-filter: blur(2px);
            -webkit-backdrop-filter: blur(2px);
            border-radius: inherit;
            text-align: center;
            padding: 4px;
        }

        .league-logo-box:hover .league-logo-edit-hint {
            opacity: 1;
        }

        .league-tags-row {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .game-mode-pill {
            background: rgba(180, 245, 107, 0.15);
            color: var(--green);
            border: 1px solid rgba(180, 245, 107, 0.3);
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* SETTINGS LOGO UPLOADER BOX */
        .logo-uploader-card {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 14px;
            background: var(--soft-green);
            border: 1px solid #cad6c4;
            border-radius: 6px;
            margin-top: 6px;
        }

        .logo-preview-box {
            width: 70px;
            height: 70px;
            border-radius: 12px;
            background: var(--dark);
            border: 2px solid var(--green-dark);
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .emblem-pill {
            padding: 4px 9px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background: #ffffff;
            color: var(--dark);
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.15s;
        }

        .emblem-pill:hover {
            border-color: var(--green-dark);
            background: var(--soft-green);
        }

        .topbar-logo-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-right: 4px;
            font-size: 14px;
        }

        @media (max-width: 768px) {
            .league-brand-wrapper {
                flex-direction: row;
                align-items: flex-start;
                gap: 12px;
            }

            .league-logo-box {
                width: 60px;
                height: 60px;
                border-radius: 10px;
            }

            .league-logo-icon {
                font-size: 22px;
            }

            .logo-uploader-card {
                flex-direction: column;
                align-items: stretch;
                gap: 12px;
            }

            .logo-preview-box {
                margin: 0 auto;
            }
        }
    </style>`;

html = html.replace('    </style>', logoCss);
console.log("Injected logo CSS.");

// 2. Update Hero Banner to include the dedicated League Logo space
const oldLeagueBanner = `                <!-- LEAGUE SUMMARY -->
                <section class="league-banner">
                    <div class="league-info">
                        <span class="status">ONGOING SEASON</span>
                        <h2 id="leagueName">Greenfield Football League</h2>
                    </div>

                    <div class="league-actions">
                        <button class="btn"
                            onclick="openTab('settings', document.querySelector('[data-tab=settings]'))">⚙
                            Settings</button>
                        <button class="btn btn-primary"
                            onclick="alert('Connect this button to your fixture creation form.')">+ Create
                            Fixture</button>
                    </div>
                </section>`;

const newLeagueBanner = `                <!-- LEAGUE SUMMARY -->
                <section class="league-banner">
                    <div class="league-brand-wrapper">
                        <!-- SET LEAGUE LOGO SPACE -->
                        <div class="league-logo-box" id="bannerLogoBox" onclick="openTab('settings', document.querySelector('[data-tab=settings]'))" title="Click to upload / set league logo">
                            <img id="bannerLogoImg" src="" alt="League Logo" style="display:none;width:100%;height:100%;object-fit:cover;border-radius:inherit">
                            <div class="league-logo-placeholder" id="bannerLogoPlaceholder">
                                <span class="league-logo-icon" id="bannerLogoIcon">🛡️</span>
                                <span class="league-logo-code" id="bannerLogoCode">GFL</span>
                            </div>
                            <span class="league-logo-edit-hint">📷 Set Logo</span>
                        </div>

                        <div class="league-info">
                            <div class="league-tags-row">
                                <span class="status">ONGOING SEASON</span>
                                <span class="game-mode-pill" id="bannerGameMode">🏆 League + Knockout</span>
                            </div>
                            <h2 id="leagueName">Greenfield Football League</h2>
                            <div class="league-meta">
                                <span>◷ 2026 Season</span>
                                <span>♟ 8 Teams</span>
                                <span>⌖ Greenfield Stadium</span>
                            </div>
                        </div>
                    </div>

                    <div class="league-actions">
                        <button class="btn"
                            onclick="openTab('settings', document.querySelector('[data-tab=settings]'))">⚙ Settings</button>
                        <button class="btn btn-primary"
                            onclick="alert('Connect this button to your fixture creation form.')">+ Create Fixture</button>
                    </div>
                </section>`;

if (!html.includes(oldLeagueBanner)) {
    console.error("Could not find oldLeagueBanner!");
    process.exit(1);
}
html = html.replace(oldLeagueBanner, newLeagueBanner);
console.log("Updated Hero Banner with League Logo space.");

// 3. Update League Details Form to include the Logo Uploader card
const oldLeagueNameGroup = `                                <div class="form-group">
                                    <label class="muted">League Name</label>
                                    <input class="field" style="width:100%;margin-top:4px" id="editLeagueName"
                                        value="Greenfield Football League" required oninput="previewSettings()">
                                </div>`;

const newLeagueNameGroupWithLogo = `                                <!-- SET LEAGUE LOGO UPLOADER -->
                                <div class="form-group">
                                    <label class="muted">Official League Logo</label>
                                    <div class="logo-uploader-card">
                                        <!-- LOGO PREVIEW -->
                                        <div class="logo-preview-box" id="settingsLogoPreview">
                                            <img id="settingsLogoImg" src="" alt="League Logo" style="display:none;width:100%;height:100%;object-fit:cover;border-radius:inherit">
                                            <div class="league-logo-placeholder" id="settingsLogoPlaceholder">
                                                <span class="league-logo-icon" id="settingsLogoIcon">🛡️</span>
                                                <span class="league-logo-code" id="settingsLogoCode">GFL</span>
                                            </div>
                                        </div>

                                        <!-- CONTROLS -->
                                        <div style="flex:1;min-width:0">
                                            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                                                <input type="file" id="leagueLogoFileInput" accept="image/*" style="display:none" onchange="handleLogoFileSelect(event)">
                                                <button class="btn btn-primary" type="button" onclick="document.getElementById('leagueLogoFileInput').click()" style="padding:7px 14px;font-size:11px">📁 Upload Logo</button>
                                                <button class="btn" type="button" onclick="removeLeagueLogo()" style="padding:7px 12px;font-size:11px">✕ Reset Crest</button>
                                            </div>
                                            <div style="margin-top:8px">
                                                <input class="field" id="leagueLogoUrlInput" placeholder="Or enter logo image URL (https://...)" style="width:100%;font-size:11px;padding:6px 10px" oninput="handleLogoUrlInput(this.value)">
                                            </div>
                                            <div style="margin-top:8px;display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                                                <span style="font-size:10px;font-weight:700;color:var(--muted)">Presets:</span>
                                                <button type="button" class="emblem-pill" onclick="selectEmblemPreset('🛡️')">🛡️ Shield</button>
                                                <button type="button" class="emblem-pill" onclick="selectEmblemPreset('⚽')">⚽ Football</button>
                                                <button type="button" class="emblem-pill" onclick="selectEmblemPreset('🏆')">🏆 Trophy</button>
                                                <button type="button" class="emblem-pill" onclick="selectEmblemPreset('🦁')">🦁 Lion</button>
                                                <button type="button" class="emblem-pill" onclick="selectEmblemPreset('⭐')">⭐ Star</button>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div class="form-group">
                                    <label class="muted">League Name</label>
                                    <input class="field" style="width:100%;margin-top:4px" id="editLeagueName"
                                        value="Greenfield Football League" required oninput="previewSettings()">
                                </div>`;

if (!html.includes(oldLeagueNameGroup)) {
    console.error("Could not find oldLeagueNameGroup!");
    process.exit(1);
}
html = html.replace(oldLeagueNameGroup, newLeagueNameGroupWithLogo);
console.log("Updated Settings Form with Logo Uploader card.");

// 4. Update Topbar breadcrumb to include logo icon
const oldBreadcrumb = `                    <div class="breadcrumb">
                        <span class="breadcrumb-parent">My Leagues / </span>
                        <strong>Greenfield League</strong>
                    </div>`;

const newBreadcrumb = `                    <div class="breadcrumb">
                        <span class="breadcrumb-parent">My Leagues / </span>
                        <span class="topbar-logo-icon" id="topbarLogoIcon">🛡️</span>
                        <strong id="topbarLeagueName">Greenfield League</strong>
                    </div>`;

if (!html.includes(oldBreadcrumb)) {
    console.error("Could not find oldBreadcrumb!");
    process.exit(1);
}
html = html.replace(oldBreadcrumb, newBreadcrumb);
console.log("Updated Topbar breadcrumb with logo icon.");

// 5. Add JavaScript for Logo Upload & Management
const logoScript = `
        // --- LEAGUE LOGO MANAGEMENT ---
        let leagueLogoData = localStorage.getItem("touchline_league_logo") || "";
        let leagueEmblemPreset = localStorage.getItem("touchline_league_emblem") || "🛡️";

        function updateLogoDisplays() {
            const bannerImg = document.getElementById("bannerLogoImg");
            const bannerPlaceholder = document.getElementById("bannerLogoPlaceholder");
            const bannerIcon = document.getElementById("bannerLogoIcon");
            const bannerCode = document.getElementById("bannerLogoCode");

            const settingsImg = document.getElementById("settingsLogoImg");
            const settingsPlaceholder = document.getElementById("settingsLogoPlaceholder");
            const settingsIcon = document.getElementById("settingsLogoIcon");
            const settingsCode = document.getElementById("settingsLogoCode");

            const topbarIcon = document.getElementById("topbarLogoIcon");

            // Calculate 2-3 letter abbreviation from league name
            const leagueNameInput = document.getElementById("editLeagueName");
            const leagueName = (leagueNameInput && leagueNameInput.value) || "Greenfield Football League";
            const code = leagueName.split(/\\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 3).toUpperCase() || "GFL";

            if (bannerCode) bannerCode.textContent = code;
            if (settingsCode) settingsCode.textContent = code;

            if (leagueLogoData) {
                // Show uploaded / URL image
                if (bannerImg) {
                    bannerImg.src = leagueLogoData;
                    bannerImg.style.display = "block";
                }
                if (bannerPlaceholder) bannerPlaceholder.style.display = "none";

                if (settingsImg) {
                    settingsImg.src = leagueLogoData;
                    settingsImg.style.display = "block";
                }
                if (settingsPlaceholder) settingsPlaceholder.style.display = "none";

                if (topbarIcon) {
                    topbarIcon.innerHTML = '<img src="' + leagueLogoData + '" style="width:16px;height:16px;border-radius:3px;vertical-align:middle;object-fit:cover;">';
                }
            } else {
                // Show emblem icon and abbreviation
                if (bannerImg) bannerImg.style.display = "none";
                if (bannerPlaceholder) bannerPlaceholder.style.display = "flex";
                if (bannerIcon) bannerIcon.textContent = leagueEmblemPreset;

                if (settingsImg) settingsImg.style.display = "none";
                if (settingsPlaceholder) settingsPlaceholder.style.display = "flex";
                if (settingsIcon) settingsIcon.textContent = leagueEmblemPreset;

                if (topbarIcon) {
                    topbarIcon.textContent = leagueEmblemPreset;
                }
            }
        }

        function handleLogoFileSelect(e) {
            const file = e.target.files && e.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = function(evt) {
                leagueLogoData = evt.target.result;
                localStorage.setItem("touchline_league_logo", leagueLogoData);
                const urlInput = document.getElementById("leagueLogoUrlInput");
                if (urlInput) urlInput.value = "";
                updateLogoDisplays();
                showToast("✓ League logo updated successfully!");
            };
            reader.readAsDataURL(file);
        }

        function handleLogoUrlInput(url) {
            const cleanUrl = url.trim();
            if (!cleanUrl) return;

            const img = new Image();
            img.onload = function() {
                leagueLogoData = cleanUrl;
                localStorage.setItem("touchline_league_logo", cleanUrl);
                updateLogoDisplays();
                showToast("✓ League logo loaded from URL!");
            };
            img.onerror = function() {
                // not a valid image yet
            };
            img.src = cleanUrl;
        }

        function selectEmblemPreset(emblem) {
            leagueEmblemPreset = emblem;
            leagueLogoData = "";
            localStorage.removeItem("touchline_league_logo");
            localStorage.setItem("touchline_league_emblem", emblem);
            const urlInput = document.getElementById("leagueLogoUrlInput");
            if (urlInput) urlInput.value = "";
            updateLogoDisplays();
            showToast("✓ League emblem set to " + emblem);
        }

        function removeLeagueLogo() {
            leagueLogoData = "";
            leagueEmblemPreset = "🛡️";
            localStorage.removeItem("touchline_league_logo");
            localStorage.removeItem("touchline_league_emblem");
            const urlInput = document.getElementById("leagueLogoUrlInput");
            if (urlInput) urlInput.value = "";
            updateLogoDisplays();
            showToast("✓ Reset to default league crest.");
        }
`;

// Insert the new logic into <script>
const scriptEndIdx = html.lastIndexOf('</script>');
html = html.slice(0, scriptEndIdx) + '\n' + logoScript + '\n' + html.slice(scriptEndIdx);
console.log("Injected logo JavaScript functions.");

// Ensure updateLogoDisplays() is called inside DOMContentLoaded
const oldDomInit = `        // Initialize live settings preview on page load
        window.addEventListener("DOMContentLoaded", function() {
            if (typeof previewSettings === "function") {
                previewSettings();
            }
        });`;

const newDomInit = `        // Initialize live settings preview and logo on page load
        window.addEventListener("DOMContentLoaded", function() {
            if (typeof previewSettings === "function") {
                previewSettings();
            }
            if (typeof updateLogoDisplays === "function") {
                updateLogoDisplays();
            }
        });`;

if (html.includes(oldDomInit)) {
    html = html.replace(oldDomInit, newDomInit);
    console.log("Added updateLogoDisplays to DOMContentLoaded.");
}

fs.writeFileSync(filePath, html, 'utf8');
console.log("Successfully added space for League Logo in organizer_index.html!");

