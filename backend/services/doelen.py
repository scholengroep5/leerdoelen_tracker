"""
Doelen service - centrale logica voor vak ID's, namen, validatie en upload.
Eén bron van waarheid. Geen andere plek in de app definieert vaknamen.
"""

import os
import json
import re

DOELEN_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'doelen')

VAK_NAMEN = {
    'doelenset-bao-aardrijkskunde':         'Aardrijkskunde',
    'doelenset-bao-burgerschap':            'Burgerschap',
    'doelenset-bao-frans':                  'Frans',
    'doelenset-bao-geschiedenis':           'Geschiedenis',
    'doelenset-bao-ict':                    'ICT',
    'doelenset-bao-leren-leren':            'Leren leren',
    'doelenset-bao-lichamelijke-opvoeding': 'Lichamelijke opvoeding',
    'doelenset-bao-muzische-vorming':       'Muzische vorming',
    'doelenset-bao-nederlands':             'Nederlands',
    'doelenset-bao-sociale-vaardigheden':   'Sociale vaardigheden',
    'doelenset-bao-wetenschap-techniek':    'Wetenschap en techniek',
    'doelenset-bao-wiskunde':               'Wiskunde',
}


def vak_naam(vak_id):
    if vak_id in VAK_NAMEN:
        return VAK_NAMEN[vak_id]
    cleaned = re.sub(r'^doelenset-bao-', '', vak_id)
    return cleaned.replace('-', ' ').title()


def is_valid_vak_id(vak_id):
    return bool(re.match(r'^[a-z0-9][a-z0-9\-]{2,78}[a-z0-9]$', vak_id))


def get_doelen_path(vak_id):
    return os.path.join(DOELEN_DIR, f'{vak_id}.json')


def list_installed_vakken():
    if not os.path.exists(DOELEN_DIR):
        return []
    return sorted([
        f[:-5] for f in os.listdir(DOELEN_DIR)
        if f.endswith('.json') and f != 'index.json' and is_valid_vak_id(f[:-5])
    ])


def load_index():
    path = os.path.join(DOELEN_DIR, 'index.json')
    if not os.path.exists(path):
        rebuild_index()
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    for vak in data.get('vakken', []):
        vak['naam'] = vak_naam(vak['id'])
    data['vakken'].sort(key=lambda v: v['naam'])
    return data


def load_vak(vak_id):
    if not is_valid_vak_id(vak_id):
        return None
    path = get_doelen_path(vak_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data['vakNaam'] = vak_naam(vak_id)
    return data


def validate_vak_json(data):
    errors = []
    for key in ['vak', 'versie', 'rijen']:
        if key not in data:
            errors.append(f'Verplicht veld ontbreekt: "{key}"')
    if errors:
        return errors
    if not isinstance(data['rijen'], list) or len(data['rijen']) == 0:
        errors.append('"rijen" moet een niet-lege lijst zijn')
        return errors
    doelzinnen = [r for r in data['rijen'] if r.get('type') == 'doelzin']
    if not doelzinnen:
        errors.append('Geen doelzinnen gevonden (type="doelzin") — verkeerd bestand?')
    else:
        zonder_nr = [r for r in doelzinnen if not r.get('goNr')]
        if zonder_nr:
            errors.append(f'{len(zonder_nr)} doelzin(nen) missen een GO! nummer (goNr)')
    vak_id = data.get('vak', '')
    if vak_id and not is_valid_vak_id(vak_id):
        errors.append(f'Ongeldig vak ID: "{vak_id}"')
    return errors


def save_vak(vak_id, data):
    os.makedirs(DOELEN_DIR, exist_ok=True)
    data['vakNaam'] = vak_naam(vak_id)
    path = get_doelen_path(vak_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    rebuild_index()


def delete_vak(vak_id):
    path = get_doelen_path(vak_id)
    if not os.path.exists(path):
        return False
    os.remove(path)
    rebuild_index()
    return True


def rebuild_index():
    os.makedirs(DOELEN_DIR, exist_ok=True)
    vakken = []
    for vak_id in list_installed_vakken():
        try:
            data = load_vak(vak_id)
            if not data:
                continue
            doelzinnen = [r for r in data.get('rijen', []) if r.get('type') == 'doelzin']
            vakken.append({
                'id':               vak_id,
                'naam':             vak_naam(vak_id),
                'aantalDoelzinnen': len(doelzinnen),
                'versie':           data.get('versie', '?'),
            })
        except Exception:
            pass
    vakken.sort(key=lambda v: v['naam'])
    index = {'versie': '2025-01', 'vakken': vakken}
    with open(os.path.join(DOELEN_DIR, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
