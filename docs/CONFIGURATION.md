# Справочник конфигурации

[Главная](../README.md) · [Runbook](RUNBOOK.md) · [Жизненный цикл задачи](WORKFLOW.md)

Один JSON-файл в `config/` задаёт одного демона. Полный пример: [один репозиторий](../config/example.json.sample) или [несколько сервисов](../config/example-services.json.sample). В таблицах — ключи JSON, значения по умолчанию и точные имена переменных окружения. Служебные поля с `_` не являются настройками пользователя.

## Приоритеты, типы и проверка

Решение в UI (**Включить / Выключить**) главнее всех источников ниже. При **По конфигу** используется порядок: переменная с префиксом проекта (`HRPPA_BASE_BRANCH`) → общая переменная (`BASE_BRANCH`) →
конфиг сервиса → общий JSON-конфиг → значение по умолчанию. Пустые ENV игнорируются. `tmp/.env`
заполняет только отсутствующие переменные, уже заданное окружение процесса главнее.
Префикс берётся из `jira.project` в JSON (также проверяется вариант в верхнем регистре).

`jira.project` обязательно задаётся в JSON: он определяет идентификатор инстанса и префикс ENV.
`JIRA_PROJECT` меняет проект запросов Jira, но не переименовывает файлы памяти и логов.
`general.ci_id` задаётся только в JSON; при его наличии ключ инстанса — `ci<номер без ведущих нулей>`.
Разным демонам нужны разные ключи инстансов и отдельные рабочие клоны.

Типы: переключатели в JSON — `true`/`false`, интервалы и лимиты — числа, списки — массивы строк.
В ENV переключатели принимают `true/false`, `1/0`, `yes/no`, `on/off`, `да/нет`;
списки, читаемые как списки параметров, разделяются запятыми (включая `*_EXTRA_ARGS`: `--model,GigaChat-2-Max`).
`general.gigacode_chats_dir` — путь или JSON-массив путей; в ENV только один путь, без разделения запятыми.
`memory.verify_commands` — вложенный массив аргументов, доступен только в JSON.
`general.enabled` учитывает именно JSON `false` и только при запуске через супервизор.
Большинство разделов не отклоняют неизвестные ключи JSON: опечатка может остаться незамеченной;
сверяйте названия с таблицами. Раздел `prompts` проверяется строго: неизвестные поля и этапы отклоняются.

Переменные запуска, не поля JSON: `CONFIG_PATH` — конфиг одного демона (явный аргумент пути главнее),
`ENV_FILE` — другой файл вместо `tmp/.env`, `DRY_RUN=true` — пробный запуск,
`ARTEL_STOP_TIMEOUT` — ожидание остановки супервизором, по умолчанию 120 секунд.
Переменные `ARTEL_RESTORE_ACTIVE` и `ARTEL_SUPERVISED` служебные — вручную их не задают.
Изменённый конфиг и ENV применяются после перезапуска процесса; предварительно выполните
`python3 jira_to_gigacode.py config/hrppa.json --check`.

## Общие настройки

### Jira

| Ключ | По умолчанию | Назначение | Env |
|---|---|---|---|
| `jira.url` | не задан | URL Jira; обязателен при включённой Jira | `JIRA_URL` |
| `jira.token` | не задан | Bearer-токен Jira; обязателен при включённой Jira | `JIRA_TOKEN` |
| `jira.project` | не задан | Ключ проекта; обязательно задаётся в JSON даже при выключенной Jira | `JIRA_PROJECT` для запросов |
| `jira.status_analysis` | `[]` | Статусы задач на реализацию; обязательны при включённой Jira | `JIRA_STATUS_ANALYSIS` |
| `jira.status_ready` | `[]` | Целевые статусы после сдачи; обязательны при включённой Jira | `JIRA_STATUS_READY` |
| `jira.epic_name` | пустая строка | Название эпика для фильтра реализации; без пары полей фильтр не применяется | `JIRA_EPIC_NAME` |
| `jira.epic_link_field` | пустая строка | Поле связи с эпиком | `JIRA_EPIC_LINK_FIELD` |
| `jira.ci_field` | не задан | Числовой ID поля КЭ; используется с `general.ci_id` | `JIRA_CI_FIELD` |
| `jira.assignee` | не задан | Исполнитель для фильтра реализации; не ограничивает исследование | `JIRA_ASSIGNEE` |
| `jira.result_comments` | `true` | Отчёты и сообщения о решениях/блокировках в Jira | `JIRA_RESULT_COMMENTS` |

