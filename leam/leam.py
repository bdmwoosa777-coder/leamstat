# -*- coding: utf-8 -*-
"""AION 2 Darkleam public-armory snapshot. Stdlib only, no account login.
Protocol derived from the user's locally supplied aion2-api-0.5.0 (MIT).
"""
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from leam_stats import produce, true_stats_template
from leam_compare import latest_previous, compare

CHAR_NAME = 'Darkleam'
REGION = 'eu'
SERVER_ID = 2317
# Public character ID from user-supplied Atelier Gaming link, NOT a login token.
CHAR_ID = 'm2VmGXXoU9zwz1BXREKGH-kS2un85fANT3LjIehi5yo='
API_SITE = 'https://aion2.plaync.com/api/character/'
API_SEARCH = 'https://api-search.plaync.com/aion2global/search/v2/character'
HEADERS = {
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
}

class APIError(Exception):
    pass

class PublicAPI:
    def __init__(self):
        self.last = 0.0
        self.counter = 0
    def get(self, url, params):
        query = urllib.parse.urlencode(params)
        address = url + ('?' + query if query else '')
        for attempt in range(3):
            delta = time.monotonic() - self.last
            if delta < .30:
                time.sleep(.30 - delta)
            self.last = time.monotonic()
            self.counter += 1
            try:
                req = urllib.request.Request(address, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=18) as r:
                    data = r.read(15 * 1024 * 1024)
                    content_type = r.headers.get('Content-Type', '')
                try:
                    value = json.loads(data.decode('utf-8-sig'))
                except (ValueError, UnicodeError):
                    raise APIError('Сервер вернул не JSON (возможно, редирект/блокировка): ' +
                                   content_type + ' / ' + data[:160].decode('utf-8', 'replace'))
                return value
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.5 * (attempt+1)); continue
                raise APIError('HTTP %s, %s' % (e.code, urllib.parse.urlsplit(url).netloc)) from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    time.sleep(1.5 * (attempt+1)); continue
                raise APIError('Не удалось подключиться к %s: %s' %
                               (urllib.parse.urlsplit(url).netloc, str(e))) from e
        raise APIError('Лимит повторных запросов')

    def character(self, route, character_id, server_id, **extra):
        args = {'region': REGION, 'lang': 'en-US', 'serverId': server_id,
                'characterId': character_id}
        args.update(extra)
        return self.get(API_SITE + route, args)

    def search(self):
        return self.get(API_SEARCH, {'keyword': CHAR_NAME, 'region': REGION,
                                    'localeInfo': 'en-US', 'serverId': SERVER_ID,
                                    'page': 1, 'size': 50})

def as_open(value):
    return value is True or value == 1 or value == '1'

def timestamp():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')

def stat_lines(entries):
    out = []
    for s in (entries or []):
        if isinstance(s, dict):
            v = str(s.get('value', '')).strip()
            if s.get('minValue'):
                v = str(s['minValue']) + '–' + v
            if s.get('extra') and str(s['extra']) not in ('0',''):
                v += ' (+' + str(s['extra']).lstrip('+') + ' усиление)'
            out.append((str(s.get('name') or s.get('id') or '?') + ': ' + v).strip())
    return out

def desc_lines(records):
    return [str(x.get('desc', '')) if isinstance(x,dict) else str(x) for x in (records or [])]

