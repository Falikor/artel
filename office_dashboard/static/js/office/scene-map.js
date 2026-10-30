'use strict';
/*
 * Офис демонов: Canvas 2D-рендер ассетов LennoxStudio без внешних зависимостей.
 * Персонажи — набор 06_CHARACTER_ANIMATIONS (v3: 32 анимации, ходьба в 4 стороны,
 * посадка/вставание, работа и кофе сидя, отдых на диване).
 * Координаты сцены — в пикселях фона (1254×1254). ?debug=1 — показать граф путей и места.
 */
/* Карта офиса и тексты: этапы демона, граф путей, места (столы, диваны, переговорка), реплики.
 * Файлы js/ подключаются обычными <script> по порядку (index.html): у них общая
 * глобальная область, поэтому порядок важен — константы и классы раньше тех, кто их использует. */

const PLATE = 1254;
const CHAR_SCALE = 1.125;    // ячейка 128 px, рост ~88 px → ~100 px на фоне
const STAND_H = 100;         // рост стоящего персонажа в пикселях фона
const SPEED = 105;           // скорость ходьбы, px/с (≈ длина шага walk-цикла)
const MIN_DWELL = 2.4;       // минимум секунд на точке для коротких этапов
const DEBUG = new URLSearchParams(location.search).has('debug');
// Этапы, когда демон сидит за столом и работает с кодом
const WORKING = new Set(['generating', 'rework', 'reviewing', 'retro']);

const STAGE = {
  starting:   { label: tr("Запуск", "Starting"),             color: '#7dd3fc' },
  polling:    { label: tr("Опрос Jira", "Polling Jira"),         color: '#a5b4fc' },
  idle:       { label: tr("Ждёт задач", "Waiting for tasks"),         color: '#94a3b8' },
  generating: { label: tr("GigaCode пишет код", "GigaCode is coding"), color: '#facc15' },
  reviewing:  { label: tr("Независимое ревью", "Independent review"),  color: '#2dd4bf' },
  rework:     { label: tr("Доработка по ревью", "Addressing review"), color: '#fde047' },
  exploring:  { label: tr("Изучает бэклог", "Exploring backlog"),     color: '#a78bfa' },
  retro:      { label: tr("Ретроспектива", "Retrospective"),      color: '#f0abfc' },
  git:        { label: tr("Git: коммит и пуш", "Git: commit and push"),  color: '#fb923c' },
  jenkins:    { label: tr("Jenkins: деплой", "Jenkins: deploy"),    color: '#c084fc' },
  jira:       { label: tr("Jira: смена статуса", "Jira: change status"), color: '#60a5fa' },
  success:    { label: tr("Готово", "Done"),             color: '#4ade80' },
  error:      { label: tr("Ошибка", "Error"),             color: '#f87171' },
  stopped:    { label: tr("Остановлен", "Stopped"),         color: '#64748b' },
  lost:       { label: tr("Нет сигнала", "No heartbeat"),        color: '#ef4444' },
};

// ------------------------------------------------------------------ карта офиса
// Узлы графа проходов (точки, где стоят ноги персонажа)
const N = {
  // вход (07_DOOR_ANIMATIONS: office_entrance, corridor = улица, room = офис)
  door_out: [622, 1144], door_in: [622, 970], ent_e: [775, 960],
  hub: [700, 700], hub_n: [700, 615],
  // зона отдыха (08_LOUNGE_AND_SOCIAL): верхний проход над ковром, колонка у дивана, нижний край ковра
  lt_w: [775, 682], lt_e: [990, 690], sofa_l: [990, 842], lb_w: [775, 955], lb_m: [870, 955], lb_e: [990, 955],
  arm_e: [870, 893], cab_i: [868, 825],
  col_top: [605, 462], col_mid: [605, 690], col_gap: [605, 612],
  a3: [567, 462], mgr_s: [437, 462], a2: [355, 462], a1: [165, 462],
  pr: [510, 690], a5: [355, 690], a4: [165, 690], pr_s: [510, 880],
  mgr_door: [437, 330], mgr_in: [437, 222], mgr_desk: [262, 222],
  meet_s: [855, 630], meet_n: [855, 458], meet_w: [705, 458], meet_e: [1080, 458],
  meet_lw: [770, 458], meet_le: [1010, 458],
  board: [1060, 690],
};
const EDGES = [
  ['door_out', 'door_in'], ['door_in', 'ent_e'], ['door_in', 'pr_s'], ['ent_e', 'lb_w'],
  ['hub', 'lt_w'], ['hub', 'hub_n'], ['hub', 'col_mid'], ['hub_n', 'col_gap'], ['col_gap', 'col_mid'], ['col_gap', 'col_top'],
  ['col_top', 'a3'], ['a3', 'mgr_s'], ['mgr_s', 'a2'], ['a2', 'a1'],
  ['col_mid', 'pr'], ['pr', 'a5'], ['a5', 'a4'], ['pr', 'pr_s'],
  ['mgr_s', 'mgr_door'], ['mgr_door', 'mgr_in'], ['mgr_in', 'mgr_desk'],
  ['hub_n', 'meet_s'], ['meet_s', 'meet_n'], ['meet_n', 'meet_w'], ['meet_n', 'meet_e'],
  ['meet_n', 'meet_lw'], ['meet_n', 'meet_le'],
  ['lt_w', 'lt_e'], ['lt_e', 'board'], ['lt_w', 'lb_w'], ['lt_e', 'sofa_l'], ['sofa_l', 'lb_e'],
  ['lb_w', 'lb_m'], ['lb_m', 'lb_e'], ['lb_m', 'arm_e'], ['arm_e', 'cab_i'],
];

