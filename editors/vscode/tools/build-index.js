#!/usr/bin/env node
// Индекс нативов и констант из .inc для расширения: node tools/build-index.js <папки с .inc>... > data/natives.json
'use strict';

const fs = require('fs');
const path = require('path');
const { parseInclude, parseConstants } = require('../incparse');

const constants = {};
const natives = {};
const files = process.argv.slice(2).flatMap((dir) =>
  fs.readdirSync(dir).filter((f) => f.endsWith('.inc')).sort().map((f) => path.join(dir, f)));
// константы — в два прохода: enum'ы ссылаются на #define из других файлов
for (let pass = 0; pass < 2; pass++) for (const file of files) parseConstants(fs.readFileSync(file, 'utf8'), constants);
for (const file of files) {
  for (const native of parseInclude(fs.readFileSync(file, 'utf8'), path.basename(file))) {
    delete native.line;
    natives[native.name] = native;
  }
}
process.stdout.write(JSON.stringify({ natives: Object.values(natives), constants }));
process.stderr.write(`natives: ${Object.keys(natives).length}, constants: ${Object.keys(constants).length}, files: ${files.length}\n`);