def report_text(archive):
    meta = archive['metadata']
    info = archive.get('character_info') or {}
    eq = archive.get('equipment') or {}
    profile = info.get('profile') or {}
    lines = [
        'AION 2 — DARKLEAM / QUAI — ПОЛНЫЙ СНИМОК ПЕРСОНАЖА',
        'Время запроса: ' + meta['captured_at'],
        'Источник: публичный API персонажей NCSOFT (не скриншоты, не игровая память)',
        'Проверка имени: ' + str(profile.get('characterName', 'нет данных')),
        'Уровень: ' + str(profile.get('characterLevel', '?')),
        'Боевая мощь: ' + str(profile.get('combatPower', '?')),
        'Сервер: ' + str(profile.get('serverName', 'Quai')),
        'ID сервера: ' + str(meta['server_id']), '',
        '=== ХАРАКТЕРИСТИКИ ПЕРСОНАЖА ===',
    ]
    for s in (info.get('stat') or {}).get('statList') or []:
        lines.append('%s: %s%s' % (s.get('name', s.get('type','?')), s.get('value','?'),
                                    ' | ' + ', '.join(s['statSecondList']) if s.get('statSecondList') else ''))
    lines += ['', '=== ВЕЩИ: ПОЛНЫЕ СЛУЧАЙНЫЕ ХАРАКТЕРИСТИКИ И КАМНИ ===']
    worn = (eq.get('equipment') or {}).get('equipmentList') or []
    items = archive.get('equipped_items') or []
    by_slot = {v['slot_pos']: v for v in items}
    for slot in worn:
        pos = slot.get('slotPos')
        lines.append('')
        lines.append('[' + str(slot.get('slotPosName',pos)) + '] ' + str(slot.get('name','?')) +
                     ' +' + str(slot.get('enchantLevel',0)) +
                     ' (Прорыв ' + str(slot.get('exceedLevel', 0)) + ')')
        detail = by_slot.get(pos,{}).get('data') or {}
        if not detail:
            lines.append('  ПОЛНЫЕ СТАТЫ НЕ ПОЛУЧЕНЫ: ' + by_slot.get(pos,{}).get('error','нет ответа'))
            continue
        lines.append('  Привязка души: ' + str(detail.get('soulBindRate','?')) + '%')
        for key, label in [('mainStats','Основные'), ('subStats','Случайные')]:
            lines.append('  ' + label + ':')
            lines.extend('    ' + x for x in stat_lines(detail.get(key)))
        lines.append('  Манастоуны:')
        for stone in detail.get('magicStoneStat') or []:
            lines.append('    ' + str(stone.get('name', '?')) + ' ' + str(stone.get('value','')))
        lines.append('  Теостоны:')
        for stone in detail.get('godStoneStat') or []:
            lines.append('    ' + str(stone.get('name','?')) + ': ' + str(stone.get('desc','')))
        for skill in detail.get('subSkills') or []:
            lines.append('  Дополнительный навык: ' + str(skill.get('name','')) + ' ' + str(skill.get('level','')))
    lines += ['', '=== НАВЫКИ И СТИГМЫ ===']
    for skill in (eq.get('skill') or {}).get('skillList') or []:
        lines.append('%s | %s | ур. %s | установлен: %s' % (
            skill.get('category',''), skill.get('name',''), skill.get('skillLevel',''),
            'да' if as_open(skill.get('equip')) else 'нет'))
    lines += ['', '=== ДАЭВАНИОН: ВСЕ УЗЛЫ ===']
    summary = (info.get('daevanion') or {}).get('boardList') or []
    boards = archive.get('daevanion_boards') or []
    for row in summary:
        bid = row.get('id'); board = next((x for x in boards if x['board_id']==bid), None)
        lines += ['', '[%s] %s/%s (ID=%s)' % (row.get('name','?'), row.get('openNodeCount','?'),
                                             row.get('totalNodeCount','?'),bid)]
        if not board or not board.get('data'):
            lines.append('  Таблица недоступна: ' + str(board.get('error','нет ответа') if board else 'нет ответа'))
            continue
        d = board['data']; nodes = d.get('nodeList') or []
        for n in sorted(nodes, key=lambda n:(n.get('row',0),n.get('col',0))):
            state = 'ОТКРЫТ' if as_open(n.get('open')) else 'закрыт'
            effects = ', '.join(desc_lines(n.get('effectList')))
            lines.append('  [%s] R%s/C%s %s (%s) %s' % (state,n.get('row','?'),n.get('col','?'),
                          n.get('name',''),n.get('type',''),effects))
        lines.append('  Все открытые бонусы характеристик: ' + ' | '.join(desc_lines(d.get('openStatEffectList'))))
        lines.append('  Все открытые бонусы навыков: ' + ' | '.join(desc_lines(d.get('openSkillEffectList'))))
    errors = archive.get('errors') or []
    lines += ['', '=== ОШИБКИ API / НЕПОЛНЫЕ ДАННЫЕ ===']
    lines += errors if errors else ['Ошибок нет.']
    return '\n'.join(lines) + '\n'

def h(s): return html.escape(str(s), quote=True)

