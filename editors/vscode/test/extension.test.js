'use strict';
// Обвязка с поддельным API VS Code: Enter после декоратора → insertSnippet в новую строку
const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

class Position { constructor(line, character) { this.line = line; this.character = character; } }
class Range {
  constructor(a, b, c, d) {
    if (typeof a === 'object') { this.start = a; this.end = b; } else { this.start = new Position(a, b); this.end = new Position(c, d); }
  }
  get isEmpty() { return this.start.line === this.end.line && this.start.character === this.end.character; }
}
const TextEdit = {
  insert: (pos, newText) => ({ range: new Range(pos.line, pos.character, pos.line, pos.character), newText }),
  replace: (range, newText) => ({ range, newText }),
};
const listeners = [];
const inserted = [];
const edits = [];
let provider = null;
const registered = { commands: [], hovers: [], completions: [] };
const fake = {
  Position,
  Range,
  TextEdit,
  CompletionItem: class { constructor(label) { this.label = label; } },
  MarkdownString: class { constructor(value) { this.value = value; } },
  languages: {
    registerCompletionItemProvider: (sel, p) => { registered.completions.push(p); provider = provider || p; return { dispose() {} }; },
    registerColorProvider: (sel, p) => { registered.color = p; return { dispose() {} }; },
    registerInlayHintsProvider: (sel, p) => { registered.inlay = p; return { dispose() {} }; },
    registerHoverProvider: (sel, p) => { registered.hovers.push(p); return { dispose() {} }; },
    registerSignatureHelpProvider: (sel, p) => { registered.signature = p; return { dispose() {} }; },
    registerCodeLensProvider: (sel, p) => { registered.lens = p; return { dispose() {} }; },
  },
  commands: { registerCommand: (name) => { registered.commands.push(name); return { dispose() {} }; } },
  InlayHint: class { constructor(position, label) { this.position = position; this.label = label; } },
  Hover: class { constructor(contents) { this.contents = contents; } },
  CodeLens: class { constructor(range, command) { this.range = range; this.command = command; } },
  SignatureInformation: class { constructor(label, documentation) { this.label = label; this.documentation = documentation; } },
  ParameterInformation: class { constructor(label, documentation) { this.label = label; this.documentation = documentation; } },
  SignatureHelp: class {},
  CompletionItemKind: { Snippet: 27, Function: 3 },
  SnippetString: class { constructor(value) { this.value = value; } },
  TextDocumentChangeReason: { Undo: 1, Redo: 2 },
  window: { activeTextEditor: null },
  workspace: {
    onDidChangeTextDocument: (fn) => { listeners.push(fn); return { dispose() {} }; },
    onDidChangeConfiguration: () => ({ dispose() {} }),
    findFiles: async () => [],
    createFileSystemWatcher: () => ({ onDidChange() {}, onDidCreate() {}, onDidDelete() {}, dispose() {} }),
    getConfiguration: () => ({ get: (key, def) => def }),
  },
};
const load = Module._load;
Module._load = (request, ...rest) => (request === 'vscode' ? fake : load(request, ...rest));
require('../extension').activate({ subscriptions: [] });

function press(lines, decoratorLine, options = {}) {
  const doc = {
    languageId: 'python',
    version: 1,
    lineCount: lines.length,
    lineAt: (i) => ({ text: lines[i], range: new Range(i, 0, i, lines[i].length) }),
    getText: () => lines.join('\n'),
  };
  const editor = {
    document: doc,
    insertSnippet: (s, pos) => inserted.push({ s: s.value, pos }),
    edit: async (fn) => { fn({ insert: (p, t) => edits.push({ p, t }), replace: (r, t) => edits.push({ r, t }) }); return true; },
  };
  fake.window.activeTextEditor = editor;
  inserted.length = 0;
  edits.length = 0;
  const change = { rangeLength: 0, text: '\n' + (options.indent || ''), range: { start: { line: decoratorLine } } };
  listeners[0]({ document: doc, reason: options.reason, contentChanges: [change] });
  return (async () => {  // ждём вставку до секунды; «ничего не вставлено» — после 50 мс тишины
    for (let waited = 0; waited < 1000 && !inserted.length; waited += 5) {
      await new Promise((r) => setTimeout(r, 5));
      if (!inserted.length && waited >= 50) break;
    }
    return [...inserted];
  })();
}

test('Enter после @plugin.command вставляет def и дописывает Player в импорт', async () => {
  const lines = ['from amxpy import Plugin', '@plugin.command("test")', '    ', ''];
  const [hit] = await press(lines, 1, { indent: '    ' });
  assert.equal(hit.s.split('\n')[0], 'def ${1:test}(player: Player) -> None:');
  assert.deepEqual([hit.pos.line, hit.pos.character], [2, 4]);
  assert.deepEqual(edits.map((e) => e.t), ['from amxpy import Player, Plugin']);
});