### Демон и репозиторий

| Ключ | По умолчанию | Назначение | Env |
|---|---|---|---|
| `general.enabled` | включён | Только JSON `false` исключает конфиг из запуска супервизором | — |
| `general.name` | не задан | Имя демона; имя из дашборда главнее | `DAEMON_NAME` |
| `general.ci_id` | не задан | Идентификатор КЭ; задаётся в JSON, определяет ключ инстанса | — |
| `general.repo_path` | текущая папка процесса | Рабочий клон одного репозитория; задайте явно или используйте `services[]` | `REPO_PATH` |
| `general.base_branch` | `develop` | Ветка origin для обычных задач и возврата клона | `BASE_BRANCH` |
| `general.base_branch_create_from` | `master` | База создания отсутствующей ветки из комментария Jira | `BASE_BRANCH_CREATE_FROM` |
| `general.branch_prefix` | `feature/ai_team` | Ветка задачи: `<prefix>/<KEY>` | `BRANCH_PREFIX` |
| `general.poll_interval_seconds` | `600` | Пауза между проходами поиска Jira, секунд | `POLL_INTERVAL` |
| `general.retry_cooldown_seconds` | `3600` | Пауза после двух неудач по задаче; BLOCKED не расходует технические ретраи | `RETRY_COOLDOWN_SECONDS` |
| `general.gigacode_path` | `gigacode` | Исполняемый файл CLI; должен быть доступен пользователю демона | `GIGACODE_PATH` |
| `general.gigacode_timeout_seconds` | `3600` | Таймаут основной генерации, секунд | `GIGACODE_TIMEOUT` |
| `general.require_success_marker` | `false` | Требовать последнюю строку `CODE_GENERATION_SUCCESS`; рекомендуется `true` | `REQUIRE_SUCCESS_MARKER` |
| `general.temp_files` | встроенный набор | Шаблоны исключаемых временных файлов: `.gigacode`, `.gigacode/*`, `tmp*.py`, `*_tmp.py`, `tmp_*.py`; непустой список заменяет набор, `[]` возвращает встроенный | `TEMP_FILES` |
| `general.compare_url` | не задан | Ссылка на diff в отчёте: `{branch}`, `{base}` без `origin/`, `{issue}` | `COMPARE_URL` |
| `general.service` | не задан | Имя одного сервиса для памяти и группировки; маршрутизация заменяет на `services[].name` | — |
| `general.role` | определяется по маркерам | `backend`, `frontend` или `other`; роль одного репозитория | — |
| `general.office_group` | значение `general.service` | Постоянная группа офиса внутри проекта; до 10 мест на комнату | — |
| `general.character` | автоматический выбор | ID персонажа; выбор в дашборде главнее | — |
| `general.tokens_regex` | не задан | Regex расхода токенов в выводе CLI | `GIGACODE_TOKENS_REGEX` |
| `general.gigacode_chats_dir` | каталоги CLI в домашней папке | Путь или JSON-массив путей записей чатов; ENV принимает один путь | `GIGACODE_CHATS_DIR` |

### Jenkins

| Ключ | По умолчанию | Назначение | Env |
|---|---|---|---|
| `jenkins.url` | пустая строка | Адрес Jenkins | `JENKINS_URL` |
| `jenkins.user` | пустая строка | Пользователь API | `JENKINS_USER` |
| `jenkins.token` | пустая строка | Токен пользователя | `JENKINS_TOKEN` |
| `jenkins.job_name` | пустая строка | Путь job, допускает папки | `JENKINS_JOB` |