def report_html(archive):
    info=archive.get('character_info') or {}; eq=archive.get('equipment') or {}
    profile=info.get('profile') or {}
    css='''body{font:15px system-ui,Arial;background:#101319;color:#e1e9f2;max-width:1200px;margin:auto;padding:24px}
    h1,h2{color:#b7e3ff}section{margin:24px 0;background:#171e29;border:1px solid #364054;border-radius:10px;padding:20px}
    table{border-collapse:collapse;width:100%}td,th{padding:6px;border-bottom:1px solid #323c4b;text-align:left}
    .board{border-collapse:separate;border-spacing:3px;width:auto;margin:12px auto}.board td{width:42px;height:42px;
    min-width:42px;text-align:center;padding:0;border:1px solid #3d4550;border-radius:5px;background:#0d1119;color:#97a0aa;cursor:help}
    .board .open{background:#436957;border-color:#54c485;color:white}.board .locked{background:#10141c}
    .board .start{background:#347c9c}.board .missing{border:0;background:transparent}
    details{margin:10px 0;padding:10px;border:1px solid #3b4d5f;border-radius:7px}
    summary{cursor:pointer;font-weight:bold;color:#bfe4fb}small{color:#a4b4c4}pre{white-space:pre-wrap;overflow-wrap:anywhere}
    '''
    out=['<!DOCTYPE html><html lang="ru"><meta charset="utf-8"><title>AION2 Darkleam snapshot</title>',
         '<style>'+css+'</style><h1>AION 2 — Darkleam / Quai</h1>',
         '<p>Источник: публичный API NCSOFT. Выгружено: '+h(archive['metadata']['captured_at'])+'</p>',
         '<section><h2>Персонаж</h2><p>Уровень '+h(profile.get('characterLevel','?'))+
         ' · Боевая мощь '+h(profile.get('combatPower','?'))+'</p><table>']
    for s in (info.get('stat') or {}).get('statList') or []:
        out.append('<tr><td>'+h(s.get('name','?'))+'</td><td>'+h(s.get('value',''))+'</td><td>'+h('; '.join(s.get('statSecondList') or []))+'</td></tr>')
    out.append('</table></section><section><h2>Экипировка — индивидуальные характеристики</h2>')
    all_items={x['slot_pos']:x for x in (archive.get('equipped_items') or [])}
    for slot in (eq.get('equipment') or {}).get('equipmentList') or []:
        pos=slot.get('slotPos'); item=all_items.get(pos,{}).get('data') or {}
        out.append('<details><summary>'+h(slot.get('slotPosName',''))+' · '+h(slot.get('name',''))+
                   ' +'+h(slot.get('enchantLevel',0))+'</summary>')
        if not item:
            out.append('<p>Нет ответа API: '+h(all_items.get(pos,{}).get('error','unknown'))+'</p></details>');continue
        out.append('<p>Привязка души: '+h(item.get('soulBindRate','?'))+'%</p>')
        for key,title in [('mainStats','Основные статы'),('subStats','Случайные статы')]:
            out.append('<h3>'+title+'</h3><p>'+'<br>'.join(map(h,stat_lines(item.get(key))))+'</p>')
        out.append('<h3>Манастоуны</h3><p>' + '<br>'.join((h(x.get('name',''))+' '+h(x.get('value',''))) for x in (item.get('magicStoneStat') or [])) + '</p>')
        out.append('<h3>Теостоны</h3><p>' + '<br>'.join((h(x.get('name',''))+' — '+h(x.get('desc',''))) for x in (item.get('godStoneStat') or [])) + '</p></details>')
    out.append('</section><section><h2>Навыки / стигмы</h2><table>')
    for skill in (eq.get('skill') or {}).get('skillList') or []:
        out.append('<tr><td>'+h(skill.get('category',''))+'</td><td>'+h(skill.get('name',''))+
                   '</td><td>'+h(skill.get('skillLevel',''))+'</td><td>'+('✓' if as_open(skill.get('equip')) else '')+'</td></tr>')
    out.append('</table></section><section><h2>Даэванион — точная карта открытых узлов</h2>')
    all_boards={x['board_id']:x for x in archive.get('daevanion_boards') or []}
    for b in (info.get('daevanion') or {}).get('boardList') or []:
        bid=b.get('id'); item=all_boards.get(bid,{}); board=item.get('data') or {}
        out.append('<details open><summary>'+h(b.get('name','?'))+' — '+h(b.get('openNodeCount','?'))+
                   '/'+h(b.get('totalNodeCount','?'))+'</summary>')
        nodes=board.get('nodeList') or []
        if not nodes:
            out.append('<p>'+h(item.get('error','Узлы не получены'))+'</p></details>'); continue
        row_ids=sorted({n.get('row',0) for n in nodes}); col_ids=sorted({n.get('col',0) for n in nodes})
        mapping={(n.get('row'),n.get('col')):n for n in nodes}
        out.append('<table class="board">')
        for r in range(min(row_ids),max(row_ids)+1):
            out.append('<tr>')
            for c in range(min(col_ids),max(col_ids)+1):
                n=mapping.get((r,c))
                if n is None:
                    out.append('<td class="missing"></td>');continue
                flag='open' if as_open(n.get('open')) else 'locked'
                if n.get('type')=='Start':flag+=' start'
                tip='%s [%s] R%s/C%s: %s' % (n.get('name','node'),
                       'OPEN' if as_open(n.get('open')) else 'locked',r,c,'; '.join(desc_lines(n.get('effectList'))))
                out.append('<td class="'+flag+'" title="'+h(tip)+'">'+('●' if as_open(n.get('open')) else '·')+'</td>')
            out.append('</tr>')
        out.append('</table><p><small>Зелёные — открытые, тёмные — закрытые. Наведи мышь для эффекта.</small></p>')
        for key,title in [('openStatEffectList','Суммарные бонусы характеристик'),
                          ('openSkillEffectList','Бонусы навыков')]:
            out.append('<p><b>'+title+':</b><br>'+'<br>'.join(map(h,desc_lines(board.get(key))))+'</p>')
        out.append('</details>')
    out.append('</section>')
    if archive.get('errors'):
        out.append('<section><h2>Предупреждения о неполных данных</h2><pre>'+h('\n'.join(archive['errors']))+'</pre></section>')
    out.append('</html>')
    return '\n'.join(out)

