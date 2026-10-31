'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { defSnippet } = require('../decorators');

const head = (line) => (defSnippet(line) || '').split('\n')[0];

test('команды: имя функции из имени команды, админ — с access', () => {
  assert.equal(head('@plugin.command("test")'), 'def ${1:test}(player: Player) -> None:');
  assert.equal(head('    @router.command("/hp", help="Здоровье")'), 'def ${1:hp}(player: Player) -> None:');
  assert.equal(head('@plugin.command("amx_heal", access=Access.SLAY)'), 'def ${1:amx_heal}(admin: Player) -> None:');
  assert.equal(head('@plugin.command("/1v1")'), 'def ${1:cmd_1v1}(player: Player) -> None:');
  assert.equal(defSnippet('@plugin.command("x")').split('\n')[1], '\t${0:...}');
});

test('события: тип параметра — класс события', () => {
  assert.equal(head('@plugin.on(events.TakeDamage)'), 'def ${1:on_take_damage}(e: events.TakeDamage) -> None:');
  assert.equal(head('@plugin.on(events.PlayerSpawn, post=True)  # бонус'), 'def ${1:on_player_spawn}(e: events.PlayerSpawn) -> None:');
  assert.equal(head('@plugin.on(PutInServer)'), 'def ${1:on_put_in_server}(e: PutInServer) -> None:');
});

test('нативы, задачи, меню, форварды, cvar', () => {
  assert.match(defSnippet('@plugin.native'), /^def \$\{1:plugin_native\}\(\$\{2:player: Player\}\) -> \$\{3\|int,bool,float,str,None\|\}:/);
  assert.match(head('@plugin.native("vip_days")'), /\$\{1:vip_days\}/);
  assert.equal(head('@plugin.every(5)'), 'def ${1:tick}() -> None:');
  assert.equal(head('@shop.item("Аптечка", enabled=lambda p: p.alive)'), 'def ${1:on_select}(player: Player) -> None:');
  assert.equal(head('@shop.item("Armor")'), 'def ${1:armor}(player: Player) -> None:');
  assert.equal(head('@plugin.on_forward("vip_granted")'), 'def ${1:on_vip_granted}(*args: object) -> None:');
  assert.equal(head('@cfg.on_change("hp_bonus")'), 'def ${1:on_hp_bonus_change}(old: ${2:int}, new: ${2:int}) -> None:');
  assert.equal(head('@plugin.server_command("amx_reload_vips")'), 'def ${1:amx_reload_vips}() -> None:');
});

test('не декораторы amxpy и недописанные строки — ничего', () => {
  for (const line of ['@property', '@pytest.fixture', '@plugin.command("x",', '@plugin.on(', 'plugin.command("x")',
    '@app.route("/")', '@plugin.every', '@plugin.command(name)']) {
    assert.equal(defSnippet(line), null, line);
  }
});
