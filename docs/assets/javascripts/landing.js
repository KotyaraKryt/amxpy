// Главная: анимации лендинга (подключается только в overrides/home.html). Обёрнуто в функцию: имена не пересекаются с глобальными Material.
(() => {
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// строка под заголовком: печать и стирание
const phrases = ['обновляются без рестарта сервера', 'не тормозят сервер на запросах к базе', 'проверяются ещё до запуска', 'работают рядом с вашими Pawn-плагинами'];
const rot = document.getElementById('rot');
(async function rotate() {
  if (reduced) { rot.textContent = phrases[0]; return; }
  for (let i = 0; ; i = (i + 1) % phrases.length) {
    for (const ch of phrases[i]) { rot.textContent += ch; await sleep(42); }
    await sleep(2200);
    while (rot.textContent) { rot.textContent = rot.textContent.slice(0, -1); await sleep(18); }
    await sleep(250);
  }
})();

const install = document.getElementById('install');
install.onclick = async () => {
  try { await navigator.clipboard.writeText('amxpy init my-plugins'); } catch {}
  install.classList.add('done'); install.querySelector('.copy').textContent = 'Скопировано';
  setTimeout(() => { install.classList.remove('done'); install.querySelector('.copy').textContent = 'Скопировать'; }, 1800);
};

// сценарий в окне: код плагина → установка на сервер → тест
const code = document.getElementById('code');
const win = document.getElementById('window');
const tabs = [...document.querySelectorAll('.tabs [data-t]')];
const hint = document.getElementById('hint');
let run = 0;  // номер запуска: другая вкладка прерывает прежнюю сцену
const SPIN = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏';

class Stop extends Error {}
function guard(id) { if (id !== run) throw new Stop(); }
async function wait(ms, id) { await sleep(ms); guard(id); }
function line(html = '', cls = '') {
  const row = document.createElement('div');
  if (cls) row.className = cls;
  row.innerHTML = html;
  code.appendChild(row);
  return row;
}
async function typeInto(el, text, speed, id) {
  for (const ch of text) { el.textContent += ch; await wait(speed, id); }
}
async function typeTokens(tokens, speed, id) {
  for (const [cls, text] of tokens) {
    const span = document.createElement('span'); if (cls) span.className = cls; code.appendChild(span);
    for (const ch of text) { span.textContent += ch; await wait(ch === '\n' ? speed * 4 : speed, id); }
  }
}
async function command(text, id) {  // $ команда — печатается, курсор мигает
  const row = line('<span class="dim">$</span> ');
  const typed = document.createElement('span'); row.appendChild(typed);
  const cursor = document.createElement('span'); cursor.className = 'cursor'; row.appendChild(cursor);
  await wait(350, id);
  await typeInto(typed, text, 38, id);
  await wait(300, id);
  cursor.remove();
}
async function spinner(prefix, label, done, ms, id) {  // ⠋ работа… → ✓ итог
  const row = line();
  for (let t = 0; t < ms; t += 80) {
    row.innerHTML = `${prefix}<span class="spin">${SPIN[(t / 80) % SPIN.length]}</span>  <span class="dim">${label}</span>`;
    await wait(80, id);
  }
  row.innerHTML = `${prefix}<span class="ok">✓</span>  ${done}`;
  row.classList.add('fade');
}
async function progress(prefix, done, id) {  // [████░░] 64% → ✓
  const row = line(`${prefix}<span class="bar"><i></i></span><span class="dim">0%</span>`);
  const fill = row.querySelector('i'), pct = row.querySelector('.dim');
  for (let p = 0; p <= 100; p += 4) { fill.style.width = `${p}%`; pct.textContent = `${p}%`; await wait(28, id); }
  row.innerHTML = `${prefix}<span class="ok">✓</span>  ${done}`;
  row.classList.add('fade');
}

const PLUGIN = [
  ['k','from'], ['',' amxpy '], ['k','import'], ['',' Player, Plugin, events, sleep\n\n'],
  ['','plugin = Plugin('], ['s','"Hello"'], ['',', version='], ['s','"1.0.0"'], ['',')\n\n'],
  ['f','@plugin.on'], ['','(events.PutInServer)\n'],
  ['k','async def'], ['f',' greet'], ['','(e: events.PutInServer) -> '], ['k','None'], ['',':\n'],
  ['','    player = e.player\n'],
  ['','    '], ['k','await'], ['',' sleep('], ['s','3'], ['',')                  '], ['c','# сервер в это время не ждёт'], ['','\n'],
  ['','    player.print('], ['s','f"!gПривет, !t{player.name}!y! Набери !g/hp"'], ['',')\n\n'],
  ['f','@plugin.command'], ['','('], ['s','"/hp"'], ['',')\n'],
  ['k','def'], ['f',' hp'], ['','(player: Player) -> '], ['k','None'], ['',':\n'],
  ['','    player.print('], ['s','f"HP: {player.health}"'], ['',')'],
];
const TEST = [
  ['k','def'], ['f',' test_greets'], ['','(server: FakeServer) -> '], ['k','None'], ['',':\n'],
  ['','    server.load('], ['s','"plugins/hello.py"'], ['',')\n'],
  ['','    bob = server.join('], ['s','"Bob"'], ['',')\n'],
  ['','    server.run('], ['s','3.5'], ['',')             '], ['c','# виртуальное время: секунды за миг'], ['','\n'],
  ['','    '], ['k','assert'], ['',' '], ['s','"Привет, Bob"'], ['',' '], ['k','in'], ['',' bob.last_chat\n\n'],
];

const scenes = [
  { ms: 7800, async play(id) {
      await typeTokens(PLUGIN, 15, id);
      const c = document.createElement('span'); c.className = 'cursor'; code.appendChild(c);
  }},
  { ms: 8200, async play(id) {
      await command('amxpy deploy plugins/hello.py', id);
      line('amxpyc 0.1.0 · cpython-314 → build/plugins/', 'dim fade'); await wait(250, id);
      await spinner('  hello            ', 'проверка и сборка…', 'событий 1 · команд 1', 1100, id);
      await wait(200, id);
      line('установка → cs16-dev:/mnt/server/cstrike', 'dim fade'); await wait(200, id);
      await progress('  hello.amxpy      ', 'отправлено · 14 КБ', id);
      await spinner('  hello            ', 'перезапуск плагина…', 'amxpy reload', 900, id);
      await wait(250, id);
      line('[amxpy] reloaded hello — состояние игроков сохранено', 'y fade'); await wait(500, id);
      const prompt = line('<span class="dim">$</span> ');
      const c = document.createElement('span'); c.className = 'cursor'; prompt.appendChild(c);
  }},
  { ms: 7600, async play(id) {
      await typeTokens(TEST, 9, id);
      await command('pytest', id);
      const dots = line('<span class="dim">tests/test_hello.py </span>');
      for (let i = 0; i < 2; i++) { await wait(380, id); dots.insertAdjacentHTML('beforeend', '<span class="ok">.</span>'); }
      await wait(300, id);
      line('<span class="ok">2 passed</span><span class="dim"> in 0.04s</span>', 'fade');
  }},
];

function select(i, ms) {
  tabs.forEach((t) => t.classList.toggle('on', +t.dataset.t === i));
  const on = tabs[i];
  on.style.setProperty('--d', `${ms}ms`);
  on.classList.remove('on'); void on.offsetWidth; on.classList.add('on');  // перезапуск полосы прогресса
}
async function show(i, id) {
  code.innerHTML = '';
  try { await scenes[i].play(id); } catch (e) { if (!(e instanceof Stop)) throw e; return false; }
  return true;
}
async function autoplay() {
  const id = ++run;
  for (let i = 0; id === run; i = (i + 1) % scenes.length) {
    select(i, scenes[i].ms);
    const start = performance.now();
    if (!(await show(i, id))) return;
    await sleep(Math.max(1600, scenes[i].ms - (performance.now() - start)));
  }
}
tabs.forEach((t) => t.onclick = () => {  // выбранная сцена проигрывается заново, автопоказ останавливается
  const id = ++run, i = +t.dataset.t;
  win.classList.add('paused'); hint.textContent = 'автопоказ остановлен';
  select(i, 1); show(i, id);
});
if (reduced) {  // без анимаций: сразу код плагина целиком
  win.classList.add('paused'); select(0, 1);
  for (const [cls, text] of PLUGIN) { const span = document.createElement('span'); if (cls) span.className = cls; span.textContent = text; code.appendChild(span); }
} else autoplay();

// плитки: появление при прокрутке, счётчики, таймлайн, подсказка редактора
function countUp(el) {
  const target = +el.dataset.count, suffix = el.dataset.suffix || '';
  if (reduced) { el.textContent = target + suffix; return; }
  const start = performance.now();
  (function step(now) {
    const p = Math.min(1, (now - start) / 1400), v = Math.round(target * (1 - Math.pow(1 - p, 3)));
    el.textContent = v.toLocaleString('ru') + (p === 1 ? suffix : '');
    if (p < 1) requestAnimationFrame(step);
  })(start);
}
// плитка «Обновление без рестарта»: правка → deploy → игроки на месте
async function reloadDemo() {
  const word = document.getElementById('rdWord'), mark = document.getElementById('rdMark');
  const log = document.getElementById('rdLog'), players = document.getElementById('rdPlayers');
  const note = document.getElementById('rdNote'), uptime = document.getElementById('rdUptime');
  let seconds = 41 * 60 + 7;  // время на сервере: при перезагрузке плагина не сбрасывается
  setInterval(() => { seconds++; uptime.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`; }, 1000);
  const words = ['Привет', 'Добро пожаловать', 'Здорово'];
  const steps = [['проверка', 'ошибок нет', 800], ['отправка на сервер', 'hello.amxpy', 700], ['перезапуск плагина', '0,04 с', 600]];
  word.textContent = words[0];
  if (reduced) {
    log.innerHTML = '<div><span class="dim">$</span> <b>amxpy deploy</b></div>' + steps.map(([a, b]) => `<div><span class="ok">✓</span> ${a} — <b>${b}</b></div>`).join('');
    return;
  }
  for (let n = 1; ; n = (n + 1) % words.length) {
    await sleep(1400);
    while (word.textContent) { word.textContent = word.textContent.slice(0, -1); await sleep(45); }
    for (const ch of words[n]) { word.textContent += ch; await sleep(75); }
    mark.classList.add('on');
    await sleep(500);
    log.innerHTML = '';
    const cmd = document.createElement('div'); cmd.innerHTML = '<span class="dim">$</span> <b></b>'; log.appendChild(cmd);
    for (const ch of 'amxpy deploy') { cmd.querySelector('b').textContent += ch; await sleep(55); }
    await sleep(250);
    for (const [label, result, ms] of steps) {
      const row = document.createElement('div'); log.appendChild(row);
      for (let t = 0; t < ms; t += 80) { row.innerHTML = `<span class="ok">${SPIN[(t / 80) % SPIN.length]}</span> ${label}…`; await sleep(80); }
      row.innerHTML = `<span class="ok">✓</span> ${label} — <b></b>`;
      for (const ch of result) { row.querySelector('b').textContent += ch; await sleep(30); }
    }
    players.classList.remove('pulse'); void players.offsetWidth; players.classList.add('pulse');
    note.textContent = 'никто не вышел'; note.classList.add('on');
    mark.classList.remove('on');
    await sleep(2600);
    note.textContent = 'на сервере'; note.classList.remove('on');
  }
}
// новости в чипе: заголовки сменяются снизу вверх
(async function news() {
  const roll = document.getElementById('newsRoll'), bar = document.getElementById('newsBar');
  const items = JSON.parse(roll.dataset.items);  // из docs/releases.yml
  if (items.length < 2) return;
  if (reduced) return;
  for (let i = 1; ; i = (i + 1) % items.length) {
    bar.classList.remove('run'); void bar.offsetWidth; bar.classList.add('run');
    await sleep(3200);
    const old = roll.querySelector('span'), next = document.createElement('span');
    next.textContent = items[i]; next.className = 'in'; roll.appendChild(next);
    requestAnimationFrame(() => requestAnimationFrame(() => { old.className = 'out'; next.className = ''; }));
    await sleep(460); old.remove();
  }
})();
// «От события до вашей функции»: сценарии проходят по цепочке узлов
const ICON = {
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
  server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>',
  code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6l-6 6 6 6M16 6l6 6-6 6"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>',
};
const FLOWS = [
  { tab: 'Покупка', link: 'reference/events/#buyweapon', file: 'plugins/shop.py',
    desc: 'ReGameDLL сообщает о покупке до того, как спишутся деньги. Обработчик вызывает <code>e.cancel()</code> — оружие не выдаётся, деньги остаются у игрока.',
    nodes: [['user', 'Игрок Bob', 'покупает AWP'], ['server', 'ReGameDLL', 'хук покупки'], 'events.BuyWeapon', 'no_awp(e)', 'покупка отменена'],
    packets: ['buy awp', 'weapon = AWP', 'BuyWeapon(Bob, "awp")', 'e.cancel()', 'деньги на месте'],
    code: ['<span class="f">@plugin.on</span>(events.BuyWeapon)',
           '<span class="k">def</span> <span class="f">no_awp</span>(e: events.BuyWeapon) -> <span class="k">None</span>:',
           '    <span class="k">if</span> e.weapon == <span class="s">"awp"</span>:',
           '        e.player.print(<span class="s">"!tAWP на сервере запрещена"</span>)',
           '        e.cancel()'],
    steps: [{ l: [0, 1] }, { l: [2] }, { l: [3] }, { l: [4] }] },
  { tab: 'Вход', link: 'guide/events/', file: 'plugins/hello.py',
    desc: 'Metamod-R передаёт модулю вход игрока. Обработчик — async-функция: <code>await sleep(3)</code> ждёт три секунды, не останавливая сервер, и пишет приветствие в чат.',
    nodes: [['user', 'Игрок Bob', 'заходит на сервер'], ['server', 'Metamod-R', 'ClientPutInServer'], 'events.PutInServer', 'greet(e)', 'приветствие в чате'],
    packets: ['connect', 'ClientPutInServer', 'PutInServer(Bob)', 'await sleep(3)', '«Привет, Bob!»'],
    code: ['<span class="f">@plugin.on</span>(events.PutInServer)',
           '<span class="k">async def</span> <span class="f">greet</span>(e: events.PutInServer) -> <span class="k">None</span>:',
           '    <span class="k">await</span> sleep(<span class="s">3</span>)  <span class="c"># сервер в это время не ждёт</span>',
           '    e.player.print(<span class="s">f"!gПривет, !t{e.player.name}!y!"</span>)'],
    steps: [{ l: [0, 1] }, { l: [2], ms: 1300 }, { l: [3] }] },
  { tab: 'Команда', link: 'guide/commands/', file: 'plugins/hp.py',
    desc: 'Сообщение <code>/hp</code> в чате приходит серверу как ClientCommand. amxpy находит команду по имени и вызывает функцию с готовым объектом <code>Player</code>.',
    nodes: [['user', 'Игрок Bob', 'пишет /hp в чат'], ['server', 'Metamod-R', 'ClientCommand'], 'команда /hp', 'hp(player)', 'ответ в чате'],
    packets: ['say /hp', 'ClientCommand', 'команда "/hp"', 'hp(Bob)', '«HP: 100»'],
    code: ['<span class="f">@plugin.command</span>(<span class="s">"/hp"</span>)',
           '<span class="k">def</span> <span class="f">hp</span>(player: Player) -> <span class="k">None</span>:',
           '    player.print(<span class="s">f"!yHP: !g{player.health}"</span>)'],
    steps: [{ l: [0, 1] }, { l: [2] }] },
  { tab: 'Pawn-форвард', link: 'pawn/forwards/', file: 'plugins/vip.py',
    desc: 'Pawn-плагин вызывает <code>ExecuteForward</code>, как обычно. amxpy принимает форвард по имени и приводит аргументы к типам из подписи: индекс — в <code>Player</code>, число — в <code>int</code>.',
    note: 'Новая подписка на форвард начинает работать со следующей карты.',
    nodes: [['file', 'vip.amxx', 'ExecuteForward'], ['server', 'AMX Mod X', 'форвард vip_granted'], 'on_forward', 'granted(…)', 'сообщение игроку'],
    packets: ['ExecuteForward', 'vip_granted(1, 30)', 'Player, 30', 'granted(Bob, 30)', '«VIP на 30 дней»'],
    code: ['<span class="f">@plugin.on_forward</span>(<span class="s">"vip_granted"</span>)',
           '<span class="k">def</span> <span class="f">granted</span>(player: Player, days: int) -> <span class="k">None</span>:',
           '    player.print(<span class="s">f"!gVIP!y активен ещё !t{days}!y дней"</span>)'],
    steps: [{ l: [0, 1] }, { l: [2] }] },
];
const chain = document.getElementById('chain'), nds = [...chain.querySelectorAll('.nd')];
const rail = document.getElementById('rail'), spark = document.getElementById('spark'), packet = document.getElementById('packet'), tag = packet.querySelector('span');
const flowCode = document.getElementById('flowCode'), flowTabs = document.getElementById('flowTabs'), desc = document.getElementById('flowDesc');
let flowRun = 0;
FLOWS.forEach((f, i) => {
  const b = document.createElement('button'); b.textContent = f.tab;
  b.addEventListener('click', () => (reduced ? flowStatic(i) : flowPlay(i)));
  flowTabs.appendChild(b);
});
function flowSetup(i) {
  const f = FLOWS[i];
  [...flowTabs.children].forEach((b, k) => b.classList.toggle('on', k === i));
  const [[ic0, t0, s0], [ic1, t1, s1], s2, s3, s4] = f.nodes;
  const set = [[ICON[ic0], t0, s0], [ICON[ic1], t1, s1], [null, null, s2], [ICON.code, null, s3], [ICON.done, null, s4]];
  nds.forEach((n, k) => {
    const [icon, title, sub] = set[k];
    if (icon) n.querySelector('.ic').innerHTML = icon;
    if (title) n.querySelector('b').textContent = title;
    n.querySelector('span').textContent = sub;
    n.classList.remove('on', 'done');
  });
  document.getElementById('flowFile').textContent = f.file;
  desc.querySelector('p').innerHTML = f.desc;
  desc.querySelector('small').textContent = f.note || '';
  document.getElementById('flowMore').href = f.link;  // главная лежит в корне сайта
  flowCode.innerHTML = f.code.map((l) => `<div>${l}</div>`).join('');
}
function flowMove(k, text, instant) {
  for (const el of [packet, spark, rail]) el.style.transition = instant ? 'none' : '';
  packet.style.left = spark.style.left = `${10 + k * 20}%`;
  rail.style.width = `${k * 25}%`;
  if (instant) { tag.textContent = text; void packet.offsetWidth; return; }
  tag.style.opacity = 0;
  setTimeout(() => { tag.textContent = text; tag.style.opacity = 1; }, 220);
}
const hl = (lines) => [...flowCode.children].forEach((d, k) => d.classList.toggle('hl', lines.includes(k)));
function flowStatic(i) {  // финальное состояние сценария — без анимации
  const f = FLOWS[i];
  flowSetup(i);
  nds.forEach((n, k) => n.classList.add(k === 4 ? 'on' : 'done'));
  flowMove(4, f.packets[4], true);
  hl(f.steps[f.steps.length - 1].l);
}
class FlowStop extends Error {}
async function flowPlay(i) {
  const id = ++flowRun, f = FLOWS[i];
  const pause = async (ms) => { await sleep(ms); if (id !== flowRun) throw new FlowStop(); };
  try {
    chain.classList.add('swap'); desc.classList.add('swap'); await pause(260);
    flowSetup(i); flowMove(0, f.packets[0], true);
    chain.classList.remove('swap'); desc.classList.remove('swap'); await pause(300);
    for (let k = 0; k < 5; k++) {
      flowMove(k, f.packets[k]);
      nds.forEach((n, j) => { n.classList.toggle('on', j === k); n.classList.toggle('done', j < k); });
      await pause(k ? 850 : 500);
      if (k === 3) for (const st of f.steps) { hl(st.l); await pause(st.ms || 800); }
      else await pause(500);
    }
    await pause(2600); hl([]);
    flowPlay((i + 1) % FLOWS.length);
  } catch (e) { if (!(e instanceof FlowStop)) throw e; }
}
flowStatic(0);

// финальный блок: команды печатаются и выполняются по очереди; высота строк не меняется
async function checksDemo() {
  const rows = [...document.querySelectorAll('#checks .ck')];
  if (reduced) { rows.forEach((r) => { r.classList.add('done'); const t = r.querySelector('.tx'); t.textContent = t.dataset.t; }); return; }
  for (;;) {
    rows.forEach((r) => { r.className = 'ck'; r.querySelector('.tx').textContent = ''; });
    for (const r of rows) {
      const t = r.querySelector('.tx'), caret = document.createElement('span');
      caret.className = 'ck-caret'; t.after(caret); r.classList.add('busy');
      for (const ch of t.dataset.t) { t.textContent += ch; await sleep(55); }
      await sleep(700); caret.remove(); r.classList.replace('busy', 'done'); await sleep(350);
    }
    await sleep(4000);
  }
}

// «Работает вместе с Pawn»: пары Pawn-плагин ⇄ Python-плагин по кругу
async function pawnPairs() {
  const box = document.getElementById('pawn'), [pawn, py] = box.querySelectorAll('span');
  const pairs = [['admin.amxx', 'plugins/vip.py'], ['statsx.amxx', 'plugins/rank.py'], ['mapchooser.amxx', 'plugins/votes.py'], ['shop.amxx', 'plugins/bonus.py']];
  for (let i = 1; !reduced; i = (i + 1) % pairs.length) {
    await sleep(2600);
    box.classList.add('swap'); await sleep(300);
    [pawn.textContent, py.textContent] = pairs[i];
    box.classList.remove('swap');
  }
}
pawnPairs();
async function editor() {
  const typed = document.getElementById('typed'), tip = document.getElementById('tip');
  for (;;) {
    typed.textContent = ''; tip.classList.remove('in');
    for (const ch of 'e.attacker') { typed.textContent += ch; await sleep(reduced ? 0 : 110); }
    tip.classList.add('in');
    if (reduced) return;
    await sleep(3200);
  }
}
const seen = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    e.target.classList.add('vis'); seen.unobserve(e.target);
    e.target.querySelectorAll('[data-count]').forEach(countUp);
    if (e.target.id === 'reload') reloadDemo();
    if (e.target.id === 'ide') editor();
    if (e.target.id === 'flow' && !reduced) flowPlay(0);
    if (e.target.id === 'cta') checksDemo();
  }
}, { threshold: .25 });
document.querySelectorAll('.reveal').forEach((el, i) => { el.style.transitionDelay = `${(i % 4) * 70}ms`; seen.observe(el); });
})();