def perform(client):
    result={'metadata':{'captured_at':timestamp(), 'character':CHAR_NAME,'region':REGION,
                        'server_id':SERVER_ID,'character_id':CHAR_ID,
                        'source':'Public AION 2 NCSOFT armory API'},
            'character_info':None,'equipment':None,'equipped_items':[],
            'daevanion_boards':[], 'errors':[]}
    char_id=CHAR_ID; server_id=SERVER_ID
    print('[1/4] Получаю профиль Darkleam с NCSOFT...')
    try:
        info=client.character('info',char_id,server_id)
        if not isinstance(info,dict) or not (info.get('profile') or {}).get('characterName'):
            raise APIError('Ответ API не содержит profile.characterName')
        if (info['profile']['characterName']).casefold()!=CHAR_NAME.casefold():
            raise APIError('API вернул другого персонажа: '+str(info['profile']['characterName']))
    except Exception as exc:
        print('  Прямой ID не сработал:', exc)
        print('  Ищу Darkleam по имени и серверу ...')
        search=client.search()
        matches=[x for x in search.get('list',[]) if re.sub('<[^>]+>','',x.get('name','')).casefold()==CHAR_NAME.casefold() and int(x.get('serverId',0))==SERVER_ID]
        if not matches:
            raise APIError('Нельзя найти Darkleam / EU / Quai. Поиск вернул %s совпадений. Первичная ошибка: %s' %
                           (len(search.get('list',[])),exc))
        server_id=int(matches[0]['serverId'])
        char_id=urllib.parse.unquote(matches[0]['characterId'])
        info=client.character('info',char_id,server_id)
        if (info.get('profile') or {}).get('characterName','').casefold()!=CHAR_NAME.casefold():
            raise APIError('Имя не совпадает после поиска; запрос остановлен')
    result['metadata']['server_id']=server_id
    result['metadata']['character_id']=char_id
    result['character_info']=info
    print('  OK:', info['profile']['characterName'], 'CP', info['profile'].get('combatPower'))
    print('[2/4] Получаю снаряжение и навыки ...')
    eq=client.character('equipment',char_id,server_id)
    if not isinstance(eq,dict) or not isinstance(eq.get('equipment'),dict):
        raise APIError('Снаряжение в ответе API отсутствует')
    result['equipment']=eq
    slots=(eq.get('equipment') or {}).get('equipmentList') or []
    print('  Надето вещей:',len(slots))
    print('[3/4] Получаю характеристики каждой вещи ...')
    for n,slot in enumerate(slots,1):
        pos=slot.get('slotPos');name=slot.get('name','?'); val={'slot_pos':pos,'slot':slot, 'data':None}
        try:
            data=client.character('equipment/item',char_id,server_id,
                                  id=slot['id'],enchantLevel=slot.get('enchantLevel',0),slotPos=pos)
            if not isinstance(data,dict) or not data.get('id'):
                raise APIError('Неожиданный ответ: нет id')
            val['data']=data
            print('  %d/%d: %s [OK]' % (n,len(slots),name))
        except Exception as e:
            val['error']=str(e)
            result['errors'].append('Вещь '+str(name)+': '+str(e))
            print('  %d/%d: %s [ОШИБКА: %s]' % (n,len(slots),name,e))
        result['equipped_items'].append(val)
    print('[4/4] Получаю все таблицы Даэваниона (точные узлы) ...')
    boards=(info.get('daevanion') or {}).get('boardList') or []
    for board in boards:
        bid=board.get('id');val={'board_id':bid,'summary':board,'data':None}
        try:
            data=client.character('daevanion/detail',char_id,server_id,boardId=bid)
            if not isinstance(data,dict) or not isinstance(data.get('nodeList'),list):
                raise APIError('В ответе нет nodeList')
            val['data']=data
            print('  %s [%d узлов]' % (board.get('name',bid),len(data['nodeList'])))
        except Exception as e:
            val['error']=str(e)
            result['errors'].append('Таблица '+str(board.get('name',bid))+': '+str(e))
            print('  %s [ОШИБКА: %s]' % (board.get('name',bid),e))
        result['daevanion_boards'].append(val)
    return result

