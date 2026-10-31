// Недостающие имена в from amxpy import ...: правка одной строки, без зависимости от VS Code
'use strict';

const SINGLE = /^from amxpy import ([^()#\n]+?)\s*(#.*)?$/;

// Какие имена amxpy использует заготовка
function neededNames(snippet) {
  const names = [];
  if (/\bPlayer\b/.test(snippet)) names.push('Player');
  if (/\bAccess\./.test(snippet)) names.push('Access');
  if (/(^|[^.\w])events\./m.test(snippet)) names.push('events');
  return names;
}

// Строка, после которой ставить новый импорт: конец блока импортов в начале файла
function importLine(lines) {
  let last = -1;
  let i = 0;
  if (/^[rbuRBU]?("""|''')/.test(lines[0] || '')) { // докстринг модуля
    const quote = lines[0].match(/("""|''')/)[1];
    i = lines[0].indexOf(quote, lines[0].indexOf(quote) + 3) >= 0 ? 1 : lines.findIndex((l, n) => n > 0 && l.includes(quote)) + 1;
    last = i - 1;
  }
  for (; i < lines.length; i++) {
    const line = lines[i];
    if (/^(import|from)\s/.test(line)) {
      if (line.includes('(') && !line.includes(')')) while (i < lines.length && !lines[i].includes(')')) i++;
      last = i;
    } else if (line.trim() && !line.startsWith('#')) break;
  }
  return last + 1;
}

/**
 * Правка импорта: {line, replace, text} — заменить строку line или вставить text перед ней; null — всё есть.
 * @param {string} source текст файла
 * @param {string[]} names нужные имена из amxpy
 */
function importEdit(source, names) {
  const lines = source.split(/\r?\n/);
  const single = lines.findIndex((l) => SINGLE.test(l));
  if (single >= 0) {
    const [, list, comment] = SINGLE.exec(lines[single]);
    const parts = list.split(',').map((p) => p.trim()).filter(Boolean);
    const bound = new Set(parts.map((p) => p.split(/\s+as\s+/).pop()));
    const missing = names.filter((n) => !bound.has(n));
    if (!missing.length) return null;
    const all = [...parts, ...missing].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    return { line: single, replace: true, text: `from amxpy import ${all.join(', ')}${comment ? `  ${comment}` : ''}` };
  }
  const bound = new Set();
  for (const m of source.matchAll(/^from amxpy import \(([^)]*)\)/gm)) {
    m[1].split(',').map((p) => p.replace(/#.*$/gm, '').trim()).filter(Boolean)
      .forEach((p) => bound.add(p.split(/\s+as\s+/).pop()));
  }
  const missing = names.filter((n) => !bound.has(n));
  if (!missing.length) return null;
  return { line: importLine(lines), replace: false, text: `from amxpy import ${missing.sort().join(', ')}` };
}

module.exports = { neededNames, importEdit };
