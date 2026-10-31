'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { templates, preview } = require('../completions');
const { neededNames, importEdit } = require('../imports');

test('шаблоны для каждого роутера и меню файла', () => {
  const src = 'from amxpy import Menu, Plugin, Router\nplugin = Plugin("X")\nrouter: Router = Router()\nshop = Menu("M")\n';
  const labels = templates(src).map((t) => t.label);
  assert.ok(labels.includes('@plugin.command') && labels.includes('@router.on') && labels.includes('@shop.item'));
  assert.deepEqual(templates('import amxpy\n').map((t) => t.label)[0], '@plugin.command');
});

test('предпросмотр: имя функции из команды и события', () => {
  const byLabel = Object.fromEntries(templates('plugin = Plugin("X")').map((t) => [t.label, preview(t.snippet)]));
  assert.equal(byLabel['@plugin.command'].split('\n')[1], 'def name(player: Player) -> None:');
  assert.equal(byLabel['@plugin.on'].split('\n')[1], 'def on_put_in_server(e: events.PutInServer) -> None:');
  assert.equal(byLabel['@plugin.native'].split('\n')[1], 'def name(player: Player) -> int:');
});

test('нужные имена из amxpy', () => {
  assert.deepEqual(neededNames('def x(admin: Player) -> None: Access.KICK events.Say'), ['Player', 'Access', 'events']);
  assert.deepEqual(neededNames('def tick() -> None:'), []);
});

test('импорт: дописать в строку, отсортировать, не дублировать', () => {
  const src = '"""Док."""\n\nfrom amxpy import Plugin, cvar  # API\n\nplugin = Plugin("X")\n';
  assert.deepEqual(importEdit(src, ['Player', 'events']),
    { line: 2, replace: true, text: 'from amxpy import Player, Plugin, cvar, events  # API' });
  assert.equal(importEdit(src, ['Plugin']), null);
  assert.equal(importEdit('from amxpy import Player as P, events\n', ['events']), null);
});

test('импорт: новой строкой после блока импортов', () => {
  const src = '"""Многострочный\nдокстринг."""\nimport time\nfrom x import (\n    a,\n)\n\nplugin = 1\n';
  assert.deepEqual(importEdit(src, ['Player']), { line: 6, replace: false, text: 'from amxpy import Player' });
  assert.equal(importEdit('from amxpy import (\n    Player,  # игрок\n    events,\n)\n', ['Player', 'events']), null);
  assert.deepEqual(importEdit('plugin = 1\n', ['Player']), { line: 0, replace: false, text: 'from amxpy import Player' });
});