## Переключатели

| Ключ | По умолчанию | Env |
|---|---|---|
| `jira.enabled` | `true` | `JIRA_ENABLED` |
| `jenkins.enabled` | `true` | `JENKINS_ENABLED` |
| `requirements.enabled` | `true` | `REQUIREMENTS_ENABLED` |
| `dependencies.enabled` | `true` | `DEPENDENCIES_ENABLED` |

У остальных функций ключ находится в своём разделе: `bitbucket.enabled`, `memory.enabled`,
`memory.auto_append`, `memory.auto_verify`, `review.enabled`, `explore.enabled`,
`explore.learn`, `retro.enabled`. Выбор UI хранится отдельно от JSON и применяется
на следующей безопасной границе работы. См. [переключатели в дашборде](DASHBOARD.md).

## dependencies

| Ключ | По умолчанию | Env |
|---|---|---|
| `dependencies.enabled` | `true`; также переключатель в панели демона | `DEPENDENCIES_ENABLED` |
| `dependencies.external_ready_label` | `backend-ready`; точное совпадение, латиница/цифры/`_`/`-`, до 100 символов | `DEPENDENCIES_EXTERNAL_READY_LABEL` |
| `dependencies.ready_statuses` | наследует `jira.status_ready`; явный `[]` отключает готовность по имени статуса | `DEPENDENCIES_READY_STATUSES` |
| `dependencies.accept_done` | `false`; дополнительно разрешать категорию Jira `done` | `DEPENDENCIES_ACCEPT_DONE` |
| `dependencies.allow_code_branch` | `true`; ветка Development с непустым Git diff разрешает фронтенд своего КЭ | `DEPENDENCIES_ALLOW_CODE_BRANCH` |
| `dependencies.dev_application_type` | `stash` для Bitbucket Server/Data Center | `DEPENDENCIES_DEV_APPLICATION_TYPE` |
| `dependencies.dev_data_type` | `pullrequest`; допустимо также `branch` | `DEPENDENCIES_DEV_DATA_TYPE` |
| `dependencies.link_types` | `[]` — все типы; иначе список точных имён типов Jira без учёта регистра | `DEPENDENCIES_LINK_TYPES` |
| `dependencies.backend_markers` | `back, backend, бек, бэк, beck, бэкенд, бекенд`; список заменяет встроенный набор | `DEPENDENCIES_BACKEND_MARKERS` |
| `dependencies.frontend_markers` | `front, frontend, web, фронт, фронтенд, веб, mobile, ios, android` | `DEPENDENCIES_FRONTEND_MARKERS` |
| `dependencies.max_links` | `50` (1–100); превышение блокирует задачу, не обрезает зависимости молча | `DEPENDENCIES_MAX_LINKS` |

## review

| Ключ `review.*` | По умолчанию | Назначение | Env |
|---|---|---|---|
| `review.enabled` | `true` | выключить ревью — `false` | `REVIEW_ENABLED` |
| `review.gigacode_path`, `review.extra_args` | как у генерации, `[]` | CLI и флаги ревьюера — например другая модель | `REVIEW_GIGACODE_PATH`, `REVIEW_EXTRA_ARGS` |
| `review.prompt_prefix` | — | начало команды, например `"вызови суб агента /code-reviewer "` | `REVIEW_PROMPT_PREFIX` |
| `review.max_rework_rounds` | `1` | сколько раз дорабатывать по замечаниям в одном прогоне | `REVIEW_MAX_REWORK_ROUNDS` |
| `review.block_on_changes` | `true` | с замечаниями задачу не переводить | `REVIEW_BLOCK_ON_CHANGES` |
| `review.on_no_verdict` | `"pass"` | ревьюер не дал вердикта: `"pass"` — пропустить, `"block"` — остановить | `REVIEW_ON_NO_VERDICT` |
| `review.timeout_seconds`, `review.max_diff_chars` | `1200`, `40000` | | `REVIEW_TIMEOUT`, `REVIEW_MAX_DIFF_CHARS` |

