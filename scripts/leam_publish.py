"""Publish latest complete character data under fixed filenames; no authentication."""
import json
import zipfile
from pathlib import Path

SOURCE = {
    'leam_all.json': 'leam.json',
    'leam_stats.csv': 'leam_stats.csv',
    'leam_stat_details.csv': 'leam_stat_details.csv',
    'leam_stats.html': 'leam_stats.html',
    'leam_report.txt': 'leam_report.txt',
    'leam_boards.html': 'leam_boards.html',
}
source_dir = Path('leam')
archives = sorted(source_dir.glob('leam_full_*.zip'), key=lambda f:f.stat().st_mtime, reverse=True)
if not archives:
    raise SystemExit('No new leam archive; existing data will stay unchanged.')
with zipfile.ZipFile(archives[0]) as z:
    missing=set(SOURCE)-set(z.namelist())
    if missing: raise SystemExit('Incomplete archive: '+repr(sorted(missing)))
    obj=json.loads(z.read('leam_all.json'))
    if obj.get('errors'): raise SystemExit('NCSOFT API errors: '+repr(obj['errors']))
    profile=(obj.get('character_info') or {}).get('profile') or {}
    if profile.get('characterName') != 'Darkleam':
        raise SystemExit('Expected Darkleam character, received '+repr(profile.get('characterName')))
    if int((obj.get('metadata') or {}).get('server_id') or 0) != 2317:
        raise SystemExit('Unexpected server id')
    equipped=((obj.get('equipment') or {}).get('equipment') or {}).get('equipmentList') or []
    details=obj.get('equipped_items') or []
    if not equipped or len(equipped)!=len(details) or any(not v.get('data') for v in details):
        raise SystemExit('Incomplete equipment details')
    board_summary=((obj.get('character_info') or {}).get('daevanion') or {}).get('boardList') or []
    boards=obj.get('daevanion_boards') or []
    if not board_summary or len(board_summary)!=len(boards) or any(not (b.get('data') or {}).get('nodeList') for b in boards):
        raise SystemExit('Incomplete Daevanion nodes')
    capture=(obj.get('metadata') or {}).get('captured_at')
    if not capture:raise SystemExit('Missing capture timestamp')
    payload={dst:z.read(source) for source,dst in SOURCE.items()}
    payload['leam_updated.txt']=(str(capture)+'\n').encode('utf-8')

dest=Path('data');dest.mkdir(exist_ok=True)
# Stage writes first; do not touch the previous snapshot if validation failed.
for filename,content in payload.items():
    (dest/(filename+'.tmp')).write_bytes(content)
for filename in payload:
    (dest/(filename+'.tmp')).replace(dest/filename)
for old in dest.iterdir():
    if old.is_file() and old.name not in payload:
        old.unlink()
print('leam snapshot published:', capture)
