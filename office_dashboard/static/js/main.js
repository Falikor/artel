'use strict';
/* Старт: загрузка ассетов и подключение к серверу. Последний скрипт страницы. */

boot().catch((e) => { const n = $('notice'); n.hidden = false; n.textContent = e.message; console.error(e); });
