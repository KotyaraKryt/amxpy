// Где курсор относительно amxx.call("имя", ...): для автодополнения, наведения и подсказки параметров
'use strict';

const CALL = /\bamxx\.call(?:_float)?\(\s*$/;

/** Набирается имя натива: часть имени или null (`amxx.call("get_us|`) */
function completionPrefix(before) {
  const m = /\bamxx\.call(?:_float)?\(\s*["'](\w*)$/.exec(before);
  return m ? m[1] : null;
}

/** Имя натива под курсором в первой строке-аргументе amxx.call: {name, start, end} или null */
function nativeAt(line, character) {
  const re = /\bamxx\.call(?:_float)?\(\s*(["'])(\w+)\1/g;
  for (const m of line.matchAll(re)) {
    const start = m.index + m[0].length - m[2].length - 1;
    const end = start + m[2].length;
    if (character >= start && character <= end) return { name: m[2], start, end };
  }
  return null;
}

/**
 * Внутри аргументов amxx.call(...): {name, argIndex} — номер параметра натива (с 0) или -1 на имени.
 * @param {string} before текст до курсора (можно несколько строк)
 */
function callContext(before) {
  // ищем с конца незакрытую «amxx.call(»
  let depth = 0;
  let quote = null;
  for (let i = before.length - 1; i >= 0; i--) {
    const ch = before[i];
    if (quote) {
      if (ch === quote && before[i - 1] !== '\\') quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === ')' || ch === ']' || ch === '}') depth++;
    else if (ch === '(' || ch === '[' || ch === '{') {
      if (depth > 0) {
        depth--;
        continue;
      }
      if (ch !== '(' || !CALL.test(before.slice(0, i + 1))) return null;
      const args = before.slice(i + 1);
      const name = /^\s*(["'])(\w+)\1/.exec(args);
      let commas = 0;
      let d = 0;
      let q = null;
      for (let j = 0; j < args.length; j++) {
        const c = args[j];
        if (q) {
          if (c === '\\') j++;
          else if (c === q) q = null;
        } else if (c === '"' || c === "'") q = c;
        else if ('([{'.includes(c)) d++;
        else if (')]}'.includes(c)) d--;
        else if (c === ',' && d === 0) commas++;
      }
      return name ? { name: name[2], argIndex: commas - 1 } : null;
    }
  }
  return null;
}

module.exports = { completionPrefix, nativeAt, callContext };