## memory

| Ключ `memory.*` | По умолчанию | Назначение | Env |
|---|---|---|---|
| `memory.enabled` | `true` | использовать память | `MEMORY_ENABLED` |
| `memory.auto_append` | `true` | собирать кандидаты; `false` — не собирать новые наблюдения | `MEMORY_AUTO_APPEND` |
| `memory.path` | `memory/{key}.md` | базовый путь; `{key}` — КЭ/проект с суффиксом сервиса | `MEMORY_PATH` |
| `memory.max_chars` | `6000` | бюджет содержимого памяти в запросе, без служебной обёртки | `MEMORY_MAX_CHARS` |
| `memory.max_candidates` | `100` | максимум кандидатов; отдельно столько же отклонённых записей | `MEMORY_MAX_CANDIDATES` |
| `memory.max_confirmed` | `40` | максимум подтверждённых записей | `MEMORY_MAX_CONFIRMED` |
| `memory.candidate_days` | `30` | срок хранения кандидатов и отклонённых записей | `MEMORY_CANDIDATE_DAYS` |
| `memory.review_after_days` | `90` | срок до повторного подтверждения опыта | `MEMORY_REVIEW_AFTER_DAYS` |
| `memory.history_max_bytes` | `1000000` | размер журнала истории (минимум 16384 байт); хранится один ротированный файл | `MEMORY_HISTORY_MAX_BYTES` |

| Ключ `memory.*` | По умолчанию | Назначение | Env |
|---|---|---|---|
| `memory.auto_verify` | `true` | автоматическая проверка существующих кандидатов | `MEMORY_AUTO_VERIFY` |
| `memory.verify_every_minutes` | `60` | интервал между проверками в простое | `MEMORY_VERIFY_EVERY_MINUTES` |
| `memory.verify_retry_hours` | `24` | пауза после технической ошибки или прерванного прогона | `MEMORY_VERIFY_RETRY_HOURS` |
| `memory.verify_base` | `origin/<general.base_branch>` | базовая ветка для проверки | `MEMORY_VERIFY_BASE` |
| `memory.verify_timeout` | `300` | таймаут каждого из двух вызовов проверяющего, секунд | `MEMORY_VERIFY_TIMEOUT` |
| `memory.verify_test_timeout` | `300` | таймаут каждой тестовой команды, секунд | `MEMORY_VERIFY_TEST_TIMEOUT` |
| `memory.verify_commands` | авто | список argv-команд тестов; не shell-строки, максимум 5 | — |
| `memory.verify_gigacode_path`, `memory.verify_extra_args` | общий CLI, `[]` | CLI и параметры проверяющего | `MEMORY_VERIFY_GIGACODE_PATH`, `MEMORY_VERIFY_EXTRA_ARGS` |

## bitbucket