test('автодополнение по @ в начале строки', () => {
  const lines = ['from amxpy import Plugin, Player', 'plugin = Plugin("X")', '@co'];
  const doc = {
    languageId: 'python',
    lineAt: (i) => ({ text: lines[i], range: new Range(i, 0, i, lines[i].length) }),
    getText: () => lines.join('\n'),
  };
  const items = provider.provideCompletionItems(doc, new Position(2, 3));
  const command = items.find((i) => i.label === '@plugin.command');
  assert.ok(command.insertText.value.startsWith('@plugin.command("/${1:name}"'));
  assert.deepEqual([command.range.start.character, command.range.end.character], [0, 3]);
  assert.equal(command.additionalTextEdits, undefined); // Player уже импортирован
  assert.equal(items.find((i) => i.label === '@plugin.on').additionalTextEdits[0].newText,
    'from amxpy import Player, Plugin, events');
  assert.deepEqual(provider.provideCompletionItems(doc, new Position(1, 6)), []); // не в начале строки
});

test('не срабатывает: def уже есть, undo, файл без amxpy, не декоратор', async () => {
  assert.deepEqual(await press(['import amxpy', '@plugin.command("a")', '', 'def a(p): ...'], 1), []);
  assert.deepEqual(await press(['import amxpy', '@plugin.command("a")', ''], 1, { reason: 1 }), []);
  assert.deepEqual(await press(['import flask', '@plugin.command("a")', ''], 1), []);
  assert.deepEqual(await press(['import amxpy', 'x = 1', ''], 1), []);
});

test('регистрация: цвета, имена cvar, предпросмотр, кнопки, команды', () => {
  assert.ok(registered.color && registered.inlay && registered.hovers.length === 2 && registered.lens && registered.signature);
  assert.deepEqual(registered.commands.sort(),
    ['amxpy.build', 'amxpy.deploy', 'amxpy.deployAll', 'amxpy.list', 'amxpy.reload']);
  const lines = ['from amxpy import Config, Plugin, cvar', 'plugin = Plugin("X")',
    'class S(Config, prefix="x_"):', '    hp: int = cvar(1)', 'player.print("!gok")'];
  const doc = {
    languageId: 'python',
    lineAt: (i) => ({ text: lines[i], range: new Range(i, 0, i, lines[i].length) }),
    getText: () => lines.join('\n'),
  };
  const lenses = registered.lens.provideCodeLenses(doc);
  assert.deepEqual(lenses.map((l) => [l.range.start.line, l.command.command]), [[1, 'amxpy.deploy'], [1, 'amxpy.list']]);
  const hints = registered.inlay.provideInlayHints(doc, new Range(0, 0, 4, 0));
  assert.deepEqual(hints.map((h) => [h.position.line, h.label]), [[3, 'cvar x_hp']]);
  const hover = registered.hovers[0].provideHover(doc, new Position(4, 16));
  assert.ok(hover.contents.supportHtml && hover.contents.value.includes('color:#7dd35b'));
});

test('нативы amxx.call: автодополнение, наведение, параметры из встроенного индекса', async () => {
  await new Promise((r) => setTimeout(r, 30));  // loadNatives() — асинхронно
  const lines = ['from amxpy import amxx', 'amxx.call("get_user_na', 'amxx.call("get_user_name", player, '];
  const doc = {
    languageId: 'python',
    lineAt: (i) => ({ text: lines[i], range: new Range(i, 0, i, lines[i].length) }),
    getText: (range) => {
      if (!range) return lines.join('\n');
      const part = lines.slice(range.start.line, range.end.line + 1);
      part[part.length - 1] = part[part.length - 1].slice(0, range.end.character);
      part[0] = part[0].slice(range.start.character);
      return part.join('\n');
    },
  };
  const items = registered.completions[1].provideCompletionItems(doc, new Position(1, lines[1].length));
  const item = items.find((i) => i.label === 'get_user_name');
  assert.equal(item.detail, 'native get_user_name(index, name[], len)');
  assert.ok(items.length > 1000);
  registered.completions[1].resolveCompletionItem(item);
  assert.match(item.documentation.value, /amxx\.String\(64\)/);
  const hover = registered.hovers[1].provideHover(doc, new Position(2, 15));
  assert.match(hover.contents.value, /Retrieves the name of a client/);
  const help = registered.signature.provideSignatureHelp(doc, new Position(2, lines[2].length));
  assert.equal(help.activeParameter, 1);
  assert.equal(help.signatures[0].parameters[1].documentation, 'Buffer to copy name to');
});
