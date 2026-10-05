const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const runtime = path.resolve(process.argv[2] || path.join(__dirname, '..', 'node_modules'));
if (!runtime || !fs.existsSync(path.join(runtime, 'esbuild')) || !fs.existsSync(path.join(runtime, 'react')))
  throw new Error('Pass the existing Remotion node_modules path; this test installs nothing.');
const esbuild = require(path.join(runtime, 'esbuild'));
const React = require(path.join(runtime, 'react'));
const {renderToStaticMarkup} = require(path.join(runtime, 'react-dom/server'));

function load(name, loader = 'tsx') {
  const source = path.join(__dirname, '..', 'assets/semantic-actions/src', `${name}.${loader}`);
  const compiled = esbuild.transformSync(fs.readFileSync(source, 'utf8'), {loader, format: 'cjs'}).code;
  const mod = new Module(source, module);
  mod.filename = source;
  mod.paths = [runtime, ...Module._nodeModulePaths(path.dirname(source))];
  mod.require = (id) => id === 'react' ? React : Module.prototype.require.call(mod, id);
  mod._compile(compiled, source);
  return mod.exports;
}
const {RowCanvasTransfer, validateRowCanvasTransfer, transferPoseAt} = load('RowCanvasTransfer');
const {FocusHandoff, validateFocusHandoff} = load('FocusHandoff');
const {PolarContourMorph, validatePolarContourMorph, polarContourPathAt} = load('PolarContourMorph');
const {CountParticleFill, validateCountParticleFill} = load('CountParticleFill');
const {cameraAt, validateCameraMove, scrollBrakeAt, validateScrollBrake} = load('SceneCoordinate', 'ts');
const {validateStack, stackAt, validatePolyline, polylineAt} = load('ChartGeometry', 'ts');
const {cubicArcAt, validateCubicPath} = load('PathArc', 'ts');
const rect = (x, y, width, height) => ({x, y, width, height});

const transferA = {frame: 50, items: [
  {id: 'chapter-1', label: '数学错题', source: rect(35, 220, 250, 66),
    target: rect(310, 500, 290, 145), checkAt: 6, departAt: 20, arriveAt: 70},
  {id: 'chapter-2', label: '英语错题', source: rect(35, 310, 250, 66),
    target: rect(310, 670, 290, 145), checkAt: 16, departAt: 35, arriveAt: 86},
]};
assert.deepEqual(validateRowCanvasTransfer(transferA), []);
const transferMid = renderToStaticMarkup(React.createElement(RowCanvasTransfer, transferA));
assert.equal((transferMid.match(/data-object-id=/g) || []).length, 2);
assert.match(transferMid, /data-empty-slot="chapter-1"/);
assert.equal(transferPoseAt(transferA.items[0], 20).progress, 0);
assert.equal(transferPoseAt(transferA.items[0], 70).progress, 1);
const transferB = {frame: 76, width: 720, height: 1280, items: [
  {id: 'evidence', label: '来源页', source: rect(410, 120, 270, 80),
    target: rect(100, 680, 470, 220), checkAt: 4, departAt: 25, arriveAt: 73},
]};
assert.match(renderToStaticMarkup(React.createElement(RowCanvasTransfer, transferB)), /data-transfer-phase="target"/);
const visualTransfer = {...transferB, items: [{...transferB.items[0],
  visual: React.createElement('img', {src: '/project-bound-source.png', alt: '已哈希来源页'})}]};
const visualMarkup = renderToStaticMarkup(React.createElement(RowCanvasTransfer, visualTransfer));
assert.match(visualMarkup, /data-content-kind="project-visual"/);
assert.equal((visualMarkup.match(/project-bound-source\.png/g) || []).length, 1);
assert.ok(validateRowCanvasTransfer({...transferA, items: [transferA.items[0],
  {...transferA.items[1], id: 'chapter-1'}]}).length);

const focusA = {frame: 22, from: {id: 'overview', visual: React.createElement('b', null, '资料总览')},
  to: {id: 'line', visual: React.createElement('b', null, '目标原句')},
  events: {fromHoldUntil: 15, toStart: 18, fromGoneAt: 32, toSettledAt: 38}};