| Ключ `bitbucket.*` | По умолчанию | Назначение | Env |
|---|---|---|---|
| `bitbucket.enabled` | `false` | разрешить фоновую обработку PR | `BITBUCKET_ENABLED` |
| `bitbucket.url` | — | HTTPS-адрес Server / Data Center | `BITBUCKET_URL` |
| `bitbucket.project` | — | ключ проекта Bitbucket, не Jira | `BITBUCKET_PROJECT` |
| `bitbucket.repo` | — | slug репозитория | `BITBUCKET_REPO` |
| `bitbucket.token` | — | Bearer PAT технического пользователя | `BITBUCKET_TOKEN` |
| `bitbucket.bot_user` | — | логин автора ответов Артели | `BITBUCKET_BOT_USER` |
| `bitbucket.verify_ssl` | `false`; при заданном `ca_file` — `true` | проверять сертификат и имя хоста; `true` без `ca_file` использует системные CA | `BITBUCKET_VERIFY_SSL` |
| `bitbucket.ca_file` | не задан | необязательный PEM доверенного CA; включает проверку, если `verify_ssl` не задан явно | `BITBUCKET_CA_FILE` |
| `bitbucket.http_timeout` | `30` | таймаут одного HTTP-запроса, секунд | `BITBUCKET_HTTP_TIMEOUT` |
| `bitbucket.poll_interval_seconds` | `600` | минимальный интервал проверки, не менее 60 секунд; фактическая частота зависит от общего цикла демона | `BITBUCKET_POLL_INTERVAL` |
| `bitbucket.batch_comments` | `true` | все новые замечания PR в одном проходе, отдельные ответы; `false` — прежняя обработка по обсуждениям | `BITBUCKET_BATCH_COMMENTS` |
| `bitbucket.max_per_cycle` | `1` | максимум PR за проход для сервиса; при `batch_comments: false` — максимум обсуждений | `BITBUCKET_MAX_PER_CYCLE` |
| `bitbucket.max_tasks_per_cycle` | `20` | максимум сданных задач для поиска PR за проход; обход по кругу | `BITBUCKET_MAX_TASKS_PER_CYCLE` |
| `bitbucket.max_age_days` | `90` | возраст записи о сдаче задачи, в пределах которого ищутся PR | `BITBUCKET_MAX_AGE_DAYS` |
| `bitbucket.gigacode_path` | общий CLI | исполнитель анализа, исправления и повторной проверки | `BITBUCKET_GIGACODE_PATH` |
| `bitbucket.extra_args` | `[]` | параметры CLI, например выбор модели | `BITBUCKET_EXTRA_ARGS` |
| `bitbucket.timeout_seconds` | `1200` | таймаут каждого вызова CLI, секунд | `BITBUCKET_TIMEOUT` |
| `bitbucket.test_commands` | авто | массив argv-команд, максимум 5; не shell-строки. Автовыбор как при проверке памяти. Явный `[]` запрещает автоматическую публикацию исправления | только JSON |
| `bitbucket.test_timeout` | `300` | таймаут каждой команды тестов, секунд | `BITBUCKET_TEST_TIMEOUT` |

## explore

| Ключ `explore.*` | По умолчанию | Назначение | Env |
|---|---|---|---|
| `explore.enabled` | `true` | разрешить исследование (также нужны `statuses`) | `EXPLORE_ENABLED` |
| `explore.statuses` | `[]` | статусы бэклога и возврата при BLOCKED; без них исследование выключено и автоматический возврат статуса невозможен | `EXPLORE_STATUSES` |
| `explore.prompt_template` | `/opsx:explore …` | своя команда: `{key}` `{summary}` `{description}` `{project}` `{repo}` `{base}` `{memory}` | `EXPLORE_PROMPT_TEMPLATE` |
| `explore.base` | `origin/<general.base_branch>` | от какой ветки делать копию | `EXPLORE_BASE` |
| `explore.max_per_cycle` | `1` | сколько задач изучать за один проход простоя | `EXPLORE_MAX_PER_CYCLE` |
| `explore.max_scan` | `200` | сколько задач бэклога просматривать за проход в поисках неизученной | `EXPLORE_MAX_SCAN` |
| `explore.min_hours_between`, `explore.reexplore_on_update` | `336`, `true` | Минимум 14 дней между исследованиями одной задачи; меньшие значения в конфиге или окружении повышаются до 336 часов | `EXPLORE_MIN_HOURS`, `EXPLORE_REEXPLORE` |
| `explore.learn` | `false` | сохранять кандидаты из исследования (по умолчанию исследование память только читает) | `EXPLORE_LEARN` |
| `explore.timeout_seconds`, `explore.gigacode_path`, `explore.extra_args` | `900`, общий CLI, `[]` | таймаут и команда исследователя | `EXPLORE_TIMEOUT`, `EXPLORE_GIGACODE_PATH`, `EXPLORE_EXTRA_ARGS` |

