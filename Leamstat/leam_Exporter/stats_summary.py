# -*- coding: utf-8 -*-
"""Only observable source bonuses. Not a reconstruction of in-game final combat stats."""
import collections,csv,html,io,json,re
from pathlib import Path

STAT_HEADERS = ['Источник','Слот/таблица','Предмет/титул','ID параметра','Параметр','Значение','Единица','Описание']
SUM_HEADERS = ['ID параметра','Название','Единица','Источник','Сумма известных бонусов','Количество записей','Примечание']
GAME_STATS_EXAMPLE = [
 ('Attack','Атака',''), ('Accuracy','Меткость',''), ('Critical Hit','Критический удар',''),
 ('Combat Speed','Скорость боя','%'), ('PvE Attack','PvE-атака',''),
 ('PvE Damage Boost','PvE-усиление урона','%'), ('Damage Boost','Усиление урона','%'),
 ('HP','Здоровье',''), ('MP','Мана',''), ('Defense','Защита',''),
 ('Critical Damage Boost','Критический урон','%'), ('Block','Блок',''),
]

num_pattern = re.compile(r'^\s*([+-]?\d+(?:[.,]\d+)?)\s*(%?)\s*$')
text_stat_pattern = re.compile(r'^\s*(.+?)\s*([+-]\s*\d+(?:[.,]\d+)?)\s*(%)?\s*$')


def parse_number(s):
    m=num_pattern.match(str(s).strip())
    if not m:return None, None
    return float(m.group(1).replace(',','.')),m.group(2) or 'ед.'


def make_rows(snapshot):
    rows=[]
    def add(source,slot,item,key,label,value,remark=''):
        v,unit=parse_number(value)
        rows.append({'source':source,'slot':str(slot),'item':str(item),'id':str(key),
                     'label':str(label),'value':v,'raw':str(value),'unit':unit or '', 'remark':str(remark)})
    for item in snapshot.get('equipped_items',[]):
        slot=item.get('slot') or {}; d=item.get('data') or {};pos=slot.get('slotPosName',item.get('slot_pos',''))
        name=slot.get('name',d.get('name',''))
        for field,cat in [('mainStats','Вещи: основные'),('subStats','Вещи: случайные'),('magicStoneStat','Манастоуны')]:
            for s in d.get(field) or []:
                remarks=[]
                if s.get('minValue'):
                    remarks.append('Диапазон '+str(s['minValue'])+'–'+str(s.get('value',''))+', не суммируется как плоский бонус')
                    # Weapon base range must not be mistaken for flat attack
                    add(cat,pos,name,str(s.get('id',''))+' [диапазон]',s.get('name',''),
                        str(s.get('minValue'))+'–'+str(s.get('value','')), '; '.join(remarks))
                else:
                    add(cat,pos,name,s.get('id',''),s.get('name',''),s.get('value',''), '')
                extra,ex_unit=parse_number(s.get('extra',''))
                if extra is not None and extra != 0:
                    add('Вещи: прибавка от усиления',pos,name,str(s.get('id',''))+' [усиление]',
                        str(s.get('name',''))+' (усиление)',str(s['extra']),
                        'Отдельно от базового значения; не складывать с диапазоном оружия как с независимым статом')
    # Summarized already by the armory. Do NOT sum nodes and these lists together.
    for b in snapshot.get('daevanion_boards') or []:
        board=b.get('data') or {};name=(b.get('summary') or {}).get('name',b.get('board_id',''))
        for effect in board.get('openStatEffectList') or []:
            desc=effect.get('desc','') if isinstance(effect,dict) else str(effect)
            m=text_stat_pattern.match(desc)
            if m:
                label=m.group(1).strip(); v=m.group(2).replace(' ','')+(m.group(3) or '')
                add('Даэванион: бонусы открытых узлов',name,'Открытые узлы',label,label,v,desc)
            else:
                add('Даэванион: бонусы открытых узлов',name,'Открытые узлы',desc,desc,desc,'Не удалось однозначно разобрать')
    # equipStatList shows equipped titles; statList is collection progress, track separately.
    for title in (snapshot.get('character_info') or {}).get('title',{}).get('titleList') or []:
        name=title.get('name','')
        for kind,src in [('equipStatList','Титулы: экипированные'),('statList','Титулы: коллекционные')]:
            for s in title.get(kind) or []:
                desc=s.get('desc','') if isinstance(s,dict) else str(s)
                m=text_stat_pattern.match(desc)
                if m:
                    lab=m.group(1).strip();value=m.group(2).replace(' ','')+(m.group(3) or '')
                    add(src,title.get('equipCategory',''),name,lab,lab,value,desc)
                else:
                    add(src,title.get('equipCategory',''),name,desc,desc,desc,'Неформализованный эффект')
    return rows


