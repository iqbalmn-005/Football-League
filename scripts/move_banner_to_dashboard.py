import os

path = 'front/organizer_index.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

banner_marker = '                <!-- LEAGUE HERO BANNER -->'
banner_end_marker = '                </section>'
tab_marker = '''                <!-- TAB 1: OVERVIEW -->
                <section class="tab-content {% if active_tab == 'overview' or not active_tab %}active{% endif %}"
                    id="overview">'''

banner_start_idx = content.find(banner_marker)
assert banner_start_idx != -1, "banner_marker not found"

tab_idx = content.find(tab_marker, banner_start_idx)
assert tab_idx != -1, "tab_marker not found"

# Find the </section> of league-banner, which occurs before tab_marker
banner_end_idx = content.rfind('                </section>', banner_start_idx, tab_idx) + len('                </section>')

banner_code = content[banner_start_idx:banner_end_idx].strip()

# Now construct new block:
# {% else %}
# <!-- TAB 1: OVERVIEW / DASHBOARD -->
# <section ... id="overview">
#     <!-- LEAGUE HERO BANNER (Visible only on Dashboard) -->
#     ...
#     <div class="kpi-grid">

old_block = content[banner_start_idx:tab_idx + len(tab_marker)]

new_block = f"""                <!-- TAB 1: OVERVIEW / DASHBOARD -->
                <section class="tab-content {{% if active_tab == 'overview' or not active_tab %}}active{{% endif %}}"
                    id="overview">

{content[banner_start_idx:banner_end_idx]}"""

assert old_block in content, "old_block not found in content"
new_content = content.replace(old_block, new_block, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("[OK] Successfully moved league-banner inside #overview tab.")