## retro

| Ключ `retro.*` | По умолчанию | Назначение | Env |
|---|---|---|---|
| `retro.enabled` | `true` | | `RETRO_ENABLED` |
| `retro.window` | `"01:00-05:00"` | ночное окно по локальному времени миника; может переходить через полночь (`"23:00-03:00"`) | `RETRO_WINDOW` |
| `retro.every_days` | `7` | как часто | `RETRO_EVERY_DAYS` |
| `retro.min_age_days`, `retro.max_age_days` | `2`, `30` | с какого возраста задачу разбирать и сколько ждать слияния | `RETRO_MIN_AGE_DAYS`, `RETRO_MAX_AGE_DAYS` |
| `retro.max_tasks` | `10` | задач за одну ретроспективу (самые старые первыми) | `RETRO_MAX_TASKS` |
| `retro.timeout_seconds`, `retro.max_diff_chars` | `1800`, `12000` | `max_diff_chars` — на одну задачу | `RETRO_TIMEOUT`, `RETRO_MAX_DIFF_CHARS` |
| `retro.gigacode_path`, `retro.extra_args` | общий CLI, `[]` | например более сильная модель для разбора | `RETRO_GIGACODE_PATH`, `RETRO_EXTRA_ARGS` |

## logs

| Ключ `logs.*` | По умолчанию | Переменная | |
|---|---|---|---|
| `logs.max_mb` | `20` | `LOG_MAX_MB` | размер, после которого лог уходит в архив; `0` — не поворачивать |
| `logs.cli_keep_days` | `14` | `LOG_CLI_KEEP_DAYS` | сколько дней логи GigaCode лежат в системной временной папке; `0` — не архивировать |

## Промпты и специализация демона

Раздел `prompts` задаётся на верхнем уровне JSON и действует для всех сервисов демона.
Сохранённые настройки вкладки **Промпты** главнее JSON. **Из конфига → Сохранить** убирает
UI-переопределение. ENV-эквивалентов у этих настроек нет.

| Ключ | По умолчанию | Назначение |
|---|---|---|
| `prompts.profile` | `developer` | `developer`, `testing` или `custom`; тестировщик составляет сценарии и добавляет/запускает автотесты |
| `prompts.subagent` | `jira-to-deploy-orchestrator` | Имя установленного субагента для выполнения и доработки: 1–80 латинских букв, цифр, `_` и `-`, начинается с буквы, без `/` |
| `prompts.instructions` | пустая строка | Общие дополнительные инструкции для всех этапов, до 6000 символов |
| `prompts.stages.generation` | пустая строка | Выполнение задачи и ручная переделка |
| `prompts.stages.review` | пустая строка | Независимое ревью |
| `prompts.stages.rework` | пустая строка | Доработка после ревью |
| `prompts.stages.explore` | пустая строка | Исследование бэклога |
| `prompts.stages.pr_review` | пустая строка | Замечания Bitbucket и ответы |
| `prompts.stages.retro` | пустая строка | Ретроспектива |
| `prompts.stages.memory` | пустая строка | Проверка кандидатов памяти |

У каждого поля этапа собственный лимит 6000 символов. Это текст, дополняющий запрос
GigaCode, а не shell-команда и не замена обязательного протокола Артели. Настройки UI
хранятся в `logs/{instance}-prompts.json`; применяются между задачами и фоновыми операциями.
Изменение поведения требует подтверждения старого повтора. [Примеры и порядок работы](PROMPTS.md).

## Сервисы и базовые ветки

У сервисов не произвольные JSON-overrides. Поддерживаются поля ниже; остальные разделы действуют для всего демона. Подробные примеры и маршрутизация — [в жизненном цикле задачи](WORKFLOW.md).

