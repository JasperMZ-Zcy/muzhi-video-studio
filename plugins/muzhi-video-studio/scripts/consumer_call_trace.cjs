#!/usr/bin/env node
// Read-only JSX call reachability from the registered Remotion Composition.
// Import presence alone is deliberately insufficient. This does not claim
// that a component is visible at every runtime frame or that its pixels work.
'use strict';
const fs = require('fs');
const path = require('path');

const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i]] = process.argv[i + 1];
const project = path.resolve(args['--project'] || '');
const runtime = path.resolve(args['--runtime'] || '');
const ts = require(path.join(runtime, 'node_modules', 'typescript'));
const entry = path.resolve(project, args['--entry'] || '');
const target = path.resolve(project, args['--target'] || '');
const wantedComposition = args['--composition'];
const wantedSymbol = args['--symbol'];
const inside = (file) => file === project || file.startsWith(project + path.sep);
const fail = (reason) => { process.stdout.write(JSON.stringify({passed: false, reason}) + '\n'); process.exit(1); };
if (!inside(entry) || !inside(target) || !fs.existsSync(entry) || !fs.existsSync(target) ||
    !wantedComposition || !wantedSymbol || !/^[A-Za-z_$][\w$]*$/.test(wantedSymbol)) {
  fail('project-local entry, target, composition id and exact component symbol required');
}

const cache = new Map();
const resolveFile = (from, spec) => {
  if (!spec.startsWith('.')) return null;
  const base = path.resolve(path.dirname(from), spec);
  for (const candidate of [base, base + '.tsx', base + '.ts', base + '.jsx', base + '.js',
    path.join(base, 'index.tsx'), path.join(base, 'index.ts')]) {
    if (inside(candidate) && fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return null;
};
const moduleAt = (file) => {
  if (cache.has(file)) return cache.get(file);
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true,
    file.endsWith('.tsx') || file.endsWith('.jsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const module = {file, source, defs: new Map(), imports: new Map()};
  cache.set(file, module);
  for (const node of source.statements) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const importedFile = resolveFile(file, node.moduleSpecifier.text);
      const clause = node.importClause;
      if (!importedFile || !clause) continue;
      if (clause.name) module.imports.set(clause.name.text, {file: importedFile, name: 'default'});
      const bindings = clause.namedBindings;
      if (bindings && ts.isNamedImports(bindings)) for (const item of bindings.elements) {
        module.imports.set(item.name.text, {file: importedFile, name: item.propertyName?.text || item.name.text});
      }
    }
    if (ts.isVariableStatement(node)) for (const decl of node.declarationList.declarations) {
      if (ts.isIdentifier(decl.name) && decl.initializer) module.defs.set(decl.name.text, decl.initializer);
    }
    if (ts.isFunctionDeclaration(node) && node.name) module.defs.set(node.name.text, node);
    if (ts.isExportAssignment(node) && ts.isIdentifier(node.expression)) module.imports.set('default', {file, name: node.expression.text});
  }
  return module;
};
const symbol = (file, name, seen = new Set()) => {
  const key = file + '#' + name;
  if (seen.has(key)) return null;
  seen.add(key);
  const module = moduleAt(file);
  if (module.defs.has(name)) return {file, name, node: module.defs.get(name), source: module.source};
  const imported = module.imports.get(name);
  return imported ? symbol(imported.file, imported.name, seen) : null;
};
const visit = (node, fn) => { fn(node); ts.forEachChild(node, (child) => visit(child, fn)); };
const register = [];
visit(moduleAt(entry).source, (node) => {
  if (ts.isCallExpression(node) && node.expression.getText() === 'registerRoot' &&
      node.arguments.length && ts.isIdentifier(node.arguments[0])) register.push(node.arguments[0].text);
});
if (register.length !== 1) fail('exactly one registerRoot(component) is required');
const root = symbol(entry, register[0]);
if (!root) fail('registered root component not resolved through project imports');
const compositions = [];
visit(root.node, (node) => {
  if (!ts.isJsxSelfClosingElement(node) && !ts.isJsxOpeningElement(node)) return;
  if (node.tagName.getText(root.source) !== 'Composition') return;
  let id = null, component = null, fps = null;
  for (const attr of node.attributes.properties) {
    if (!ts.isJsxAttribute(attr)) continue;
    if (attr.name.text === 'id' && attr.initializer && ts.isStringLiteral(attr.initializer)) id = attr.initializer.text;
    if (attr.name.text === 'component' && attr.initializer && ts.isJsxExpression(attr.initializer) &&
        attr.initializer.expression && ts.isIdentifier(attr.initializer.expression)) component = attr.initializer.expression.text;
    if (attr.name.text === 'fps' && attr.initializer && ts.isJsxExpression(attr.initializer) &&
        attr.initializer.expression && ts.isNumericLiteral(attr.initializer.expression)) fps = Number(attr.initializer.expression.text);
  }
  if (id && component) compositions.push({id, component, fps});
});
const composition = compositions.find((item) => item.id === wantedComposition);
if (!composition) fail('composition id not found inside registered root');
const first = symbol(root.file, composition.component);
if (!first) fail('composition component is not a resolved project component');
const queue = [{...first, chain: [composition.component]}];
const visited = new Set();
while (queue.length) {
  const current = queue.shift();
  const key = current.file + '#' + current.name;
  if (visited.has(key)) continue;
  visited.add(key);
  if (path.resolve(current.file) === target && current.name === wantedSymbol) {
    process.stdout.write(JSON.stringify({passed: true, composition_id: wantedComposition, fps: composition.fps,
      target: path.relative(project, target).replaceAll('\\', '/'), component_symbol: current.name,
      call_path: current.chain, evidence_level: 'static_jsx_reachability_plus_bound_frame',
      conditional_visibility_unverified: true,
      boundary: 'Exact JSX component symbol is reachable from the registered main Composition; conditional visibility at the selected frame and perceptual quality are unverified.'}) + '\n');
    process.exit(0);
  }
  const tags = new Set();
  visit(current.node, (node) => {
    if (!ts.isJsxSelfClosingElement(node) && !ts.isJsxOpeningElement(node)) return;
    const tag = node.tagName.getText(current.source);
    if (/^[A-Z][A-Za-z0-9_]*$/.test(tag)) tags.add(tag);
  });
  for (const tag of tags) {
    const next = symbol(current.file, tag);
    if (next) queue.push({...next, chain: [...current.chain, tag]});
  }
}
fail('exact target component symbol is not in the main Composition JSX call path');
