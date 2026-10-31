'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { findColors, colorText, cvarHints, colorPreview } = require('../features');

test('цвета HUD: позиции кортежей и текст из палитры', () => {
  const src = 'info = Hud(y=0.25, color=(0, 200, 255), hold=4)\nb = DirectorHud(color2 = (1,2,3,128))\nx = (1, 2, 3)';
  const found = findColors(src);
  assert.deepEqual(found.map((c) => [src.slice(c.start, c.end), c.rgba]),
    [['(0, 200, 255)', [0, 200, 255, 255]], ['(1,2,3,128)', [1, 2, 3, 128]]]);
  assert.deepEqual(findColors('color=(300, 0, 0)'), []);
  assert.equal(colorText(1, 0.5, 0, 1, false), '(255, 128, 0)');
  assert.equal(colorText(0, 0, 0, 0.5, false), '(0, 0, 0, 128)');
});

test('имена cvar: префикс класса, name=, конец класса', () => {
  const src = [
    'class Settings(Config, prefix="vip_"):',
    '    hp_bonus: int = cvar(25, "HP")',
    '    secret: str = cvar("", name="vip_api_key")',
    '',
    '    def helper(self): ...',
    'x: int = cvar(1)',
    'class Plain(amxpy.Config):',
    '    on: bool = amxpy.cvar(True)',
  ].join('\n');
  assert.deepEqual(cvarHints(src), [
    { line: 1, name: 'vip_hp_bonus' }, { line: 2, name: 'vip_api_key' }, { line: 7, name: 'on' }]);
  assert.deepEqual(cvarHints('class A(Base):\n    x: int = cvar(1)'), []);
});

test('предпросмотр чата и меню', () => {
  const chat = 'player.print(f"!gПривет, !t{player.name}!y! <3")';
  const html = colorPreview(chat, 20);
  assert.match(html, /^\*\*Чат/);
  assert.match(html, /<span style="color:#7dd35b;">Привет, <\/span><span style="color:#ff5c5c;">\{player.name\}<\/span>/);
  assert.match(html, /&lt;3/);
  const menu = '@shop.item("Броня !y($1000)!R!dнет денег")';
  assert.match(colorPreview(menu, 15), /^\*\*Меню[\s\S]*color:#ffd42a;">\(\$1000\)[\s\S]*⇥/);
  assert.equal(colorPreview('print("обычный текст")', 9), null);
  assert.equal(colorPreview('player.print("!gx")', 3), null); // курсор не на строке
});