| Настройка | У сервиса задана | У сервиса не задана |
|---|---|---|
| `name`, `repo_path` | обязательны; имя сервиса и путь его клона | запись без них игнорируется |
| `labels`, `keywords` | массивы маркеров маршрутизации | встроенные слова по имени сервиса |
| `role` | роль задачи сервиса: `backend`, `frontend` или `other` | определяется по имени сервиса, лейблам и словам в названии задачи |
| `base_branch`, `base_branch_create_from`, `branch_prefix`, `compare_url` | заменяет общую из `general` | берётся общая |
| `jenkins`, `review`, `memory`, `bitbucket` | **сливается** с общим разделом: ключи сервиса главнее, остальные — из общего | берётся общий раздел целиком |

Обычно в общий `jenkins` кладут `url` и `user` (токен — в `tmp/.env`), а у сервиса — только свой
`job_name`. **Переменные окружения главнее и общих настроек, и настроек сервиса:** `REPO_PATH`,
`JENKINS_JOB`, `COMPARE_URL`, `BRANCH_PREFIX`, `BASE_BRANCH`, `BASE_BRANCH_CREATE_FROM` (в том числе с префиксом проекта, `HRPPA_JENKINS_JOB`)
при сервисах дали бы всем одно значение — проверка окружения при старте предупредит, если такая
переменная перекрывает настройку сервиса.

Сервис задачи демон определяет по **лейблам** (точное совпадение, без учёта регистра) и **словам в
названии** (целые слова: «[Бек] Добавить поле», «WEB: кнопка»; «webhook» — не «web»):

- подошёл ровно один сервис — задача делается в его репозитории, с его джобой Jenkins;
- не подошёл ни один или подошли несколько — демон задачу **не берёт** и один раз пишет в неё
  комментарий: какие лейблы и слова он понимает, или просьбу разбить задачу на несколько. Как только
  название или лейблы поменяются, задача проверяется снова и, если сервис стал понятен, берётся в работу.

Другие разделы внутри `services[]` не накладываются на общие настройки: поддерживаются только поля из таблицы.

Память сервисов разделяется автоматически: `memory/{инстанс}-{сервис}.md`. Вложенные настройки `jira`, `explore`, `retro`, `dependencies`, `requirements`, `prompts` внутри `services[]` не поддерживаются.

## Дополнительные правила

- `general.base_branch` по умолчанию `develop`, `base_branch_create_from` — `master`. Явный пользовательский маркер `branch:` / `ветка:` в Jira имеет приоритет. Для `main` задайте обе ветки. [Подробности](WORKFLOW.md#базовая-ветка).
- `explore.base` и `memory.verify_base` принимают Git ref, например `origin/main`.
- `memory.verify_commands` и `bitbucket.test_commands` — массивы argv-массивов (до 5), не shell-строки. Команды выполняются в worktree; укажите команды, подходящие вашей ОС. Пустой список запрещает тестовые запуски, а для PR также автоматический push.
- Jira и Bitbucket работают через Python REST-клиенты без MCP. Jira не имеет настройки CA/проверки TLS в JSON. У Bitbucket проверка TLS по умолчанию выключена; `verify_ssl: true` использует системные CA, `ca_file` задаёт свой PEM.
- Jenkins запускается только по лейблу `jenkins_{стенд}[_migration]`. Имена параметров `refName`, `filter`, `MIGRATION` и встроенное соответствие стендов заданы в `jira_gigacode/jenkins.py`, отдельными ключами JSON не настраиваются.
- У `requirements` единственный пользовательский ключ — `enabled`. Причина и задача переделки задаются в дашборде, а не в конфиге.

## Дашборд и обновление

Параметры HTTP-сервера (`--host`, `--port`, `--logs`, `--assets`, `--no-control` и пути файлов) задаются аргументами запуска: [справочник дашборда](DASHBOARD.md). У updater свой CLI: [обновление и резервные копии](../UPDATE.md). Они не являются полями JSON-конфига демона.
