// Цвета HUD, имена cvar'ов и предпросмотр цветного текста — без зависимости от VS Code
'use strict';

const COLOR = /\b(color2?)\s*=\s*\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*(\d{1,3})\s*)?\)/g;

/** Кортежи color=(r, g, b[, a]) в тексте: [{start, end, rgba}] — start/end охватывают скобки. */
function findColors(text) {
  const out = [];
  for (const m of text.matchAll(COLOR)) {
    const [r, g, b] = [m[2], m[3], m[4]].map(Number);
    const a = m[5] === undefined ? 255 : Number(m[5]);
    if ([r, g, b, a].some((v) => v > 255)) continue;
    const open = m.index + m[0].indexOf('(');
    out.push({ start: open, end: m.index + m[0].length, rgba: [r, g, b, a], alpha: m[5] !== undefined });
  }
  return out;
}

/** Текст кортежа для выбранного в палитре цвета (компоненты 0–1). */
function colorText(red, green, blue, alpha, withAlpha) {
  const c = [red, green, blue].map((v) => Math.round(v * 255));
  if (withAlpha || alpha < 1) c.push(Math.round(alpha * 255));
  return `(${c.join(', ')})`;
}

/** Полные имена cvar'ов в классах Config: [{line, name}] — подсказка в конце строки. */
function cvarHints(text) {
  const lines = text.split(/\r?\n/);
  const out = [];
  let prefix = null;
  let indent = -1;
  lines.forEach((line, i) => {
    const cls = /^(\s*)class\s+\w+\s*\(([^)]*)\)\s*:/.exec(line);
    if (cls) {
      const isConfig = /(^|[\s,.])Config\b/.test(cls[2]);
      prefix = isConfig ? (/prefix\s*=\s*["']([^"']*)["']/.exec(cls[2]) || [, ''])[1] : null;
      indent = cls[1].length;
      return;
    }
    if (prefix === null || !line.trim()) return;
    if (line.length - line.trimStart().length <= indent) { prefix = null; return; }
    const field = /^\s*([A-Za-z_]\w*)\s*:[^=]+=\s*(?:amxpy\.)?cvar\(/.exec(line);
    if (!field) return;
    const explicit = /\bname\s*=\s*["']([^"']+)["']/.exec(line);
    out.push({ line: i, name: explicit ? explicit[1] : prefix + field[1] });
  });
  return out;
}

const CHAT = { g: '#7dd35b', t: '#ff5c5c', y: '#ffc04d', n: '#ffc04d' };
const MENU = { y: '#ffd42a', w: '#ffffff', r: '#ff3b3b', d: '#8a8a8a' };
const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Строковый литерал строки, в котором стоит курсор: {start, end, text} или null. */
function stringAt(line, character) {
  const re = /[rRfFbBuU]{0,2}("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
  for (const m of line.matchAll(re)) {
    if (character >= m.index && character <= m.index + m[0].length) {
      return { start: m.index, end: m.index + m[0].length, text: m[1].slice(1, -1) };
    }
  }
  return null;
}

/**
 * HTML-предпросмотр текста с тегами цвета: чат (!g !t !y) или меню (!y !w !r !d !R).
 * @returns {string|null} markdown с <span style="color">, null — тегов нет
 */
function colorPreview(line, character) {
  const lit = stringAt(line, character);
  if (!lit || !/![gtynwrdR]/.test(lit.text)) return null;
  const menu = /\bMenu(\.ask)?\(|\.item\(|\.add\(/.test(line) && !/\.print\(/.test(line);
  const palette = menu ? MENU : CHAT;
  const tags = menu ? /!([ywrdR])/g : /!([gtyn])/g;
  let color = menu ? MENU.w : CHAT.y;
  let html = '';
  let last = 0;
  const flush = (to) => {
    const part = lit.text.slice(last, to).replace(/\\n/g, '\n');
    if (part) html += `<span style="color:${color};">${escapeHtml(part)}</span>`;
  };
  for (const m of lit.text.matchAll(tags)) {
    flush(m.index);
    if (m[1] === 'R') html += '<span style="color:#8a8a8a;"> ⇥ </span>';
    else color = palette[m[1]];
    last = m.index + m[0].length;
  }
  flush(lit.text.length);
  if (!html) return null;
  const legend = menu
    ? '`!y` жёлтый · `!w` белый · `!r` красный · `!d` серый · `!R` — к правому краю'
    : '`!g` зелёный · `!t` цвет команды (красный у T, синий у CT) · `!y` обычный';
  return `**${menu ? 'Меню' : 'Чат'}: как увидит игрок**\n\n${html}\n\n---\n${legend}`;
}

module.exports = { findColors, colorText, cvarHints, stringAt, colorPreview };
