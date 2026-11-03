with open('front/organizer_index.html', 'r', encoding='utf-8') as f:
    for idx, line in enumerate(f, 1):
        if 'id="teams"' in line:
            print(f"{idx}: {line.strip()}")

