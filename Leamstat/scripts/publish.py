"""Keep ONLY the latest complete NCSOFT snapshot at fixed paths in data/."""
import json
import zipfile
from pathlib import Path

SOURCE_FILES = {
    'Darkleam_ALL.json': 'latest.json',
    'Darkleam_STATS_SUMMARY.csv': 'stats.csv',
    'Darkleam_STATS_DETAILS.csv': 'stat_details.csv',
    'Darkleam_STATS_SUMMARY.html': 'stats.html',
    'Darkleam_REPORT.txt': 'report.txt',
    'Darkleam_DAEVANION_AND_GEAR.html': 'boards.html',
}

source_dir = Path('Darkleam_Exporter')
archives = sorted(source_dir.glob('Darkleam_FULL_*.zip'),
                  key=lambda f: f.stat().st_mtime, reverse=True)
if not archives:
    raise SystemExit('No new archive. Keep previous data/ files unchanged.')

with zipfile.ZipFile(archives[0]) as z:
    missing = set(SOURCE_FILES).difference(z.namelist())
    if missing:
        raise SystemExit('Incomplete ZIP; missing: ' + ', '.join(sorted(missing)))
    obj = json.loads(z.read('Darkleam_ALL.json'))
    if obj.get('errors'):
        raise SystemExit('API returned errors; previous snapshot preserved: ' + str(obj['errors']))
    profile = (obj.get('character_info') or {}).get('profile') or {}
    if profile.get('characterName') != 'Darkleam':
        raise SystemExit('Wrong character name; previous snapshot preserved.')
    if (obj.get('metadata') or {}).get('server_id') != 2317:
        raise SystemExit('Unexpected server; previous snapshot preserved.')
    worn = ((obj.get('equipment') or {}).get('equipment') or {}).get('equipmentList') or []
    details = obj.get('equipped_items') or []
    if not worn or len(details) != len(worn) or not all(x.get('data') for x in details):
        raise SystemExit('Not all equipped items available; previous snapshot preserved.')
    summaries = ((obj.get('character_info') or {}).get('daevanion') or {}).get('boardList') or []
    boards = obj.get('daevanion_boards') or []
    if not summaries or len(boards) != len(summaries) or not all((b.get('data') or {}).get('nodeList') for b in boards):
        raise SystemExit('Not all Daevanion boards available; previous snapshot preserved.')
    timestamp = (obj.get('metadata') or {}).get('captured_at')
    if not timestamp:
        raise SystemExit('Missing capture timestamp; previous snapshot preserved.')
    # Collect all output bytes before touching the previous snapshot.
    payload = {target: z.read(source) for source, target in SOURCE_FILES.items()}
    payload['last_update.txt'] = (str(timestamp) + '\n').encode('utf-8')

# Dedicated data/ folder: remove obsolete snapshot filenames, replace fixed names.
dest = Path('data')
dest.mkdir(exist_ok=True)
for existing in dest.iterdir():
    if existing.is_file() and existing.name not in payload and existing.name != '.gitkeep':
        existing.unlink()
for filename, content in payload.items():
    tmp = dest / (filename + '.tmp')
    tmp.write_bytes(content)
    tmp.replace(dest / filename)
print('Updated current Darkleam snapshot at', timestamp)
print('Current files:', ', '.join(sorted(payload)))
