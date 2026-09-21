// A fresh document gets a fresh nonce. Promotion must preserve it and the
// in-memory counter, text, history, scroll position and CDP target identity.
const title = new URL(location.href).searchParams.get('title');
if (title) {
  document.title = title;
  document.querySelector('#title')?.replaceChildren(title);
}
let storage;
try { void localStorage.length; storage = 'accessible'; }
catch (error) { storage = error.name; }
window.plicoProbe = {
  documentNonce: crypto.randomUUID(), counter: 0, events: [], storage,
  createdAt: Date.now(),
};
function snapshot() {
  return {
    ...window.plicoProbe,
    href: location.href,
    title: document.title,
    visibility: document.visibilityState,
    focused: document.hasFocus(),
    selection: getSelection()?.toString(),
    input: document.querySelector('#unsaved')?.value,
    historyLength: history.length,
    historyState: history.state,
    scrollY,
  };
}
function render() {
  document.querySelector('#probe').textContent = JSON.stringify(snapshot(), null, 2);
}
window.plicoSnapshot = snapshot;
for (const type of ['focus', 'blur', 'visibilitychange', 'pageshow', 'pagehide', 'popstate']) {
  addEventListener(type, () => {
    window.plicoProbe.events.push({type, at: performance.now(), visibility: document.visibilityState});
    window.plicoProbe.events = window.plicoProbe.events.slice(-100);
    render();
  });
}
document.querySelector('#increment')?.addEventListener('click', () => { ++window.plicoProbe.counter; render(); });
document.querySelector('#history')?.addEventListener('click', () => {
  history.pushState({nonce: window.plicoProbe.documentNonce}, '', '#retained'); render();
});
document.querySelector('#permission')?.addEventListener('click', () => {
  navigator.geolocation.getCurrentPosition(
    () => { window.plicoProbe.permission = 'allowed'; render(); },
    error => { window.plicoProbe.permission = error.code; render(); });
});
document.querySelector('#unsaved')?.addEventListener('input', render);
addEventListener('beforeunload', event => {
  if (document.querySelector('#beforeunload')?.checked) {
    event.preventDefault(); event.returnValue = '';
  }
});
render();