def summed(rows):
    grouped=collections.defaultdict(list)
    for row in rows:
        if row['value'] is None:continue
        grouped[(row['id'],row['label'],row['unit'],row['source'])].append(row['value'])
    result=[]
    for (key,label,unit,source),nums in sorted(grouped.items(),key=lambda x:(x[0][1].casefold(),x[0][3])):
        total=round(sum(nums),4)
        result.append([key,label,unit,source,total,len(nums),
                       'Только известные источники! Не итоговый стат персонажа.'])
    return result


def compact_by_stat(sum_rows):
    cat=collections.defaultdict(dict)
    names={}
    for key,label,unit,source,total,count,comment in sum_rows:
        cat[(key,unit)][source]=total
        names[(key,unit)]=label
    return names,cat


def render_csv(rows):
    f=io.StringIO(newline='');w=csv.writer(f,delimiter=';'); w.writerows(rows)
    return '\ufeff'+f.getvalue()


def read_true_stats(filepath):
    path=Path(filepath)
    if not path.exists(): return []
    with path.open(encoding='utf-8-sig',newline='') as fh:
        r=csv.DictReader(fh,delimiter=';')
        if not r.fieldnames or not {'Ключ','Название','Значение','Единица'}.issubset(set(r.fieldnames)):
            return []
        return [rec for rec in r if str(rec.get('Значение','')).strip()]


def true_stats_template():
    return render_csv([['Ключ','Название','Значение','Единица','Комментарий']]+[
        [key,name,'',unit,'Ввести точное число из игрового окна персонажа'] for key,name,unit in GAME_STATS_EXAMPLE])


