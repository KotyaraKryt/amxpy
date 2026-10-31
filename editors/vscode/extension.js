// amxpy для VS Code: после Enter на строке декоратора amxpy сам дописывает def с курсором на имени.
'use strict';

const vscode = require('vscode');
const { defSnippet } = require('./decorators');
const { templates, preview } = require('./completions');
const { neededNames, importEdit } = require('./imports');
const { findColors, colorText, cvarHints, colorPreview } = require('./features');
const fs = require('fs');
const path = require('path');
const { parseInclude, parseConstants, signature } = require('./incparse');
const { nativeMarkdown } = require('./nativedocs');
const { completionPrefix, nativeAt, callContext } = require('./callsite');

const isAmxpy = (doc) => doc.languageId === 'python' && /\bamxpy\b/.test(doc.getText());

// TextEdit для недостающих имён в from amxpy import ...
function importTextEdit(doc, snippet) {
  const edit = importEdit(doc.getText(), neededNames(snippet));
  if (!edit) return null;
  if (edit.replace) return vscode.TextEdit.replace(doc.lineAt(edit.line).range, edit.text);
  return vscode.TextEdit.insert(new vscode.Position(edit.line, 0), edit.text + '\n');
}

function onChange(event) {
  const editor = vscode.window.activeTextEditor;
  const doc = event.document;
  if (!editor || editor.document !== doc || doc.languageId !== 'python') return;
  if (event.reason === vscode.TextDocumentChangeReason.Undo || event.reason === vscode.TextDocumentChangeReason.Redo) return;
  if (event.contentChanges.length !== 1 || !vscode.workspace.getConfiguration('amxpy', doc).get('autoDef', true)) return;

  const change = event.contentChanges[0];
  if (change.rangeLength !== 0 || !/^\r?\n[ \t]*$/.test(change.text)) return; // ровно Enter с автоотступом
  const decorator = doc.lineAt(change.range.start.line);
  const line = change.range.start.line + 1;
  if (line >= doc.lineCount || doc.lineAt(line).text.trim() !== '') return;
  // def уже есть ниже (строку вставили между декоратором и функцией) — ничего не делаем
  for (let next = line + 1; next < doc.lineCount; next++) {
    const text = doc.lineAt(next).text.trim();
    if (!text) continue;
    if (/^(async\s+def\b|def\b|@)/.test(text)) return;
    break;
  }
  const snippet = defSnippet(decorator.text);
  if (!snippet || !isAmxpy(doc)) return;

  const version = doc.version;
  setImmediate(async () => {
    if (doc.version !== version || vscode.window.activeTextEditor !== editor) return;
    let target = line;
    const imports = importTextEdit(doc, snippet);
    if (imports) {
      const added = imports.newText.endsWith('\n') && imports.range.start.line <= line ? 1 : 0;
      const ok = await editor.edit((b) => (imports.range.isEmpty ? b.insert(imports.range.start, imports.newText)
        : b.replace(imports.range, imports.newText)), { undoStopBefore: true, undoStopAfter: false });
      if (!ok) return;
      target += added;
    }
    const position = new vscode.Position(target, doc.lineAt(target).text.length);
    editor.insertSnippet(new vscode.SnippetString(snippet), position, { undoStopBefore: !imports, undoStopAfter: true });
  });
}

// «@» в начале строки: декоратор amxpy вместе с def
const completionProvider = {
  provideCompletionItems(doc, position) {
    const prefix = doc.lineAt(position.line).text.slice(0, position.character);
    const m = /^(\s*)(@[\w.]*)$/.exec(prefix);
    if (!m || !isAmxpy(doc) || !vscode.workspace.getConfiguration('amxpy', doc).get('completions', true)) return [];
    const range = new vscode.Range(position.line, m[1].length, position.line, position.character);
    return templates(doc.getText()).map((t, i) => {
      const item = new vscode.CompletionItem(t.label, vscode.CompletionItemKind.Snippet);
      item.detail = t.detail;
      item.documentation = new vscode.MarkdownString(`${t.documentation}\n\n\`\`\`python\n${preview(t.snippet)}\n\`\`\``);
      item.insertText = new vscode.SnippetString(t.snippet);
      item.range = range;
      item.filterText = t.label;
      item.sortText = String(i).padStart(3, '0');
      const imports = importTextEdit(doc, t.snippet);
      if (imports) item.additionalTextEdits = [imports];
      return item;
    });
  },
};

const PYTHON = { language: 'python' };
const enabled = (doc, key) => isAmxpy(doc) && vscode.workspace.getConfiguration('amxpy', doc).get(key, true);

