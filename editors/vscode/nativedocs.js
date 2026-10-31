// Подсказки к amxx.call: markdown натива и готовый пример вызова из Python
'use strict';

const { signature } = require('./incparse');

const PLAYER = /^(index|id|player|client|iplayer|pplayer|playerindex|victim|attacker|killer|ent_player)$/i;
const LENGTH = /^(len|maxlen|maxlength|length|size|max_len|ilen|len\d*|outlen|buflen)$/i;
const PY_KEYWORDS = new Set(['len', 'id', 'type', 'str', 'max', 'min', 'from', 'class', 'def', 'in', 'is', 'and', 'or', 'not']);

function pyName(name) {
  const snake = name.replace(/^(sz|i|fl|f|b|p|v|psz)(?=[A-Z])/, '').replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
  return PY_KEYWORDS.has(snake) || !snake ? `${snake}_value` : snake;
}

function size(dim, constants) {
  if (/^\d+$/.test(dim)) return Number(dim);
  if (dim in constants) return constants[dim];
  return null;
}

// Значение по умолчанию Pawn → Python
function pyDefault(param, constants) {
  const d = param.default;
  if (d === null) return null;
  if (d === 'true') return 'True';
  if (d === 'false') return 'False';
  if (/^-?\d+(\.\d+)?$/.test(d) || /^".*"$/.test(d)) return d;
  if (/^-?\d+\.$/.test(d)) return `${d}0`;
  if (d in constants) return `${constants[d]}`;
  return null;
}

/** Пример вызова из Python: {code, outputs} — все параметры, выходные — обёртками amxx */
function pythonExample(native, constants = {}) {
  const lines = [];
  const args = [`"${native.name}"`];
  const outputs = [];
  const unknown = [];
  native.params.forEach((p, i) => {
    const next = native.params[i + 1];
    const isFloat = /^float$/i.test(p.tag);
    if (p.varargs) {
      args.push('amxx.Ref(0)');
      return;
    }
    if (p.ref) {
      const name = pyName(p.name);
      lines.push(`${name} = amxx.${isFloat ? 'FloatRef' : 'Ref'}()`);
      args.push(name);
      outputs.push(`${name}.value`);
      return;
    }
    if (p.dims.length && !p.const) {
      const name = pyName(p.name);
      const n = size(p.dims[0], constants);
      if (!isFloat && !p.dims[0] && next && !next.dims.length && !next.ref && LENGTH.test(next.name)) {
        lines.push(`${name} = amxx.String(64)`);
        args.push(name);
        outputs.push(`${name}.value`);
        args.push('63');
        native.params[i + 1]._consumed = true;
        return;
      }
      lines.push(`${name} = amxx.${isFloat ? 'FloatArray' : 'Array'}(${n ?? 32})`);
      args.push(name);
      outputs.push(`${name}.values`);
      return;
    }
    if (p._consumed) {
      delete p._consumed;
      return;
    }
    const fallback = pyDefault(p, constants);
    if (p.dims.length) {  // const-массив или строка
      if (isFloat) args.push(`[${Array(size(p.dims[0], constants) || 3).fill('0.0').join(', ')}]`);
      else args.push(fallback ?? '"..."');
      return;
    }
    if (PLAYER.test(p.name)) args.push('player');
    else if (fallback !== null) args.push(fallback);
    else if (isFloat) args.push('0.0');
    else if (/^bool$/i.test(p.tag)) args.push('True');
    else {
      args.push(pyName(p.name));
      unknown.push(pyName(p.name));
    }
    if (p.default !== null && fallback === null) unknown.push(`${pyName(p.name)} (${p.default})`);
  });
  const fn = /^float$/i.test(native.tag) ? 'amxx.call_float' : 'amxx.call';
  const call = `${fn}(${args.join(', ')})`;
  lines.push(outputs.length || !native.doc.returns ? call : `result = ${call}`);
  if (outputs.length) lines.push(`# результат: ${outputs.join(', ')}`);
  if (native.params.some((p) => p.varargs)) lines.push('# any:... — числа и float по ссылке: amxx.Ref(5), amxx.FloatRef(1.5)');
  return { code: lines.join('\n'), unknown };
}

/** Markdown для наведения и автодополнения (в стиле подсказок AMXB) */
function nativeMarkdown(native, constants = {}) {
  const doc = native.doc;
  const out = [`**amxx.call** · \`${native.file || 'native'}\``, '', '```pawn', signature(native), '```'];
  if (doc.text) out.push('', doc.text);
  const params = native.params.filter((p) => doc.params[p.varargs ? '...' : p.name] !== undefined || p.default !== null);
  if (params.length) {
    out.push('', '#### Параметры');
    for (const p of native.params) {
      const key = p.varargs ? '...' : p.name;
      const text = doc.params[key] || '';
      const def = p.default !== null ? ` *(по умолчанию ${p.default})*` : '';
      if (text || def) out.push(`- \`${key}\` — ${text}${def}`.replace(/ — $/, ''));
    }
  }
  if (doc.returns) out.push('', '#### Возвращает', doc.returns);
  if (doc.error) out.push('', '#### Ошибки', doc.error);
  if (doc.notes.length) out.push('', '#### Заметки', ...doc.notes.map((n) => `- ${n}`));
  const example = pythonExample(native, constants);
  out.push('', '#### Из Python', '```python', example.code, '```');
  out.push('', '*Передавайте все параметры: значения по умолчанию в Pawn подставляет компилятор, а не натив.*');
  return out.join('\n');
}

module.exports = { pythonExample, nativeMarkdown, pyName };
