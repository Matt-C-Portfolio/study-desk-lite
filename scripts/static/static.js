/* Read-only transport for the generated site; the local application's code is unchanged. */
(() => {
  const base = new URL('.', document.currentScript.src);
  const routes = window.STUDY_DESK_ROUTES;
  const nativeFetch = window.fetch.bind(window);
  const logicalPath = (url) => {
    if (url.origin !== base.origin) return null;
    const path = url.pathname.startsWith(base.pathname)
      ? '/' + url.pathname.slice(base.pathname.length) : url.pathname;
    return path;
  };
  window.staticUrl = (input) => {
    const url = new URL(input, base);
    const path = logicalPath(url);
    if (routes[path]) return new URL(routes[path], base).href;
    if (path?.startsWith('/data/')) return new URL(path.slice(1), base).href;
    if (path === '/' && url.searchParams.has('answer'))
      return new URL('./' + url.search + url.hash, base).href;
    return input;
  };
  window.fetch = (input, options = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, base);
    const path = logicalPath(url);
    if (path?.startsWith('/api/')) {
      const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (!['GET', 'HEAD'].includes(method))
        return Promise.resolve(new Response(JSON.stringify({error: 'This demo contains saved results. Run the local app to create new results.'}), {status: 405, headers: {'Content-Type': 'application/json'}}));
      if (!routes[path])
        return Promise.resolve(new Response(JSON.stringify({error: 'No saved result is available for this request.'}), {status: 404, headers: {'Content-Type': 'application/json'}}));
    }
    return nativeFetch(window.staticUrl(url.href), options);
  };
  if (!location.hash) history.replaceState(null, '', location.search + '#processed');
  document.addEventListener('DOMContentLoaded', () => {
    const fixed = '#submit,#choose-captions,#choose-local,#study-generate,#study-five,#study-all-local';
    function lockControls() {
      for (const button of document.querySelectorAll(fixed + ',#library-rows button,#graph-view button,#ask-view button')) {
        if (button.matches(fixed) || /^(Remove|Build |Rebuild |Resume |Ask all four)/.test(button.textContent.trim())) {
          if (!button.disabled) button.disabled = true;
          if (!button.hasAttribute('data-static-disabled')) {
            button.setAttribute('data-static-disabled', '');
            button.title = 'Available in the local app. This website displays recorded results.';
          }
        }
      }
    }
    lockControls();
    new MutationObserver(lockControls).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['disabled']});
    for (const form of document.querySelectorAll('#intake,#ask-view form'))
      form.addEventListener('submit', event => {event.preventDefault(); event.stopImmediatePropagation();}, true);
    const ask = document.querySelector('#ask-view > section');
    ask.querySelector('h2').textContent = 'Saved answers';
    ask.querySelector('p').textContent = 'Open an answer from the comparison to see its generated text, sources, timing, and status.';
    const link = document.createElement('a');
    link.href = '#answer-comparison';
    link.textContent = 'Browse all 1,920 recorded attempts';
    ask.querySelector('p').append(' ', link);
    const titles = () => {
      if (location.hash === '#intake') document.querySelector('#page-title').textContent = 'Saved guide runs';
      if (location.hash === '#ask') document.querySelector('#page-title').textContent = 'Saved answer';
    };
    window.addEventListener('hashchange', titles);
    titles();
    const presetHint = document.querySelector('#preset-hint');
    presetHint.textContent = 'Choose a lecture to browse all recorded guide attempts.';
    const stepTitle = document.querySelector('#step-one-title');
    stepTitle.textContent = 'Choose a saved lecture';
    stepTitle.nextElementSibling.textContent = 'The same ten lectures used throughout the project.';
  });
})();