// Палитра для color=(r, g, b) у Hud и DirectorHud
const colorProvider = {
  provideDocumentColors(doc) {
    if (!enabled(doc, 'colors')) return [];
    return findColors(doc.getText()).map((c) => {
      const info = new vscode.ColorInformation(
        new vscode.Range(doc.positionAt(c.start), doc.positionAt(c.end)),
        new vscode.Color(c.rgba[0] / 255, c.rgba[1] / 255, c.rgba[2] / 255, c.rgba[3] / 255),
      );
      info.withAlpha = c.alpha;
      return info;
    });
  },
  provideColorPresentations(color, context) {
    const withAlpha = context.document.getText(context.range).split(',').length > 3;
    return [new vscode.ColorPresentation(colorText(color.red, color.green, color.blue, color.alpha, withAlpha))];
  },
};

// Полное имя cvar'а на сервере в конце строки: hp_bonus → vip_hp_bonus
const inlayProvider = {
  provideInlayHints(doc, range) {
    if (!enabled(doc, 'cvarNames')) return [];
    return cvarHints(doc.getText())
      .filter((h) => h.line >= range.start.line && h.line <= range.end.line)
      .map((h) => {
        const hint = new vscode.InlayHint(doc.lineAt(h.line).range.end, `cvar ${h.name}`);
        hint.paddingLeft = true;
        hint.tooltip = `Имя cvar'а на сервере: ${h.name}`;
        return hint;
      });
  },
};

// Как игрок увидит цветной текст чата или меню
const hoverProvider = {
  provideHover(doc, position) {
    if (!enabled(doc, 'colorPreview')) return null;
    const markdown = colorPreview(doc.lineAt(position.line).text, position.character);
    if (!markdown) return null;
    const content = new vscode.MarkdownString(markdown);
    content.supportHtml = true;
    return new vscode.Hover(content);
  },
};

