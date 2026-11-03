# -*- coding: utf-8 -*-
"""Comparisons of two NCSOFT public-armory exports; source bonuses, not game final stats."""
from collections import defaultdict
import zipfile,json
from pathlib import Path
from stats_summary import produce

def latest_previous(folder):
    files=sorted(Path(folder).glob('Darkleam_FULL_*.zip'),key=lambda p:p.stat().st_mtime,reverse=True)
    for p in files:
        try:
            with zipfile.ZipFile(p) as f:
                data=json.loads(f.read('Darkleam_ALL.json'))
                if (data.get('character_info') or {}).get('profile',{}).get('characterName','').casefold()=='darkleam':
                    return data,p.name
        except (ValueError,KeyError,OSError,zipfile.BadZipFile): continue
    return None,None

def compare(old,new,filename):
    op=(old.get('character_info') or {}).get('profile') or {}
    np=(new.get('character_info') or {}).get('profile') or {}
    a=[]
    a.append('СРАВНЕНИЕ: '+str(old.get('metadata',{}).get('captured_at',''))+' → '+str(new.get('metadata',{}).get('captured_at','')))
    a.append('Предыдущий файл: '+filename+'\n')
    for key,title in [('combatPower','Боевая мощь'),('characterLevel','Уровень персонажа')]:
        v1=op.get(key);v2=np.get(key)
        if v1!=v2:
            a.append(f'{title}: {v1} → {v2}' + (f' ({v2-v1:+})' if isinstance(v1,(int,float)) and isinstance(v2,(int,float)) else ''))
    oldstats={x.get('type'):x.get('value') for x in (old.get('character_info') or {}).get('stat',{}).get('statList') or []}
    newstats={x.get('type'):x.get('value') for x in (new.get('character_info') or {}).get('stat',{}).get('statList') or []}
    for key in sorted(set(oldstats)|set(newstats)):
        if oldstats.get(key)!=newstats.get(key): a.append(f'Атрибут {key}: {oldstats.get(key)} → {newstats.get(key)}')
    a.append('\n=== ЭКИПИРОВКА И ЗАТОЧКА ===')
    old_items={str(x.get('slot_pos')):x for x in old.get('equipped_items') or []}; new_items={str(x.get('slot_pos')):x for x in new.get('equipped_items') or []}
    for k in sorted(set(old_items)|set(new_items),key=lambda v:int(v) if v.isdecimal() else 999):
        old_slot=old_items.get(k,{}).get('slot') or {};new_slot=new_items.get(k,{}).get('slot') or {}
        x=(old_slot.get('name'),old_slot.get('enchantLevel'),old_slot.get('exceedLevel'));y=(new_slot.get('name'),new_slot.get('enchantLevel'),new_slot.get('exceedLevel'))
        if x!=y:a.append(f'{new_slot.get("slotPosName",old_slot.get("slotPosName",k))}: {x} → {y}')
        else:
            # Distinguish enhancement details if same item and swapped stones
            def sig(item):
                data=item.get('data') or {}
                return json.dumps({key:data.get(key) for key in ('mainStats','subStats','magicStoneStat','godStoneStat')},sort_keys=True,ensure_ascii=False)
            if k in old_items and k in new_items and sig(old_items[k])!=sig(new_items[k]):
                a.append(f'{new_slot.get("slotPosName",k)}: изменились характеристики или камни (детали — в JSON)')
    a.append('\n=== ИЗМЕНЕНИЯ ИЗВЕСТНЫХ БОНУСОВ ПО ИСТОЧНИКАМ ===')
    def agg(d):
        return {(r[0],r[2],r[3]):r[4] for r in produce(d)['aggregate']}
    x=agg(old);y=agg(new)
    for key in sorted(set(x)|set(y)):
        l=x.get(key,0);r=y.get(key,0)
        if abs(l-r)>1e-7:a.append(f'{key[0]} [{key[2]}]: {l:g} → {r:g} ({r-l:+g} {key[1]})')
    a.append('\n=== ДАЭВАНИОН: ОТКРЫТО УЗЛОВ ===')
    def board_stat(d):
        return {b.get('board_id'):((b.get('summary') or {}).get('name',''), sum(bool(n.get('open')) for n in (b.get('data') or {}).get('nodeList') or [])) for b in d.get('daevanion_boards') or []}
    bs1=board_stat(old);bs2=board_stat(new)
    for id in sorted(set(bs1)|set(bs2)):
        if bs1.get(id)!=bs2.get(id):a.append(f'{bs2.get(id,(bs1.get(id,("?",0))[0],0))[0]}: {bs1.get(id,("",0))[1]} → {bs2.get(id,("",0))[1]}')
    if len(a)<9:a.append('Существенных изменений в проверяемых категориях не обнаружено.')
    a.append('\nВажно: это сравнение публичных данных NCSOFT, не точных итоговых боевых статов из игрового клиента.\n')
    return '\n'.join(a)
