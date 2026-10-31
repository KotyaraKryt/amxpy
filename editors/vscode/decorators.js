// Заготовка def по строке декоратора amxpy: @plugin.command("/hp") → def ${1:hp}(player: Player) -> None:
'use strict';

const BODY = '\t${0:...}';

// Скобки закрыты (без учёта строк): декоратор дописан до конца
function balanced(text) {
  let depth = 0;
  let quote = null;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === '\\') i++;
      else if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === '(' || ch === '[' || ch === '{') depth++;
    else if (ch === ')' || ch === ']' || ch === '}') depth--;
  }
  return depth === 0 && quote === null;
}

// Первый аргумент вызова до запятой верхнего уровня
function firstArg(args) {
  let depth = 0;
  let quote = null;
  for (let i = 0; i < args.length; i++) {
    const ch = args[i];
    if (quote) {
      if (ch === '\\') i++;
      else if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") quote = ch;
    else if ('([{'.includes(ch)) depth++;
    else if (')]}'.includes(ch)) depth--;
    else if (ch === ',' && depth === 0) return args.slice(0, i).trim();
  }
  return args.trim();
}

function stringLiteral(text) {
  const m = /^[rRbBuUfF]*(["'])(.*?)\1$/.exec(text.trim());
  return m ? m[2] : null;
}

function keyword(args, name) {
  const m = new RegExp(`\\b${name}\\s*=\\s*(["'])(.*?)\\1`).exec(args);
  return m ? m[2] : null;
}

// Имя функции из имени команды, пункта меню и т. п.; кириллица и мусор — fallback
function ident(text, fallback) {
  const name = (text || '').toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
  if (!name) return fallback;
  return /^[0-9]/.test(name) ? `${fallback}_${name}` : name;
}

function snake(name) {
  return name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
}

/**
 * Сниппет def для строки декоратора или null, если это не декоратор amxpy.
 * @param {string} line строка с декоратором (с отступом или без)
 */
function defSnippet(line) {
  const text = line.trim().replace(/\s+#.*$/, '');
  const m = /^@([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\.([a-z_]+)(?:\((.*)\))?$/s.exec(text);
  if (!m || !balanced(text)) return null;
  const [, , method, rawArgs] = m;
  const args = rawArgs || '';
  const first = firstArg(args);
  const literal = stringLiteral(first);
  const def = (name, params, result = 'None') => `def \${1:${name}}(${params}) -> ${result}:\n${BODY}`;

  switch (method) {
    case 'on': {
      const event = /^(?:[A-Za-z_]\w*\.)*([A-Z]\w*)$/.exec(first);
      if (!event) return null;
      return def(`on_${snake(event[1])}`, `e: ${first}`);
    }
    case 'command': {
      if (literal === null) return null;
      const caller = /\baccess\s*=/.test(args) ? 'admin' : 'player';
      return def(ident(literal.replace(/^[/!]/, ''), 'cmd'), `${caller}: Player`);
    }
    case 'server_command':
      return literal === null ? null : def(ident(literal, 'cmd'), '');
    case 'native': {
      const name = keyword(args, 'name') || literal;
      return `def \${1:${ident(name, 'plugin_native')}}(\${2:player: Player}) -> \${3|int,bool,float,str,None|}:\n`
        + `\t"""\${4:Описание для .inc}"""\n${BODY}`;
    }
    case 'every':
      return rawArgs === undefined ? null : def('tick', '');
    case 'on_forward':
      return literal === null ? null : def(`on_${ident(literal, 'forward')}`, '*args: object');
    case 'item':
      return rawArgs === undefined ? null : def(ident(literal, 'on_select'), 'player: Player');
    case 'on_change':
      if (literal === null) return null;
      return `def \${1:on_${ident(literal, 'cvar')}_change}(old: \${2:int}, new: \${2:int}) -> None:\n${BODY}`;
    default:
      return null;
  }
}

module.exports = { defSnippet, balanced };