assert.deepEqual(validateFocusHandoff(focusA), []);
assert.match(renderToStaticMarkup(React.createElement(FocusHandoff, focusA)), /data-focus-phase="handoff"/);
const focusB = {...focusA, frame: 75, from: {id: 'question', visual: React.createElement('span', null, '题目')},
  to: {id: 'attempt', visual: React.createElement('span', null, '尝试作答')}};
assert.match(renderToStaticMarkup(React.createElement(FocusHandoff, focusB)), /data-focus-phase="to"/);
assert.ok(validateFocusHandoff({...focusA, events: {...focusA.events, toStart: 35}}).length);

const blobA = {frame: 28, center: {x: 360, y: 570},
  fromRadii: Array.from({length: 32}, (_, i) => 65 + 8 * Math.cos(i * Math.PI / 16)),
  toRadii: Array.from({length: 32}, (_, i) => 75 + 5 * Math.sin(i * Math.PI / 8)),
  events: {morphStart: 10, morphEnd: 40, readUntil: 65}, label: '一个对象改变外形'};
assert.deepEqual(validatePolarContourMorph(blobA), []);
assert.match(renderToStaticMarkup(React.createElement(PolarContourMorph, blobA)), /single-star-shaped-closed/);
const blobB = {...blobA, center: {x: 300, y: 400}, toRadii: blobA.toRadii.map((r) => r * .75)};
assert.notEqual(polarContourPathAt(blobA, 28), polarContourPathAt(blobB, 28));
assert.ok(validatePolarContourMorph({...blobA, toRadii: [10, 20]}).length);

const fillA = {frame: 100, columns: [{id: 'a', label: '甲组', value: 20},
  {id: 'b', label: '乙组', value: 30}], particleValue: 5, unit: '份', basis: '教学示意件数',
  dataStatus: 'illustrative', events: {fallStart: 10, fallEnd: 70, readUntil: 100}};
assert.deepEqual(validateCountParticleFill(fillA), []);
assert.match(renderToStaticMarkup(React.createElement(CountParticleFill, fillA)), /每粒 = 5份/);
const fillB = {...fillA, columns: [{id: 'morning', label: '上午', value: 12}],
  particleValue: 2, unit: '题', basis: '已核题数', dataStatus: 'measured',
  sourcePath: 'inputs/solved.json', sourceSha256: 'a'.repeat(64)};
assert.deepEqual(validateCountParticleFill(fillB), []);
assert.match(renderToStaticMarkup(React.createElement(CountParticleFill, fillB)), /data-count="6"/);
const sparseA = {...fillA, frame: 100, width: 720, height: 620, layout: 'unit-columns',
  columns: [{id: 'write', label: '写题', value: 60}, {id: 'correct', label: '订正', value: 45},
    {id: 'recall', label: '回忆', value: 30}, {id: 'gap', label: '查缺', value: 15}],
  particleValue: 5, unit: '分钟', basis: '教学设定 · 150分钟任务分配'};
assert.deepEqual(validateCountParticleFill(sparseA), []);
const sparseMarkup = renderToStaticMarkup(React.createElement(CountParticleFill, sparseA));
assert.match(sparseMarkup, /data-layout="unit-columns"/);
assert.match(sparseMarkup, /data-column-id="write" data-count="12"/);
const sparseCircles = [...sparseMarkup.matchAll(/<circle[^>]*cx="([^"]+)" cy="([^"]+)" r="([^"]+)"/g)];
assert.equal(sparseCircles.length, 30);
assert.equal(new Set(sparseCircles.slice(0, 12).map((match) => match[1])).size, 1);
assert.equal(new Set(sparseCircles.slice(0, 12).map((match) => match[2])).size, 12);
assert.ok(Number(sparseCircles[0][3]) >= 9);
assert.match(sparseMarkup, /x="127\.5" y="501\.6" text-anchor="middle" font-size="29"/);
const sparseB = {...sparseA, columns: [{id: 'read', label: '审题', value: 12},
  {id: 'calc', label: '运算', value: 8}, {id: 'concept', label: '概念', value: 6},
  {id: 'write', label: '表达', value: 4}], particleValue: 1, unit: '题',
  basis: '教学设定 · 示意错题簿30题'};
