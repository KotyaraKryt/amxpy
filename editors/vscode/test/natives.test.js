'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parseInclude, parseConstants, parseParam, signature } = require('../incparse');
const { pythonExample, nativeMarkdown } = require('../nativedocs');
const { completionPrefix, nativeAt, callContext } = require('../callsite');

const INC = `
#define MAX_PLAYERS 32
#define print_chat 3
enum GiveType { GT_APPEND, GT_REPLACE, GT_DROP_AND_REPLACE };
enum { Flag_A = (1<<0), Flag_B = (1<<1), Flag_C };

/**
 * Retrieves the name of a client or the server.
 *
 * @param index     Client index, or 0 to retrieve the server hostname
 * @param name      Buffer to copy name to
 * @param len       Maximum buffer size
 *
 * @return          Number of cells written to buffer
 */
native get_user_name(index, name[], len);

/*
* Gives the player an item.
*
* @param index      Client index
* @param pszName    Item classname
* @param type       Look at the enums with name GiveType
*
* @return           Index of entity if successfull, -1 otherwise
*/
native rg_give_item(const index, const pszName[], GiveType:type = GT_APPEND);

native Float:entity_range(ida, idb);
native get_players(players[MAX_PLAYERS], &num, const flags[]="", const team[]="");
native client_print(index, type, const message[], any:...);
// native commented_out(a);
stock helper(a) { return a; }
`;

test('нативы, параметры и документация из .inc', () => {
  const natives = parseInclude(INC, 'test.inc');
  assert.deepEqual(natives.map((n) => n.name), ['get_user_name', 'rg_give_item', 'entity_range', 'get_players', 'client_print']);
  const [name, give, range] = natives;
  assert.equal(signature(name), 'native get_user_name(index, name[], len)');
  assert.equal(name.doc.text, 'Retrieves the name of a client or the server.');
  assert.equal(name.doc.params.len, 'Maximum buffer size');
  assert.equal(give.doc.returns, 'Index of entity if successfull, -1 otherwise');  // комментарий /* */ ReAPI
  assert.equal(range.tag, 'Float');
  assert.deepEqual(parseParam('&Float:value'), { raw: '&Float:value', name: 'value', tag: 'Float', ref: true, const: false, dims: [], default: null, varargs: false });
  assert.deepEqual(parseParam('const Float:vec[3] = {0.0, 0.0, 0.0}').dims, ['3']);
  assert.equal(parseParam('any:...').varargs, true);
});

test('константы: #define, enum с автонумерацией и (1<<n)', () => {
  const c = parseConstants(INC);
  assert.equal(c.MAX_PLAYERS, 32);
  assert.deepEqual([c.GT_APPEND, c.GT_REPLACE, c.GT_DROP_AND_REPLACE], [0, 1, 2]);
  assert.deepEqual([c.Flag_A, c.Flag_B, c.Flag_C], [1, 2, 3]);
});

test('пример вызова из Python: буферы, ссылки, массивы, значения по умолчанию', () => {
  const natives = Object.fromEntries(parseInclude(INC, 'test.inc').map((n) => [n.name, n]));
  const constants = parseConstants(INC);
  assert.equal(pythonExample(natives.get_user_name, constants).code,
    'name = amxx.String(64)\namxx.call("get_user_name", player, name, 63)\n# результат: name.value');
  assert.equal(pythonExample(natives.rg_give_item, constants).code, 'result = amxx.call("rg_give_item", player, "...", 0)');
  assert.equal(pythonExample(natives.entity_range, constants).code, 'amxx.call_float("entity_range", ida, idb)');
  assert.equal(pythonExample(natives.get_players, constants).code,
    'players = amxx.Array(32)\nnum = amxx.Ref()\namxx.call("get_players", players, num, "", "")\n# результат: players.values, num.value');
  assert.match(pythonExample(natives.client_print, constants).code, /amxx\.Ref\(0\)\)\n# any:\.\.\./);
  const md = nativeMarkdown(natives.rg_give_item, constants);
  assert.match(md, /```pawn\nnative rg_give_item\(const index, const pszName\[\], GiveType:type = GT_APPEND\)\n```/);
  assert.match(md, /- `type` — Look at the enums with name GiveType \*\(по умолчанию GT_APPEND\)\*/);
  assert.match(md, /#### Из Python\n```python\nresult = amxx\.call\("rg_give_item"/);
});

test('где курсор: имя, наведение, номер параметра', () => {
  assert.equal(completionPrefix('    amxx.call("get_us'), 'get_us');
  assert.equal(completionPrefix("x = amxx.call_float('"), '');
  assert.equal(completionPrefix('print("get_us'), null);
  const line = 'n = amxx.call("get_user_name", player, name, 31)';
  assert.deepEqual(nativeAt(line, 20), { name: 'get_user_name', start: 15, end: 28 });
  assert.equal(nativeAt(line, 35), null);
  assert.deepEqual(callContext('amxx.call("get_user_name", player, '), { name: 'get_user_name', argIndex: 1 });
  assert.deepEqual(callContext('amxx.call("rg_give_item", player, f("a, b", (1, 2)), '), { name: 'rg_give_item', argIndex: 2 });
  assert.deepEqual(callContext('amxx.call(\n    "get_user_origin",\n    player,\n    '), { name: 'get_user_origin', argIndex: 1 });
  assert.equal(callContext('amxx.call("x", 1)\nfoo('), null);
  assert.deepEqual(callContext('amxx.call("get_user_name"'), { name: 'get_user_name', argIndex: -1 });
});
