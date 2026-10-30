'use strict';
/* Утилиты: $, экранирование, время сервера, загрузка картинок, localStorage, поиск пути по графу. */

// ------------------------------------------------------------------ утилиты
const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const median = (arr) => { const s = [...arr].sort((a, b) => a - b); return s.length ? s[s.length >> 1] : 0; };
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
let clockSkew = 0; // серверное время − локальное, сек
const nowSec = () => Date.now() / 1000 + clockSkew;
function fmtDur(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}
function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Не загрузилось: ' + src));
    img.src = src;
  });
}
const storage = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* приватный режим */ } },
};

// Кратчайший путь по графу (Дейкстра — узлов мало)
const ADJ = {};
for (const [a, b] of EDGES) {
  const d = Math.hypot(N[a][0] - N[b][0], N[a][1] - N[b][1]);
  (ADJ[a] ||= []).push([b, d]); (ADJ[b] ||= []).push([a, d]);
}
function route(from, to) {
  if (from === to) return [from];
  const dist = { [from]: 0 }, prev = {}, open = new Set([from]);
  while (open.size) {
    let u = null;
    for (const n of open) if (u === null || dist[n] < dist[u]) u = n;
    open.delete(u);
    if (u === to) break;
    for (const [v, w] of ADJ[u] || []) {
      const nd = dist[u] + w;
      if (dist[v] === undefined || nd < dist[v]) { dist[v] = nd; prev[v] = u; open.add(v); }
    }
  }
  const path = [to];
  while (path[0] !== from) { const p = prev[path[0]]; if (p === undefined) return [to]; path.unshift(p); }
  return path;
}