def save(archive,directory):
    path=Path(directory)
    name='leam_full_'+dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')+'.zip'
    dest=path/name
    previous,prevname=latest_previous(path)
    template=path/'leam_game_stats.csv'
    if not template.exists():
        template.write_text(true_stats_template(),encoding='utf-8-sig')
    stats=produce(archive,template)
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        z.writestr('leam_all.json',json.dumps(archive,ensure_ascii=False,indent=2))
        z.writestr('leam_report.txt',report_text(archive))
        z.writestr('leam_stats.csv',stats['summary_csv'])
        z.writestr('leam_stat_details.csv',stats['details_csv'])
        z.writestr('leam_stats.html',stats['html'])
        z.writestr('leam_game_stats.csv',template.read_bytes())
        if previous is not None:
            z.writestr('leam_changes.txt',compare(previous,archive,prevname))
        z.writestr('leam_boards.html',report_html(archive))
        z.writestr('README.txt','Открой HTML двойным щелчком. Передай весь ZIP в ChatGPT.\n'
                   'JSON содержит сырые ответы публичного API NCSOFT на момент экспорта.\n'
                   'Это НЕ данные текущего игрового клиента и не авторизация в аккаунте.\n'
                   'Ошибки отдельных запросов указаны внутри JSON/TXT.\n')
    return dest

def main():
    print('=== AION 2 / Darkleam — публичные данные персонажа ===')
    print('Без паролей, cookies, установки модулей и запуска игры.\n')
    try:
        data=perform(PublicAPI())
        dest=save(data,Path(__file__).resolve().parent)
        items=sum(bool(x.get('data')) for x in data['equipped_items'])
        boards=sum(bool(x.get('data')) for x in data['daevanion_boards'])
        print('\nГОТОВО! Файл:',dest)
        print('Подробно прочитано вещей:',items,'/',len(data['equipped_items']))
        print('Подробно прочитано таблиц:',boards,'/',len(data['daevanion_boards']))
        print('Предупреждений:',len(data['errors']))
        print('Сводка известных бонусов и подробная CSV/HTML таблица добавлены в архив.')
        print('Точные итоговые боевые статы, если известны, впиши в leam_game_stats.csv.')
        print('Отправь этот ZIP сюда. Если есть предупреждения, данные частичные.')
        return 0
    except Exception as exc:
        message=type(exc).__name__+': '+str(exc)
        print('\nНЕ ПОЛУЧИЛОСЬ:',message)
        log=Path(__file__).resolve().parent/'leam_error.txt'
        log.write_text(timestamp()+'\n'+message+'\n', encoding='utf-8')
        print('Лог сохранён:',log)
        return 1

if __name__=='__main__':
    sys.exit(main())