// Места сидя: pos — точка ног, dir — куда смотрит (переходы sit/stand нарисованы вбок)
const SEATS = [
  { key: 'w1', pos: [176, 584], node: 'a1', dir: 'right' },
  { key: 'w2', pos: [366, 584], node: 'a2', dir: 'right' },
  { key: 'w3', pos: [557, 584], node: 'a3', dir: 'left' },
  { key: 'w4', pos: [176, 794], node: 'a4', dir: 'right' },
  { key: 'w5', pos: [366, 794], node: 'a5', dir: 'right' },
  { key: 'mgr', pos: [240, 234], node: 'mgr_desk', dir: 'right' },
  { key: 'm1', pos: [780, 300], node: 'meet_lw', dir: 'right' },
  { key: 'm2', pos: [780, 370], node: 'meet_lw', dir: 'right' },
  { key: 'm3', pos: [780, 440], node: 'meet_lw', dir: 'right' },
  { key: 'm4', pos: [996, 300], node: 'meet_le', dir: 'left' },
  { key: 'm5', pos: [996, 370], node: 'meet_le', dir: 'left' },
  { key: 'm6', pos: [996, 440], node: 'meet_le', dir: 'left' },
];
// Лаунж: диван (2 места) и мягкое кресло — свои посадки из 08_LOUNGE_AND_SOCIAL; pos — точка подхода (entry),
// feet — где сидит. Дальше — места стоя с кофе по краю ковра
const LOUNGE = [
  { key: 'sofa1', pos: [989, 808], feet: [1031, 808], node: 'sofa_l', dir: 'left', sit: true, furniture: 'sofa' },
  { key: 'sofa2', pos: [989, 876], feet: [1031, 876], node: 'sofa_l', dir: 'left', sit: true, furniture: 'sofa' },
  { key: 'arm', pos: [870, 893], feet: [827, 893], node: 'arm_e', dir: 'right', sit: true, furniture: 'armchair' },
  { key: 'ls1', pos: [915, 690], node: 'lt_e' }, { key: 'ls2', pos: [940, 955], node: 'lb_e' },
  { key: 'ls3', pos: [830, 955], node: 'lb_m' }, { key: 'ls4', pos: [1060, 958], node: 'lb_e' },
  { key: 'ls5', pos: [700, 930], node: 'ent_e' }, { key: 'ls6', pos: [840, 690], node: 'lt_w' },
];
const MEET = [[705, 268], [705, 340], [1080, 268], [1080, 340], [705, 410], [1080, 410]];
const BOARD = [[1060, 690], [1010, 692], [1110, 692]];
const PRINTER = [[505, 892], [556, 884]];
// Порядок персонажей совпадает с исходной сценой; менеджер — за столом менеджера (место 5)
const CHAR_ORDER = ['worker_orange_yellow', 'worker_dark_purple', 'worker_brown_green', 'worker_black_charcoal',
  'worker_blond_blue', 'manager_navy', 'worker_brown_red'];
// Анимации офиса поверх фона: строка атласа, bbox в ячейке, масштаб, позиция на фоне
const PROPS = {
  tv:      { anim: 'tv-diagram',     bbox: [20, 76, 237, 181], s: 0.60, at: [449, 115] },
  printer: { anim: 'office-printer', bbox: [20, 19, 237, 236], s: 0.58, at: [427, 906] },
  plant1:  { anim: 'office-plants',  bbox: [57, 25, 201, 237], s: 0.42, at: [714, 141] },
  plant2:  { anim: 'office-plants',  bbox: [57, 25, 201, 237], s: 0.42, at: [1020, 141], offset: 900 },
};
const MEET_TV = [812, 113, 172, 58];

