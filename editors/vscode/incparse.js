// Разбор .inc AMX Mod X: нативы с сигнатурой и документацией (/** */ и /* */ с @param, @return...)
'use strict';

// Разделить по запятым верхнего уровня (без скобок и строк)
function splitTop(text) {
  const parts = [];
  let depth = 0;
  let quote = null;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === '\\') i++;
      else if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") quote = ch;
    else if ('([{'.includes(ch)) depth++;
    else if (')]}'.includes(ch)) depth--;
    else if (ch === ',' && depth === 0) {
      parts.push(text.slice(start, i));
      start = i + 1;
    }
  }
  if (text.trim()) parts.push(text.slice(start));
  return parts.map((p) => p.replace(/\s+/g, ' ').trim()).filter(Boolean);
}

/** Параметр Pawn: {raw, name, tag, ref, const, dims, default, varargs} */
function parseParam(raw) {
  const varargs = /^(?:const\s+)?(?:([A-Za-z_]\w*):)?\.\.\.$/.exec(raw);
  if (varargs) return { raw, name: '...', tag: varargs[1] || '', ref: false, const: false, dims: [], default: null, varargs: true };
  const m = /^(const\s+)?(&)?\s*(?:([A-Za-z_]\w*):)?\s*(&)?\s*([A-Za-z_]\w*)\s*((?:\[[^\]]*\]\s*)*)(?:=\s*(.+))?$/.exec(raw);
  if (!m) return { raw, name: raw, tag: '', ref: false, const: false, dims: [], default: null, varargs: false };
  const dims = [...(m[6] || '').matchAll(/\[([^\]]*)\]/g)].map((d) => d[1].trim());
  return {
    raw, name: m[5], tag: m[3] || '', ref: Boolean(m[2] || m[4]), const: Boolean(m[1]), dims,
    default: m[7] === undefined ? null : m[7].trim(), varargs: false,
  };
}

/** Текст doc-комментария → {text, params: {имя: описание}, returns, notes: [], error} */
function parseDoc(comment) {
  const lines = comment.replace(/^\/\*+/, '').replace(/\*+\/$/, '').split(/\r?\n/)
    .map((l) => l.replace(/^\s*\*+ ?/, '').replace(/\s+$/, ''));
  const doc = { text: '', params: {}, returns: '', notes: [], error: '' };
  let target = { set: (v) => { doc.text += v; }, get: () => doc.text };
  for (const line of lines) {
    const tag = /^\s*@(\w+)\s*(.*)$/.exec(line);
    if (tag) {
      const [, kind, rest] = tag;
      if (kind === 'param') {
        const p = /^(\S+)\s*(.*)$/.exec(rest) || [null, rest, ''];
        const name = p[1];
        doc.params[name] = p[2];
        target = { set: (v) => { doc.params[name] += v; }, get: () => doc.params[name] };
      } else if (kind === 'return' || kind === 'returns') {
        doc.returns = rest;
        target = { set: (v) => { doc.returns += v; }, get: () => doc.returns };
      } else if (kind === 'noreturn') {
        doc.returns = '';
      } else if (kind === 'error') {
        doc.error = rest;
        target = { set: (v) => { doc.error += v; }, get: () => doc.error };
      } else {
        const index = doc.notes.push(rest) - 1;
        target = { set: (v) => { doc.notes[index] += v; }, get: () => doc.notes[index] };
      }
      continue;
    }
    const text = line.trim();
    if (!text) {
      if (target.get() && !target.get().endsWith('\n\n')) target.set('\n\n');
      continue;
    }
    const current = target.get();
    target.set(current && !current.endsWith('\n') ? ` ${text}` : text);
  }
  const trim = (s) => s.replace(/\s*\n\n\s*$/, '').trim();
  doc.text = trim(doc.text);
  doc.returns = trim(doc.returns);
  doc.error = trim(doc.error);
  doc.notes = doc.notes.map(trim).filter(Boolean);
  for (const k of Object.keys(doc.params)) doc.params[k] = trim(doc.params[k]);
  return doc;
}

const NATIVE = /^[ \t]*native\s+(?:([A-Za-z_]\w*):)?([A-Za-z_]\w*)\s*\(([\s\S]*?)\)\s*;/gm;

/** Нативы из текста .inc: [{name, tag, params, doc, file, line}] */
function parseInclude(text, file = '') {
  const out = [];
  for (const m of text.matchAll(NATIVE)) {
    const before = text.slice(0, m.index).replace(/\s+$/, '');
    let doc = null;
    if (before.endsWith('*/')) {
      const open = before.lastIndexOf('/*');
      if (open >= 0) doc = parseDoc(before.slice(open));
    }
    out.push({
      name: m[2],
      tag: m[1] || '',
      params: splitTop(m[3]).map(parseParam),
      doc: doc || { text: '', params: {}, returns: '', notes: [], error: '' },
      file,
      line: text.slice(0, m.index).split('\n').length,
    });
  }
  return out;
}

// Числовое выражение константы: 5, -1, 0x10, (1<<3), A|B, ранее известные имена
function evaluate(expr, known) {
  const text = expr.replace(/\/\/.*$|\/\*[\s\S]*?\*\//g, '').trim();
  if (!text || !/^[\w\s()<>|&+\-~*]+$/.test(text)) return null;
  const js = text.replace(/[A-Za-z_]\w*/g, (name) => (/^0x/i.test(name) ? name : name in known ? `(${known[name]})` : '#'));
  if (js.includes('#') || /[^0-9a-fA-Fx\s()<>|&+\-~*]/.test(js)) return null;
  try {
    const value = Function(`"use strict"; return (${js});`)();
    return Number.isInteger(value) ? value : null;
  } catch {
    return null;
  }
}

/** Числовые константы .inc: #define и элементы enum → {имя: значение} */
function parseConstants(text, known = {}) {
  const constants = known;
  const clean = text.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const m of clean.matchAll(/^[ \t]*#define\s+([A-Za-z_]\w*)[ \t]+([^\n]+)$/gm)) {
    const value = evaluate(m[2], constants);
    if (value !== null) constants[m[1]] = value;
  }
  for (const m of clean.matchAll(/\benum\b[^{;]*\{([^}]*)\}/g)) {
    let next = 0;
    for (const item of splitTop(m[1].replace(/\/\/[^\n]*/g, ''))) {
      const e = /^([A-Za-z_]\w*)(?:\[[^\]]*\])?\s*(?:=\s*(.+))?$/.exec(item);
      if (!e) continue;
      const value = e[2] === undefined ? next : evaluate(e[2], constants);
      if (value === null) break;
      constants[e[1]] = value;
      next = value + 1;
    }
  }
  return constants;
}

/** Сигнатура как в Pawn: native Float:name(const a[], &b, ...) */
function signature(native) {
  return `native ${native.tag ? `${native.tag}:` : ''}${native.name}(${native.params.map((p) => p.raw).join(', ')})`;
}

module.exports = { parseInclude, parseConstants, parseParam, parseDoc, splitTop, signature, evaluate };
