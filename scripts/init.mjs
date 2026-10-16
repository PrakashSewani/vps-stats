#!/usr/bin/env node
/**
 * Renames this template in place — replaces the slug and the title everywhere they appear:
 * README, docs, skills, and any config the scaffold added later.
 *
 * Usage:
 *   node scripts/init.mjs --name episode-roulette --title "Episode Roulette"
 *   node scripts/init.mjs --name episode-roulette --dry-run
 */
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const SLUG = 'template-open-source-tool';
const TITLE = 'Open Source Tool';

const SKIP_DIRS = new Set([
  '.git',
  '.next',
  '.output',
  '.venv',
  '.wrangler',
  '.wxt',
  '__pycache__',
  'build',
  'coverage',
  'dist',
  'node_modules',
  'out',
  'target',
  'venv',
  'vendor',
]);

const TEXT_EXTENSIONS = new Set([
  '.cjs',
  '.css',
  '.go',
  '.html',
  '.js',
  '.json',
  '.jsx',
  '.lock',
  '.md',
  '.mjs',
  '.php',
  '.py',
  '.rb',
  '.rs',
  '.sh',
  '.sql',
  '.svg',
  '.toml',
  '.ts',
  '.tsx',
  '.txt',
  '.yaml',
  '.yml',
]);

const TEXT_NAMES = new Set([
  '.editorconfig',
  '.env.example',
  '.gitattributes',
  '.gitignore',
  'LICENSE',
]);

const root = resolve(import.meta.dirname, '..');
const args = parseArgs(process.argv.slice(2));

if (!args.name) {
  console.error(
    'Usage: node scripts/init.mjs --name <kebab-case-name> [--title "Display Title"] [--dry-run]',
  );
  process.exit(1);
}
if (!/^[a-z0-9][a-z0-9-]*$/.test(args.name)) {
  console.error(`Invalid name "${args.name}" — use lowercase letters, numbers, and hyphens.`);
  process.exit(1);
}

const slug = args.name;
const title = args.title ?? slug.replace(/-+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

let filesChanged = 0;
let replacementCount = 0;

walk(root);

if (filesChanged === 0) {
  console.log(`Nothing to do — no occurrences of "${SLUG}" or "${TITLE}" found.`);
  process.exit(0);
}

console.log(
  `${args.dryRun ? '[dry run] ' : ''}Renamed in ${filesChanged} file(s), ${replacementCount} replacement(s):`,
);
console.log(`  ${SLUG} -> ${slug}`);
console.log(`  ${TITLE} -> ${title}`);

if (!args.dryRun) {
  console.log('\nNext: open an AI session in this repo and say "bootstrap this project".');
  console.log('The agent will ask the questions that matter, choose the stack, resolve current');
  console.log('versions live, and scaffold it (see AGENTS.md and the project-bootstrap skill).');
  console.log('You can delete scripts/init.mjs - it has done its job.');
}

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry) || entry === 'init.mjs') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full);
      continue;
    }
    if (!isTextFile(entry)) continue;

    const before = readFileSync(full, 'utf8');
    const matches = countMatches(before);
    if (matches === 0) continue;

    if (!args.dryRun) {
      writeFileSync(full, before.split(SLUG).join(slug).split(TITLE).join(title));
    }
    filesChanged += 1;
    replacementCount += matches;
  }
}

function isTextFile(name) {
  if (TEXT_NAMES.has(name)) return true;
  const dot = name.lastIndexOf('.');
  return dot > 0 && TEXT_EXTENSIONS.has(name.slice(dot));
}

function countMatches(text) {
  let count = 0;
  for (const token of [SLUG, TITLE]) {
    let index = text.indexOf(token);
    while (index !== -1) {
      count += 1;
      index = text.indexOf(token, index + token.length);
    }
  }
  return count;
}

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--name') parsed.name = argv[++i];
    else if (arg === '--title') parsed.title = argv[++i];
    else if (arg === '--dry-run') parsed.dryRun = true;
  }
  return parsed;
}