def render_html(snapshot,rows, sums, real_stats):
    meta=snapshot.get('metadata') or {};info=snapshot.get('character_info') or {}
    profile=info.get('profile') or {}
    esc=lambda x:html.escape(str(x),quote=True)
    css='''body{background:#0c121b;color:#e6edf8;font-family:system-ui,Segoe UI,Arial;max-width:1250px;margin:auto;padding:25px}h1{color:#a3e2ff}h2{color:#bfe7fc}p,small{color:#adbfd0}strong{color:#f0f6ff}.tile{display:inline-block;background:#182435;border:1px solid #40556b;padding:10px 20px;margin:6px;border-radius:10px}.warning{background:#3b2d14;border-left:4px solid #e5b343;padding:14px;border-radius:6px;color:#f5eacb}.ok{background:#142b27;border-left:4px solid #4ac9ac;padding:14px}.box{background:#131e2c;border:1px solid #304357;border-radius:12px;padding:15px;margin:20px 0;overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:8px 9px;border-bottom:1px solid #2c3949;text-align:left}th{position:sticky;top:0;background:#23374e;color:#eaf6ff}tr:hover{background:#1c2b3b}input{padding:10px;background:#192739;color:white;border:1px solid #597792;border-radius:5px;width:300px}a{color:#86d9ff}.number{text-align:right;font-variant-numeric:tabular-nums}'''
    out=['<!DOCTYPE html><html lang="ru"><meta charset="utf-8"><title>Darkleam — сводка известных статов</title><style>'+css+'</style>',
         '<h1>Darkleam — сводная таблица характеристик</h1>',
         '<p>Снимок '+esc(meta.get('captured_at',''))+' · Публичные данные NCSOFT</p>',
         '<div class="tile">Уровень <strong>'+esc(profile.get('characterLevel','?'))+'</strong></div>',
         '<div class="tile">Боевая мощь <strong>'+esc(profile.get('combatPower','?'))+'</strong></div>',
         '<div class="tile">iLvl <strong>'+esc(next((s['value'] for s in info.get('stat',{}).get('statList') or [] if s.get('type')=='ItemLevel'),'?'))+'</strong></div>',
         '<p class="warning"><strong>Не путать!</strong> В таблицах ниже сложены доступные бонусы от видимых источников, но это <strong>не</strong> окончательные боевые характеристики персонажа в игре. Часть влияний скрыта или применяется по формулам, а разные типы Attack / Attack Bonus и Accuracy / Accuracy Bonus специально не объединены.</p>']
    out.append('<div class="box"><h2>Итоговые значения из игры (вручную)</h2>')
    if real_stats:
        out.append('<table><tr><th>Параметр</th><th>Значение</th><th>Комментарий</th></tr>')
        for rec in real_stats:out.append('<tr><td>'+esc(rec['Название'])+'</td><td>'+esc(rec['Значение'])+esc(rec.get('Единица',''))+'</td><td>'+esc(rec.get('Комментарий',''))+'</td></tr>')
        out.append('</table>')
    else:
        out.append('<p>Пока нет точных итоговых боевых статов. Впиши их в <code>GAME_STATS.csv</code> из окна персонажа — следующая выгрузка подхватит эти значения без изменения сырых данных API.</p>')
    out.append('</div><div class="box"><h2>Основные и божественные атрибуты — точные данные API</h2><table><tr><th>Атрибут</th><th>Число</th><th>Производные эффекты</th></tr>')
    for s in info.get('stat',{}).get('statList') or []:
        if s.get('type')=='ItemLevel':continue
        out.append('<tr><td>'+esc(s.get('name',''))+'</td><td>'+esc(s.get('value',''))+'</td><td>'+esc('; '.join(s.get('statSecondList') or []))+'</td></tr>')
    out.append('</table></div><div class="box"><h2>Известные бонусы по источникам</h2><p>Каждая строка = конкретный источник. Одноимённые, но разные типы статов не смешиваются.</p><input id="q" placeholder="Поиск, например Combat Speed" oninput="filter()"><table id="t"><tr><th>Характеристика</th><th>Значение</th><th>Источник</th><th>Записей</th></tr>')
    for key,label,unit,source,total,count,_ in sums:
        out.append('<tr><td>'+esc(label)+' <small>('+esc(key)+')</small></td><td class="number">'+esc('%g'%total)+(' %' if unit=='%' else '')+'</td><td>'+esc(source)+'</td><td>'+esc(count)+'</td></tr>')
    out.append('</table></div><div class="box"><h2>Все подробности (каждый предмет, камень, таблица, титул)</h2><input id="q2" placeholder="Поиск по вещам, параметрам" oninput="filter2()"><table id="t2"><tr><th>Источник</th><th>Слот</th><th>Предмет/таблица</th><th>Параметр</th><th>Значение</th><th>Примечание</th></tr>')
    for r in rows:
        out.append('<tr><td>'+esc(r['source'])+'</td><td>'+esc(r['slot'])+'</td><td>'+esc(r['item'])+'</td><td>'+esc(r['label'])+'</td><td>'+esc(r['raw'])+'</td><td>'+esc(r['remark'])+'</td></tr>')
    out.append('''</table></div><p>Агрегаты сохранены отдельно от сырых ответов API. Статы титулов из коллекций и экипированных титулов разделены для исключения неверного сложения.</p><script>function run(a,b){let v=document.getElementById(a).value.toLowerCase();for(let t of document.getElementById(b).querySelectorAll('tr')){t.style.display=t.textContent.toLowerCase().includes(v)?'':'none'}}function filter(){run('q','t')}function filter2(){run('q2','t2')}</script></html>''')
    return ''.join(out)


def produce(snapshot,game_stats_csv=None):
    rows=make_rows(snapshot); agg=summed(rows)
    detailed=[STAT_HEADERS]+[[r['source'],r['slot'],r['item'],r['id'],r['label'],r['raw'],r['unit'],r['remark']] for r in rows]
    sum_matrix=[SUM_HEADERS]+agg
    actual=read_true_stats(game_stats_csv) if game_stats_csv else []
    return {'known_rows':rows,'aggregate':agg,'actual':actual,
            'details_csv':render_csv(detailed),'summary_csv':render_csv(sum_matrix),
            'html':render_html(snapshot,rows,agg,actual)}
