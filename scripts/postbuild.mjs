// Копирует статику в standalone-образ Next.js.
// standalone-сервер не берёт .next/static и public сам — их надо положить рядом.
// Скрипт кроссплатформенный (fs.cpSync), в отличие от `cp` в shell.
import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const standalone = join(root, '.next', 'standalone');

if (!existsSync(standalone)) {
  console.error('Нет .next/standalone — сборка не в standalone-режиме?');
  process.exit(1);
}

const pairs = [
  [join(root, '.next', 'static'), join(standalone, '.next', 'static')],
  [join(root, 'public'), join(standalone, 'public')],
];

for (const [from, to] of pairs) {
  if (!existsSync(from)) {
    continue;
  }
  mkdirSync(dirname(to), { recursive: true });
  cpSync(from, to, { recursive: true });
  console.log(`postbuild: ${from} -> ${to}`);
}

console.log('postbuild: готово');
