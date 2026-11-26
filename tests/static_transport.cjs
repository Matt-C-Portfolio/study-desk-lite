// Run with node tests/static_transport.cjs after scripts/build_static.py.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const site = path.resolve(process.argv[2] || 'site');
const routes = JSON.parse(fs.readFileSync(path.join(site, 'snapshot/routes.json')));
const adapter = fs.readFileSync(path.join(site, 'static.js'), 'utf8');

(async () => {
  let count = 0;
  for (const base of ['https://example.com/', 'https://example.com/study-desk-lite/']) {
    const requests = [];
    const document = {currentScript: {src: base + 'static.js'}, addEventListener() {}};
    const context = {URL, Request, Response, document, location: {hash: '#processed'},
      history: {}, STUDY_DESK_ROUTES: routes,
      fetch: async (url, options) => { requests.push({url, options}); return new Response('saved'); }};
    context.window = context;
    vm.runInNewContext(adapter, context);
    for (const [route, asset] of Object.entries(routes)) {
      assert(fs.statSync(path.join(site, asset)).isFile(), route);
      assert.equal(context.staticUrl(route), base + asset);
      assert.equal(await (await context.fetch(route)).text(), 'saved');
      assert.equal(requests.at(-1).url, base + asset);
      count++;
    }
    const before = requests.length;
    for (const method of ['POST', 'DELETE', 'PUT', 'PATCH']) {
      const response = await context.fetch('/api/urls', {method});
      assert.equal(response.status, 405);
      assert.match((await response.json()).error, /saved results/);
    }
    assert.equal(requests.length, before, 'Mutations reached the network');
    assert.equal((await context.fetch('/api/answers/missing')).status, 404);
    const id = Object.keys(routes).find(route => route.startsWith('/api/answers/')).split('/').at(-1);
    assert.equal(context.staticUrl('/?answer=' + id + '#ask'), base + '?answer=' + id + '#ask');
    assert.equal(context.staticUrl('/data/comparison-cohort.json'), base + 'data/comparison-cohort.json');
    assert.equal(context.staticUrl('https://www.youtube.com/watch?v=example'), 'https://www.youtube.com/watch?v=example');
    const requested = new Request(base + 'api/urls', {method: 'POST', body: '{}'});
    assert.equal((await context.fetch(requested)).status, 405);
  }
  console.log(`${count} saved route checks passed at root and project-subdirectory URLs; mutations blocked.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
