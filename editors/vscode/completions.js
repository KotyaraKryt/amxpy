// Заготовки по «@» в начале строки: декоратор amxpy вместе с def
'use strict';

// Каталог amxpy.events, частые — первыми (tests/test_lint.py сверяет набор с Python)
const EVENTS = ['PutInServer', 'TakeDamage', 'PlayerSpawn', 'PlayerKilled', 'Say', 'RoundStart', 'FreezeEnd',
  'RoundEnd', 'TeamSelect', 'BuyWeapon', 'MoneyChange', 'DropItem', 'NameChange', 'GrenadeThrow', 'BombPlanted',
  'BombDefuseStart', 'BombDefuseEnd', 'BombExploded', 'Connect', 'Authorized', 'Disconnected', 'Init', 'MapStart',
  'MapEnd', 'Unload', 'Frame'];
const ACCESS = ['KICK', 'BAN', 'SLAY', 'MAP', 'CVAR', 'CFG', 'CHAT', 'VOTE', 'RCON', 'MENU', 'IMMUNITY'];
const BODY = '\t${0:...}';
const FN = '${1/[^A-Za-z0-9_]+/_/g}'; // имя функции = имя команды, обновляется по мере ввода

function variables(source, kinds) {
  const re = new RegExp(`^([A-Za-z_]\\w*)\\s*(?::[^=]+)?=\\s*(?:amxpy\\.)?(?:${kinds})\\(`, 'gm');
  return [...new Set([...source.matchAll(re)].map((m) => m[1]))];
}

/** Заготовки для файла: [{label, detail, documentation, snippet}] */
function templates(source) {
  const routers = variables(source, 'Plugin|Router');
  const out = [];
  for (const r of routers.length ? routers : ['plugin']) {
    out.push(
      {
        label: `@${r}.command`, detail: 'Команда игрока в чате: /name',
        documentation: 'Имя функции повторяет имя команды. Первый параметр — игрок, остальные аргументы разбираются по аннотациям.',
        snippet: `@${r}.command("/\${1:name}", help="\${2:Описание}")\ndef ${FN}(player: Player) -> None:\n${BODY}`,
      },
      {
        label: `@${r}.command admin`, detail: 'Команда админа: доступ и игрок-цель',
        documentation: 'Usage строится из сигнатуры: amx_name <target> [amount].',
        snippet: `@${r}.command("\${1:amx_name}", access=Access.\${2|${ACCESS.join(',')}|}, help="\${3:Описание}")\n`
          + `def ${FN}(admin: Player, target: Player\${4:, amount: int = 1}) -> None:\n${BODY}`,
      },
      {
        label: `@${r}.on`, detail: 'Обработчик события',
        documentation: 'Событие выбирается из списка; функция называется on_<событие>.',
        snippet: `@${r}.on(events.\${1|${EVENTS.join(',')}|})\ndef on\${1/([A-Z])/_\${1:/downcase}/g}(e: events.$1) -> None:\n${BODY}`,
      },
      {
        label: `@${r}.on async`, detail: 'Async-обработчик события (с await)',
        documentation: 'Событие живёт до первого await: нужные поля скопируйте заранее.',
        snippet: `@${r}.on(events.\${1|${EVENTS.join(',')}|})\nasync def on\${1/([A-Z])/_\${1:/downcase}/g}(e: events.$1) -> None:\n${BODY}`,
      },
      {
        label: `@${r}.native`, detail: 'Натив для Pawn-плагинов (попадёт в .inc)',
        documentation: 'Сигнатура натива — из аннотаций: int, float, bool, str, Player.',
        snippet: `@${r}.native\ndef \${1:name}(\${2:player: Player}) -> \${3|int,bool,float,str,None|}:\n\t"""\${4:Описание для .inc}"""\n${BODY}`,
      },
      {
        label: `@${r}.every`, detail: 'Периодическая задача',
        documentation: 'Вызывается раз в N секунд, пока плагин работает.',
        snippet: `@${r}.every(\${1:1.0})\ndef \${2:tick}() -> None:\n${BODY}`,
      },
      {
        label: `@${r}.server_command`, detail: 'Команда серверной консоли и rcon',
        documentation: 'Без игрока: аргументы разбираются по аннотациям.',
        snippet: `@${r}.server_command("\${1:amx_name}", help="\${2:Описание}")\ndef ${FN}() -> None:\n${BODY}`,
      },
    );
  }
  for (const menu of variables(source, 'Menu')) {
    out.push({
      label: `@${menu}.item`, detail: 'Пункт меню',
      documentation: 'Функция вызывается с игроком, который выбрал пункт.',
      snippet: `@${menu}.item("\${1:Пункт}")\ndef \${2:on_select}(player: Player) -> None:\n${BODY}`,
    });
  }
  return out;
}

// ${N/regex/format/flags}: разбор по символам — в format бывает ${1:/downcase} со своим «/»
function transforms(snippet, apply) {
  let out = '';
  let i = 0;
  for (let at; (at = snippet.slice(i).search(/\$\{\d+\//)) >= 0;) {
    out += snippet.slice(i, i + at);
    let j = i + at + 2;
    const n = snippet.slice(j).match(/^\d+/)[0];
    j += n.length + 1;
    const parts = [];
    for (let k = 0; k < 2; k++) {
      let part = '';
      let depth = 0;
      for (; j < snippet.length && !(snippet[j] === '/' && depth === 0); j++) {
        if (snippet[j] === '\\') part += snippet[j++];
        else if (snippet.startsWith('${', j)) depth++;
        else if (snippet[j] === '}' && depth > 0) depth--;
        part += snippet[j];
      }
      parts.push(part);
      j++;
    }
    const close = snippet.indexOf('}', j);
    out += apply(n, parts[0], parts[1], snippet.slice(j, close));
    i = close + 1;
  }
  return out + snippet.slice(i);
}

// Текст заготовки, как он вставится со значениями по умолчанию: для подсказки
function preview(snippet) {
  const values = {};
  for (const m of snippet.matchAll(/\$\{(\d+)(?:\|([^,|]*)[^}]*\||:([^/${}][^${}]*))\}/g)) values[m[1]] ??= m[2] ?? m[3];
  return transforms(snippet, (n, re, format, flags) =>
    (values[n] || '').replace(new RegExp(re, flags), (...m) =>
      format.replace(/\$\{(\d+):\/downcase\}|\$(\d+)/g, (_, d, g) => (d ? (m[+d] || '').toLowerCase() : m[+g] || ''))))
    .replace(/\$\{(\d+)(?:\|[^}]*\||:[^${}]*)\}/g, (_, n) => values[n])
    .replace(/\$(\d+)/g, (_, n) => values[n] ?? '')
    .replace(/\t/g, '    ');
}

module.exports = { templates, preview, EVENTS };