// Общение в простое: точки для разговора вдвоём, кулер, окна
const CHAT_SPOTS = [[655, 925], [300, 462], [440, 700], [1000, 955]];
const COOLER = [875, 668];
const KITCHEN = [514, 385];  // кухонный уголок у кулера: тумба, кофемашина, снеки
const DECOR = [               // предметы из 03_INDIVIDUAL_TRANSPARENT_ASSETS, левый верхний угол на фоне
  { key: 'cabinet', at: [466, 300], base: 357 },
  { key: 'coffee', at: [474, 222], base: 357.1 },
  { key: 'snacks', at: [522, 268], base: 357.2 },
];
const DOOR = { src: [78, 68, 100, 114], box: [540, 1006, 154, 95], zone: [617, 1040] }; // двери входа из атласа office
const WINDOWS = [[905, 962], [1015, 962]];
const REST_AT_DESK = [8, 20];   // секунд за столом между занятиями в простое
// Реплики в простое: мысли вслух (SOLO) и мини-диалоги «вопрос → ответ» (DIALOGS)
const SOLO = [
  tr("Скоро обед?", "Lunch soon?"), tr("Хочу в отпуск…", "I need a vacation…"), tr("Ох уж этот баг…", "That bug again…"), tr("Кто опять сломал develop?", "Who broke develop again?"), tr("У меня локально всё работало", "It worked on my machine"),
  tr("Это не баг, это фича", "It is a feature, not a bug"), tr("Пятница, деплой… нет уж", "Friday deploy… no thanks"), tr("Тесты напишу. Завтра", "Tests? Tomorrow."), tr("Опять мерж-конфликт", "Another merge conflict"), tr("Jenkins снова красный", "Jenkins is red again"),
  tr("Где мой кофе?", "Where is my coffee?"), tr("Работает — не трогай", "If it works, leave it alone"), tr("Кто писал этот легаси?", "Who wrote this legacy code?"), tr("Ещё одна планёрка?", "Another meeting?"), tr("Ревьюер молчит третий день", "Three days waiting for review"),
  tr("Почему в проде, а не на деве?", "Why only in production?"), tr("ИФТ опять лежит", "Integration environment is down"), tr("Обновить зависимости… или не надо", "Update dependencies… or maybe not"), tr("Кажется, я понял задачу. Или нет", "I think I get it. Maybe."),
  tr("Сначала кофе, потом код", "Coffee first, code later"), tr("Стендап через пять минут", "Standup in five minutes"), tr("Хоть бы до обеда без тикетов", "No tickets before lunch, please"), tr("Кто трогал конфиг?", "Who changed the config?"),
  tr("Миграция прошла? Тьфу-тьфу", "Migration done? Fingers crossed"), tr("Рефакторинг… когда-нибудь", "Refactoring… someday"), tr("А документацию кто напишет?", "Who will write the docs?"), tr("Сегодня без багов. Наверное", "No bugs today. Probably."),
  tr("Пойду проверю логи", "Let me check the logs"), tr("Сколько можно перезапускать пайплайн", "How many pipeline retries?"), tr("Где-то потерялась запятая", "A comma is missing somewhere"),
];
const DIALOGS = [
  [tr("Скоро обед?", "Lunch soon?"), tr("Через полчаса!", "In half an hour!")], [tr("Кто сломал develop?", "Who broke develop?"), tr("Точно не я", "Definitely not me")], [tr("Кофе будешь?", "Want a coffee?"), tr("Давай!", "Yes, please!")],
  [tr("Тесты прошли?", "Did the tests pass?"), tr("Почти все…", "Almost all…")], [tr("Как отпуск?", "How was your vacation?"), tr("Слишком быстро кончился", "Over too soon")], [tr("Видел новый эпик?", "Seen the new epic?"), tr("Лучше бы не видел", "Wish I had not")],
  [tr("Опять баг в проде", "Another production bug"), tr("Классика", "Classic")], [tr("Пойдём на обед?", "Shall we get lunch?"), tr("Только задачу закрою", "Let me finish this task")], [tr("Ревью посмотришь?", "Can you review this?"), tr("После кофе", "After coffee")],
  [tr("Jenkins опять красный", "Jenkins is red again"), tr("Перезапусти — поможет", "Try running it again")], [tr("Когда релиз?", "When is the release?"), tr("Вчера", "Yesterday")], [tr("Ты трогал конфиг?", "Did you change the config?"), tr("Он сам!", "It changed itself!")],
  [tr("Хочу в отпуск", "I need a vacation"), tr("И я. В горы", "Me too. In the mountains")], [tr("Ох уж этот баг…", "That bug again…"), tr("Дай угадаю: null?", "Let me guess: null?")], [tr("Пятничный деплой?", "Friday deploy?"), tr("Только через мой труп", "Over my dead body")],
  [tr("Стендап скоро?", "Standup soon?"), tr("Уже идёт…", "It has already started…")],
];
const VISIT_DIALOGS = [
  [tr("Как успехи?", "How is it going?"), tr("Почти готово", "Almost done")], [tr("Долго ещё?", "How much longer?"), tr("Ещё пара тестов", "Just a couple more tests")], [tr("Помочь?", "Need help?"), tr("Не отвлекай :)", "Let me focus :)")],
  [tr("Ого, сколько кода", "That is a lot of code"), tr("GigaCode старается", "GigaCode is working hard")], [tr("Обедать идёшь?", "Coming to lunch?"), tr("Только допишу", "Let me finish this")],
];
const LINES = {
  laugh: [tr("ха-ха!", "ha-ha!"), tr("ахаха", "hahaha"), tr("хех", "heh"), tr("ну ты даёшь", "you are something else")],
  out: [tr("Пойду прогуляюсь", "Going for a walk"), tr("Я за кофе", "Off for coffee"), tr("Подышу воздухом", "Getting some fresh air"), tr("Схожу на обед", "Going to lunch")],
  back: [tr("Я вернулся", "I am back"), tr("Что пропустил?", "What did I miss?")],
  cheer: [tr("Ура!", "Hooray!"), tr("Отлично!", "Great!"), tr("Красавчик!", "Nice work!"), tr("Задеплоили!", "Deployed!")],
  game: [tr("Гол!", "Goal!"), tr("Ещё катку!", "One more game!"), tr("Нечестно!", "Not fair!"), tr("Я тебя сделаю", "I will beat you"), tr("Это был лаг!", "That was lag!"), tr("Реванш!", "Rematch!"), tr("Йес!", "Yes!")],
  gameStart: [tr("Сыграем в приставку?", "Fancy a console game?"), tr("Кто на катку?", "Who wants to play?"), tr("Перерыв — FIFA?", "Break time — FIFA?")],
  pat: [[tr("Молодец, хорошо закрыл!", "Great work on that task!"), tr("Спасибо :)", "Thanks :)")], [tr("Так держать!", "Keep it up!"), tr("Стараюсь!", "Doing my best!")], [tr("Красава!", "Well done!"), tr("Да ладно…", "Oh, stop…")]],
  give: [[tr("Держи, тебе посылка", "Here is your package"), tr("О, спасибо!", "Oh, thanks!")], [tr("Это тебе с ресепшена", "This came for you at reception"), tr("Наконец-то!", "Finally!")], [tr("Твой мерч приехал", "Your merch is here"), tr("Огонь!", "Awesome!")]],
};
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
// Имя демона: задаётся в дашборде (names.json) или в конфиге (general.name); иначе — ключ проекта
// 1 234 → «1.2K», 3 400 000 → «3.4M»
function fmtTokens(n) {
  if (n == null || !isFinite(n)) return '—';
  if (n < 1000) return String(Math.round(n));
  if (n < 1e6) return (n / 1e3).toFixed(n < 1e4 ? 1 : 0).replace('.0', '') + 'K';
  return (n / 1e6).toFixed(n < 1e7 ? 2 : 1).replace(/\.?0+$/, '') + 'M';
}
// Под одним Jira-проектом может быть несколько сервисов, поэтому демона идентифицирует КЭ
const projectKey = (d) => (d.ci_id ? `${tr('КЭ', 'CI')} ${d.ci_id}` : d.project || String(d.id || '').toUpperCase());
const displayName = (d) => d.name || projectKey(d);
const rnd = (a, b) => a + Math.random() * (b - a);
function nearestNode(pos) {
  let best = null, bd = Infinity;
  for (const [k, [x, y]] of Object.entries(N)) {
    const d = Math.hypot(x - pos[0], y - pos[1]);
    if (d < bd) { bd = d; best = k; }
  }
  return best;
}