assert.deepEqual(validateCountParticleFill(sparseB), []);
assert.match(renderToStaticMarkup(React.createElement(CountParticleFill, sparseB)), /每粒 = 1题/);
assert.ok(validateCountParticleFill({...sparseA, height: 580}).length);
assert.ok(validateCountParticleFill({...sparseA, columns: [{...sparseA.columns[0], value: 65}]}).length);
assert.ok(validateCountParticleFill({...fillA, columns: [{id: 'bad', label: '不可整除', value: 23}]}).length);
assert.ok(validateCountParticleFill({...fillB, sourceSha256: undefined}).length);

const cameraA = {viewport: {width: 1000, height: 600}, target: rect(700, 160, 120, 80),
  fromScale: 1, toScale: 2, startFrame: 0, endFrame: 40};
assert.deepEqual(validateCameraMove(cameraA), []);
const camEnd = cameraAt(cameraA, 40);
assert.deepEqual(camEnd.project({x: 760, y: 200}), {x: 500, y: 300});
assert.equal(camEnd.pointer({x: 760, y: 200}, 24).screenSize, 24);
assert.equal(camEnd.pointer({x: 760, y: 200}, 24).innerSize, 12);
const cameraB = {...cameraA, viewport: {width: 800, height: 800},
  target: rect(170, 570, 120, 60), toScale: 2.5};
assert.deepEqual(cameraAt(cameraB, 40).project({x: 230, y: 600}), {x: 400, y: 400});
assert.ok(validateCameraMove({...cameraA, target: rect(700, 160, 500, 80)}).length);
const scrollA = {contentHeight: 1000, viewportHeight: 400, target: {y: 700, height: 60},
  startFrame: 0, brakeFrame: 24, settledFrame: 40, overshootPixels: 30};
assert.deepEqual(validateScrollBrake(scrollA), []);
assert.equal(scrollBrakeAt(scrollA, 40).offset, 530);
const scrollB = {contentHeight: 600, viewportHeight: 300, target: {y: 50, height: 80},
  startFrame: 0, brakeFrame: 20, settledFrame: 36};
assert.equal(scrollBrakeAt(scrollB, 36).offset, 0);
assert.ok(validateScrollBrake({...scrollA, viewportHeight: 40}).length);
const stackA = [{id: 'read', value: 20}, {id: 'practice', value: 30}, {id: 'review', value: 50}];
const stackB = [{id: 'class', value: 2}, {id: 'homework', value: 3}, {id: 'rest', value: 5}];
assert.deepEqual(validateStack(stackA, 100), []);
assert.equal(stackAt(stackA, 100, 200, .5).reduce((sum, x) => sum + x.length, 0), 100);
assert.equal(stackAt(stackB, 10, 150, 1).reduce((sum, x) => sum + x.length, 0), 150);
assert.ok(validateStack(stackA, 90).length);
const curveA = [{x: 0, y: 10}, {x: 1, y: 30}, {x: 2, y: 20}, {x: 3, y: 50}];
const curveB = [{x: 0, y: 0}, {x: 2, y: 4}, {x: 4, y: 8}, {x: 6, y: 12}];
assert.equal(polylineAt(curveA, .5).readout, 25);
assert.equal(polylineAt(curveB, .5).readout, 6);
assert.deepEqual(polylineAt(curveA, .5).endpoint, polylineAt(curveA, .5).drawn.at(-1));
assert.ok(validatePolyline([{x: 2, y: 5}, {x: 1, y: 8}]).length);
const arcA = [{x: 0, y: 0}, {x: 10, y: 0}, {x: 90, y: 10}, {x: 100, y: 100}];
const arcB = [{x: 0, y: 0}, {x: 0, y: 100}, {x: 20, y: 100}, {x: 100, y: 100}];
assert.deepEqual(validateCubicPath(arcA), []);
assert.ok(Math.abs(cubicArcAt(arcA, .5).arcFraction - .34) < .02);
assert.ok(Math.abs(cubicArcAt(arcB, .5).arcFraction - .53) < .02);
assert.ok(validateCubicPath(arcA.slice(0, 3)).length);
console.log('phase-r mechanisms: two semantic inputs + negative per component passed');
