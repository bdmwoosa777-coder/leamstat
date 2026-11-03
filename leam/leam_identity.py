# -*- coding: utf-8 -*-
"""Resolve character across EU servers, with fail-closed identity verification."""
import html
import json
from collections import Counter
from pathlib import Path
import re
import urllib.parse


class IdentityError(Exception):
    pass


def _name(value):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip().casefold()


def _profile_ok(info, name, previous):
    profile = (info or {}).get("profile") or {}
    if _name(profile.get("characterName")) != _name(name):
        return False
    old = (previous.get("character_info") or {}).get("profile") or {}
    for key in ("raceId", "pcId"):
        if old.get(key) is not None and profile.get(key) is not None and old[key] != profile[key]:
            return False
    return True


def _previous_snapshot(path):
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if data.get("errors"):
            return {}
        return data
    except (OSError, ValueError, TypeError):
        return {}


def _gear_ids(equipment):
    slots = (((equipment or {}).get("equipment") or {}).get("equipmentList") or [])
    return Counter(int(x["id"]) for x in slots if x.get("id"))


def _gear_match(client, row, previous, name):
    sid = int(row["serverId"])
    cid = urllib.parse.unquote(str(row["characterId"]))
    info = client.character("info", cid, sid)
    if not _profile_ok(info, name, previous):
        return None
    before = _gear_ids(previous.get("equipment"))
    if sum(before.values()) < 10:
        return None
    now = _gear_ids(client.character("equipment", cid, sid))
    identical = sum((before & now).values())
    level_before = ((previous.get("character_info") or {}).get("profile") or {}).get("characterLevel")
    level_now = ((info.get("profile") or {}).get("characterLevel"))
    if level_before and level_now and (int(level_now) < int(level_before) or int(level_now) > int(level_before) + 5):
        return None
    if identical < max(8, int(sum(before.values()) * .5)):
        return None
    return {"server_id": sid, "character_id": cid, "info": info,
            "matched_items": identical, "total_items": sum(before.values())}


def _search_matches(client, name):
    found = {}
    page = 1
    while True:
        response = client.search(page)
        if not isinstance(response, dict) or not isinstance(response.get("list"), list):
            raise IdentityError("Character search returned an unexpected response.")
        for row in response["list"]:
            if _name(row.get("name")) != _name(name):
                continue
            if not row.get("serverId") or not row.get("characterId"):
                continue
            key = (int(row["serverId"]), urllib.parse.unquote(str(row["characterId"])))
            found[key] = row
        paging = response.get("pagination") or {}
        last = int(paging.get("endPage") or 1)
        if page >= last:
            break
        if page >= 20:
            raise IdentityError("Character search has >20 pages; refusing incomplete identity scan.")
        page += 1
    return list(found.values())


def resolve(client, name, region, fallback_server, fallback_id, saved_path="data/leam.json"):
    previous = _previous_snapshot(saved_path)
    meta = previous.get("metadata") or {}
    sid = int(meta.get("server_id") or fallback_server)
    cid = str(meta.get("character_id") or fallback_id)
    old_ref = (sid, cid)

    try:
        matches = _search_matches(client, name)
    except Exception as e:
        print("Поиск по EU временно недоступен:", str(e))
        try:
            info = client.character("info", cid, sid)
        except Exception as direct_error:
            raise IdentityError("Search and last-known character lookup both failed: " + str(direct_error)) from direct_error
        if not _profile_ok(info, name, previous):
            raise IdentityError("Last-known character identity mismatch.")
        print("Сохраняю подтверждённый ID; проверить одноимённых персонажей пока не удалось.")
        return sid, cid, info, {"method": "previous_id_search_unavailable", "duplicates_checked": False}

    print("Найдено точных совпадений имени по EU:", len(matches))
    for row in matches:
        print("  serverId=%s, server=%s, level=%s" %
              (row.get("serverId"), row.get("serverName", "?"), row.get("level", "?")))

    known_id = [row for row in matches
                if urllib.parse.unquote(str(row["characterId"])) == cid]
    if len(known_id) == 1:
        row = known_id[0]
        new_sid = int(row["serverId"])
        info = client.character("info", cid, new_sid)
        if not _profile_ok(info, name, previous):
            raise IdentityError("Known character ID does not match expected profile.")
        if new_sid != sid:
            print("Подтверждён перенос по прежнему ID: %s -> %s" % (sid, new_sid))
        return new_sid, cid, info, {"method": "same_character_id", "duplicates_checked": True,
                                    "matching_names": len(matches)}

    if len(known_id) > 1:
        raise IdentityError("Same character ID found on multiple EU servers. Manual check required.")

    if not matches:
        # Sometimes search indexing lags behind a direct profile lookup.
        try:
            info = client.character("info", cid, sid)
        except Exception as e:
            raise IdentityError("No matching characters in EU search and direct lookup failed: " + str(e)) from e
        if not _profile_ok(info, name, previous):
            raise IdentityError("No reliable matching character.")
        print("Поиск пока не индексирует профиль; подтверждён старый ID.")
        return sid, cid, info, {"method": "previous_id_search_lag", "duplicates_checked": True,
                                "matching_names": 0}

    candidates = []
    for row in matches:
        try:
            candidate = _gear_match(client, row, previous, name)
            if candidate:
                candidates.append(candidate)
        except Exception as e:
            print("  Не удалось проверить кандидата", row.get("serverName"), str(e))
    candidates.sort(key=lambda x: x["matched_items"], reverse=True)
    if len(candidates) != 1:
        raise IdentityError(
            "Имя найдено, но нельзя однозначно подтвердить личность по экипировке. "
            "Совпадающих кандидатов: %d. Старые данные сохранены; нужна проверка пользователя." % len(candidates))
    best = candidates[0]
    print("Перенос подтверждён совпадением экипировки: %d/%d, serverId=%s" %
          (best["matched_items"], best["total_items"], best["server_id"]))
    return best["server_id"], best["character_id"], best["info"], {
        "method": "equipment_fingerprint", "duplicates_checked": True,
        "matching_names": len(matches), "matched_items": best["matched_items"]}
