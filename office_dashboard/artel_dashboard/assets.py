"""Ассеты офиса: какие персонажи, анимации, двери, мебель и Кокошка есть в паке."""
import glob
import json
import os

SHEETS_DIR = os.path.join('04_CHARACTER_MODELS', '03_CHARACTER_SPRITESHEETS')
PLATE = os.path.join('02_ANIMATION', 'character_free_restoration_plate.png')
DECOR = {'cabinet': '53_low_side_cabinet.png', 'coffee': '34_coffee_machine.png', 'snacks': '35_snack_bowl.png'}


def find_animation_set(pack):
    """Лучший из наборов 06_CHARACTER_ANIMATIONS*: больше всего анимаций на персонажа.

    Нужны все 4 направления ходьбы и посадка/работа сидя — наборы без них пропускаются.
    """
    required = {'idle_down', 'walk_left', 'walk_right', 'walk_up', 'walk_down',
                'work_right', 'work_left', 'sit_down_right', 'stand_up_right', 'seated_idle_right'}
    best = None
    for folder in glob.glob(os.path.join(pack, '06_CHARACTER_ANIMATIONS*')):
        chars = []
        for anim_path in sorted(glob.glob(os.path.join(folder, 'characters', '*', 'animations.json'))):
            atlas_path = os.path.join(os.path.dirname(anim_path), 'atlas.png')
            try:
                with open(anim_path, encoding='utf-8') as f:
                    anims = json.load(f)
            except Exception:
                continue
            if os.path.exists(atlas_path) and required <= set(anims.get('animations', {})):
                chars.append((os.path.basename(os.path.dirname(anim_path)), atlas_path, anims))
        if not chars:
            continue
        score = (len(chars), min(len(c[2]['animations']) for c in chars))
        if best is None or score > best[0]:
            best = (score, folder, chars)
    return (best[1], best[2]) if best else None


