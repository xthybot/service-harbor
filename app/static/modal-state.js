/* One focus/Escape owner for native dialogs, custom dialogs, and the drawer. */
(() => {
  const stack = [];
  const roots = () => [...document.querySelectorAll('dialog, .modal-backdrop, #detail-drawer')];
  const visible = node => node.tagName === 'DIALOG' ? node.open : node.id === 'detail-drawer' ? node.classList.contains('open') : !node.hidden;
  const controls = node => [...node.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]')].filter(item => !item.closest('[hidden]'));
  function sync() {
    for (let i = stack.length - 1; i >= 0; i--) if (!visible(stack[i].node)) {
      const [{focus}] = stack.splice(i, 1);
      if (focus?.isConnected && !focus.closest('[hidden]') && (!top() || top().contains(focus))) focus.focus({preventScroll: true});
    }
    for (const node of roots()) if (visible(node) && !stack.some(item => item.node === node)) {
      stack.push({node, focus: document.activeElement});
      if (!node.contains(document.activeElement)) controls(node)[0]?.focus();
    }
  }
  function top() { return stack.at(-1)?.node || null; }
  const cancelButtons = {'confirm-modal': 'confirm-cancel', 'manage-confirm-modal': 'manage-confirm-cancel', 'host-trust-modal': 'host-trust-cancel', 'rename-modal': 'rename-cancel', 'service-port-modal': 'service-port-close'};
  function close(node) {
    if (node.tagName === 'DIALOG') {
      if (node.dispatchEvent(new Event('cancel', {cancelable: true}))) node.close();
    } else if (node.id === 'detail-drawer') node.querySelector('[data-close-drawer]')?.click();
    else document.getElementById(cancelButtons[node.id])?.click();
    sync();
  }
  document.addEventListener('keydown', event => {
    sync(); const node = top(); if (!node) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); event.stopImmediatePropagation(); return; }
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopImmediatePropagation();
      const menu = node.querySelector('.tracking-menu:not([hidden])');
      if (menu) { menu.hidden = true; menu.previousElementSibling?.setAttribute('aria-expanded', 'false'); return; }
      close(node);
    }
    if (event.key === 'Tab') {
      const list = controls(node), first = list[0], last = list.at(-1);
      if (event.shiftKey && (document.activeElement === first || !node.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !node.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
    }
  }, true);
  new MutationObserver(sync).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['hidden', 'open', 'class']});
  window.HostModals = {top: () => {sync(); return top();}, sync};
})();