// Кнопки над plugin = Plugin(...)
const codeLensProvider = {
  provideCodeLenses(doc) {
    if (!enabled(doc, 'codeLens')) return [];
    const lenses = [];
    doc.getText().split(/\r?\n/).forEach((line, i) => {
      if (!/^\s*\w+\s*(?::[^=]+)?=\s*(?:amxpy\.)?Plugin\(/.test(line)) return;
      const range = new vscode.Range(i, 0, i, 0);
      lenses.push(
        new vscode.CodeLens(range, { title: '$(cloud-upload) Установить на сервер', command: 'amxpy.deploy', arguments: [doc.uri] }),
        new vscode.CodeLens(range, { title: '$(list-unordered) Плагины на сервере', command: 'amxpy.list', arguments: [doc.uri] }),
      );
    });
    return lenses;
  },
};

async function python(uri) {
  const folder = uri && vscode.workspace.getWorkspaceFolder(uri);
  try {
    const path = await vscode.commands.executeCommand('python.interpreterPath', { workspaceFolder: folder && folder.uri.fsPath });
    if (typeof path === 'string' && path) return path;
  } catch { /* расширение Python не установлено */ }
  return 'python3';
}

// amxpy CLI задачей VS Code: вывод в терминале, ошибки amxpyc — в «Проблемах»
async function runAmxpy(uri, label, args) {
  uri = uri || (vscode.window.activeTextEditor && vscode.window.activeTextEditor.document.uri);
  const folder = (uri && vscode.workspace.getWorkspaceFolder(uri)) || (vscode.workspace.workspaceFolders || [])[0];
  const exec = new vscode.ProcessExecution(await python(uri), ['-m', 'amxpy', ...args], { cwd: folder && folder.uri.fsPath });
  const task = new vscode.Task({ type: 'amxpy', command: args[0] }, folder || vscode.TaskScope.Workspace, label, 'amxpy',
    exec, ['$amxpy', '$amxpy-warnings']);
  return vscode.tasks.executeTask(task);
}

// Нативы AMXX для amxx.call: встроенный индекс (AMXX + ReAPI) + свои .inc из настроек и проекта
const natives = { byName: new Map(), constants: {} };

async function loadNatives() {
  const byName = new Map();
  let constants = {};
  try {
    const bundled = JSON.parse(await fs.promises.readFile(path.join(__dirname, 'data', 'natives.json'), 'utf8'));
    for (const n of bundled.natives) byName.set(n.name, n);
    constants = bundled.constants;
  } catch { /* расширение собрано без индекса */ }
  const files = [];
  for (const entry of vscode.workspace.getConfiguration('amxpy').get('includePaths', [])) {
    const resolved = entry.replace(/^~(?=\/)/, process.env.HOME || '~');
    try {
      const stat = fs.statSync(resolved);
      if (stat.isDirectory()) files.push(...fs.readdirSync(resolved).filter((f) => f.endsWith('.inc')).map((f) => path.join(resolved, f)));
      else files.push(resolved);
    } catch { /* путь не найден */ }
  }
  const found = await vscode.workspace.findFiles('**/*.inc', '**/{node_modules,third_party,.git}/**', 2000);
  files.push(...found.map((u) => u.fsPath));
  const texts = files.map((file) => { try { return [file, fs.readFileSync(file, 'utf8')]; } catch { return null; } }).filter(Boolean);
  for (const [, text] of texts) parseConstants(text, constants);
  for (const [file, text] of texts) {
    for (const n of parseInclude(text, path.basename(file))) byName.set(n.name, { ...n, path: file });
  }
  natives.byName = byName;
  natives.constants = constants;
}

const nativeDoc = (n) => {
  const md = new vscode.MarkdownString(nativeMarkdown(n, natives.constants));
  md.isTrusted = false;
  return md;
};

// amxx.call("|  — имена нативов с документацией
const nativeCompletion = {
  provideCompletionItems(doc, position) {
    if (!enabled(doc, 'nativeHints')) return [];
    const before = doc.lineAt(position.line).text.slice(0, position.character);
    const prefix = completionPrefix(before);
    if (prefix === null) return [];
    const range = new vscode.Range(position.line, position.character - prefix.length, position.line, position.character);
    return [...natives.byName.values()].map((n) => {
      const item = new vscode.CompletionItem(n.name, vscode.CompletionItemKind.Function);
      item.detail = signature(n);
      item.range = range;
      item.native = n;
      return item;
    });
  },
  resolveCompletionItem(item) {
    if (item.native) item.documentation = nativeDoc(item.native);
    return item;
  },
};

// Наведение на имя натива в amxx.call("имя", ...)
const nativeHover = {
  provideHover(doc, position) {
    if (!enabled(doc, 'nativeHints')) return null;
    const at = nativeAt(doc.lineAt(position.line).text, position.character);
    const n = at && natives.byName.get(at.name);
    if (!n) return null;
    return new vscode.Hover(nativeDoc(n), new vscode.Range(position.line, at.start, position.line, at.end));
  },
};

// Параметры натива при вводе аргументов amxx.call("имя", |)
const nativeSignature = {
  provideSignatureHelp(doc, position) {
    if (!enabled(doc, 'nativeHints')) return null;
    const start = new vscode.Position(Math.max(0, position.line - 15), 0);
    const ctx = callContext(doc.getText(new vscode.Range(start, position)));
    const n = ctx && natives.byName.get(ctx.name);
    if (!n || ctx.argIndex < 0) return null;
    const label = signature(n);
    const info = new vscode.SignatureInformation(label, nativeDoc(n));
    let from = label.indexOf('(') + 1;
    info.parameters = n.params.map((p) => {
      const at = label.indexOf(p.raw, from);
      from = at + p.raw.length;
      return new vscode.ParameterInformation([at, at + p.raw.length], n.doc.params[p.varargs ? '...' : p.name] || undefined);
    });
    const help = new vscode.SignatureHelp();
    help.signatures = [info];
    help.activeSignature = 0;
    const vararg = n.params.findIndex((p) => p.varargs);
    help.activeParameter = vararg >= 0 && ctx.argIndex >= vararg ? vararg : Math.min(ctx.argIndex, n.params.length - 1);
    return help;
  },
};

function activate(context) {
  loadNatives();
  const watcher = vscode.workspace.createFileSystemWatcher('**/*.inc');
  watcher.onDidChange(loadNatives);
  watcher.onDidCreate(loadNatives);
  watcher.onDidDelete(loadNatives);
  context.subscriptions.push(
    watcher,
    vscode.workspace.onDidChangeConfiguration((e) => e.affectsConfiguration('amxpy.includePaths') && loadNatives()),
    vscode.workspace.onDidChangeTextDocument(onChange),
    vscode.languages.registerCompletionItemProvider(PYTHON, completionProvider, '@'),
    vscode.languages.registerColorProvider(PYTHON, colorProvider),
    vscode.languages.registerInlayHintsProvider(PYTHON, inlayProvider),
    vscode.languages.registerHoverProvider(PYTHON, hoverProvider),
    vscode.languages.registerCodeLensProvider(PYTHON, codeLensProvider),
    vscode.languages.registerCompletionItemProvider(PYTHON, nativeCompletion, '"', "'"),
    vscode.languages.registerHoverProvider(PYTHON, nativeHover),
    vscode.languages.registerSignatureHelpProvider(PYTHON, nativeSignature, '(', ','),
    vscode.commands.registerCommand('amxpy.deploy', (uri) => {
      uri = uri instanceof vscode.Uri ? uri : vscode.window.activeTextEditor && vscode.window.activeTextEditor.document.uri;
      return uri && runAmxpy(uri, 'установить на сервер', ['deploy', uri.fsPath]);
    }),
    vscode.commands.registerCommand('amxpy.deployAll', (uri) => runAmxpy(uri, 'установить все плагины', ['deploy'])),
    vscode.commands.registerCommand('amxpy.build', (uri) => runAmxpy(uri, 'собрать', ['build'])),
    vscode.commands.registerCommand('amxpy.list', (uri) => runAmxpy(uri, 'плагины на сервере', ['rcon', 'amxpy list'])),
    vscode.commands.registerCommand('amxpy.reload', async (uri) => {
      const name = await vscode.window.showInputBox({ prompt: 'Имя плагина (как в amxpy list)' });
      return name && runAmxpy(uri, `перезагрузить ${name}`, ['rcon', `amxpy reload ${name}`]);
    }),
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