def discover_assets(pack, cat=False):
    if not os.path.isdir(pack):
        return {'error': f'Ассет-пак не найден: {pack}. Укажите --assets или OFFICE_ASSETS.'}

    def url(rel):
        return '/assets/' + rel.replace(os.sep, '/')

    result = {'plate': url(PLATE), 'office': None, 'characters': [], 'animationSet': None}
    sheets = os.path.join(pack, SHEETS_DIR)
    anim_set = find_animation_set(pack)
    if anim_set:
        folder, chars = anim_set
        result['animationSet'] = os.path.basename(folder)
        for char_id, atlas_path, anims in chars:
            result['characters'].append({
                'id': char_id,
                'format': 'v3',
                'atlas': url(os.path.relpath(atlas_path, pack)),
                'frameSize': anims.get('frameSize', {'w': 128, 'h': 128}),
                'pivot': anims.get('pivot', {'x': 64, 'y': 112}),
                'animations': anims['animations'],
            })
    for name in sorted(os.listdir(sheets)) if os.path.isdir(sheets) else []:
        folder = os.path.join(sheets, name)
        if not os.path.isdir(folder):
            continue
        manifest_path = None
        for candidate in sorted(glob.glob(os.path.join(folder, '*', 'manifest.json'))):
            if os.path.exists(os.path.join(os.path.dirname(candidate), 'atlas.png')):
                manifest_path = candidate
                break
        if not manifest_path:
            continue
        with open(manifest_path, encoding='utf-8') as f:
            manifest = json.load(f)
        atlas = url(os.path.relpath(os.path.join(os.path.dirname(manifest_path), 'atlas.png'), pack))
        if name == 'office':
            result['office'] = {'manifest': manifest, 'atlas': atlas}
            continue
    # Отдельные предметы для кухонного уголка (необязательные)
    decor_dir = os.path.join(pack, '03_INDIVIDUAL_TRANSPARENT_ASSETS', '01_SCENE_SCALE_PNG')
    result['decor'] = {}
    for key, fname in DECOR.items():
        if os.path.exists(os.path.join(decor_dir, fname)):
            result['decor'][key] = url(os.path.relpath(os.path.join(decor_dir, fname), pack))
    # Мягкая мебель, общение и PlayStation (08_LOUNGE_AND_SOCIAL): доп. клипы персонажей + тумба с ТВ
    result['lounge'] = None
    lounge_dir = os.path.join(pack, '08_LOUNGE_AND_SOCIAL')
    lounge_manifest = os.path.join(lounge_dir, 'manifest.json')
    if os.path.exists(lounge_manifest):
        with open(lounge_manifest, encoding='utf-8') as f:
            lm = json.load(f)
        chars = {}
        for cdir in sorted(glob.glob(os.path.join(lounge_dir, 'characters', '*'))):
            try:
                with open(os.path.join(cdir, 'atlas.json'), encoding='utf-8') as f:
                    frames = {k: [v['frame']['x'], v['frame']['y'], v['frame']['w'], v['frame']['h']]
                              for k, v in json.load(f)['frames'].items()}
                with open(os.path.join(cdir, 'animations.json'), encoding='utf-8') as f:
                    anims = json.load(f)
            except (OSError, ValueError, KeyError):
                continue
            chars[os.path.basename(cdir)] = {'atlas': url(os.path.relpath(os.path.join(cdir, 'atlas.png'), pack)),
                                             'frames': frames, 'animations': anims}
        cabinet = None
        cab_dir = os.path.join(lounge_dir, 'props', 'media_cabinet')
        if os.path.exists(os.path.join(cab_dir, 'manifest.json')):
            with open(os.path.join(cab_dir, 'manifest.json'), encoding='utf-8') as f:
                cabinet = json.load(f)
            with open(os.path.join(cab_dir, 'atlas.json'), encoding='utf-8') as f:
                cabinet['frames'] = [[v['frame']['x'], v['frame']['y'], v['frame']['w'], v['frame']['h']]
                                     for v in json.load(f)['frames'].values()]
            cabinet['atlas'] = url(os.path.relpath(os.path.join(cab_dir, 'atlas.png'), pack))
        result['lounge'] = {'frameSize': lm.get('frameSize'), 'pivot': lm.get('pivot'), 'scene': lm.get('scene'),
                            'characters': chars, 'cabinet': cabinet}

    # Кошка Кокошка (только с флагом --cat): первый спрайтшит в папке cat*/ (manifest.json + atlas.png)
    result['cat'] = None
    for manifest_path in [] if not cat else sorted(glob.glob(os.path.join(pack, 'cat*', '**', 'manifest.json'), recursive=True)):
        atlas_path = os.path.join(os.path.dirname(manifest_path), 'atlas.png')
        if os.path.exists(atlas_path):
            with open(manifest_path, encoding='utf-8') as f:
                result['cat'] = {'manifest': json.load(f), 'atlas': url(os.path.relpath(atlas_path, pack))}
            break
    # Двери кабинета руководителя и переговорки (07_DOOR_ANIMATIONS): свой фон с открытыми проёмами + створки
    result['doors'] = []
    door_manifest = os.path.join(pack, '07_DOOR_ANIMATIONS', 'manifest.json')
    if os.path.exists(door_manifest):
        base = os.path.dirname(door_manifest)
        with open(door_manifest, encoding='utf-8') as f:
            dm = json.load(f)
        plate = os.path.join(base, dm.get('scene', {}).get('background', ''))
        if os.path.isfile(plate):
            result['plate'] = url(os.path.relpath(plate, pack))
        for d in dm.get('doors', []):
            atlas = os.path.join(base, d['image'])
            if not os.path.exists(atlas):
                continue
            fg = os.path.join(base, d.get('foreground', ''))
            result['doors'].append({
                'id': d['id'], 'atlas': url(os.path.relpath(atlas, pack)),
                'foreground': url(os.path.relpath(fg, pack)) if os.path.isfile(fg) else None,
                'frameSize': d['frameSize'], 'scenePosition': d['scenePosition'], 'depthY': d['depthY'],
                'waypoints': d['waypoints'], 'autoCloseDelayMs': d.get('autoCloseDelayMs', 1100),
                'animations': d['animations'],
            })
    if not result['characters']:
        result['error'] = (f'В {pack} не найден набор анимаций 06_CHARACTER_ANIMATIONS* '
                           '(characters/<id>/atlas.png + animations.json).')
    return result
