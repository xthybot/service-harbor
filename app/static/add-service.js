/* Register existing units or links; registration never creates or starts a unit. */
(() => {
  const form = document.querySelector('#add-service-form');
  const feedback = document.querySelector('#add-form-feedback');
  const fields = ['host_id', 'display_name', 'category', 'scope', 'description', 'unit', 'port', 'open_url'];
  let hosts = [], registering = false;
  const { api, showToast, refreshAll } = window.HostDashboard;
  const setText = (id, value) => { document.getElementById(id).textContent = value; };

  function values() {
    const result = Object.fromEntries(fields.map(name => [name, form.elements[name].value.trim()]));
    result.service_type = result.host_id === 'external' ? 'external' : result.host_id === 'local' ? 'local' : 'remote';
    if (result.service_type === 'external') result.host_id = '';
    result.port = result.port ? Number(result.port) : null;
    if (result.service_type === 'external') { result.scope = ''; result.unit = ''; }
    if (!result.unit) result.port = null;
    return { ...result, favorite: form.elements.favorite.checked };
  }

  function render() {
    window.HostDashboard.resizeTextareas();
    const draft = values();
    const external = draft.service_type === 'external';
    const remote = draft.service_type === 'remote';
    const managed = !external && !!draft.unit;
    const selectedHost = hosts.find(host => host.id === draft.host_id);
    document.getElementById('add-register').disabled = registering || (remote && (!selectedHost || (managed && !selectedHost.trusted)));
    setText('add-preview-host', external ? 'External website' : remote ? selectedHost?.name || 'Select a host' : 'This host');
    ['add-unit-field', 'add-scope-field'].forEach(id => {
      document.getElementById(id).hidden = external;
    });
    form.elements.unit.disabled = external;
    document.getElementById('add-port-field').hidden = external;
    form.elements.port.disabled = !managed;
    form.elements.unit.required = false;
    document.getElementById('add-preview-unit').hidden = !managed;
    form.elements.scope.disabled = external;
    form.elements.open_url.required = external;
    form.elements.unit.setCustomValidity('');
    form.elements.open_url.setCustomValidity('');
    setText('add-url-requirement', external ? '* Required' : 'Optional');
    setText('add-next-log', managed ? 'View status and live journal logs' : 'Open your configured website in a new tab');
    setText('add-next-control', managed ? 'Use Start / Stop / Restart controls' : 'Edit its settings in Services');
    document.querySelectorAll('[data-add-local-control]').forEach(item => { item.hidden = !managed; });
    setText('add-preview-name', draft.display_name || 'Your new service');
    setText('add-preview-mark', [...(draft.display_name || 'M')][0].toUpperCase());
    setText('add-preview-description', draft.description || 'Fill in the service details to preview its card.');
    setText('add-preview-category', draft.category);
    setText('add-preview-scope', external ? 'EXTERNAL LINK' : managed ? `${draft.scope.toUpperCase()} UNIT` : 'UNMANAGED');
    setText('add-preview-unit', draft.unit);
    document.getElementById('add-preview-port').hidden = !draft.port;
    setText('add-preview-port', draft.port ? `PORT ${draft.port}` : '');
    setText('add-preview-url', draft.open_url || (!managed ? 'No URL configured' : remote ? 'Set a remote website URL' : draft.port ? `This host:${draft.port}` : 'Set a service port or URL'));
    setText('add-preview-star', draft.favorite ? '★' : '☆');
    document.getElementById('add-preview-star').classList.toggle('is-favorite', draft.favorite);
    setText('add-scope-note', !managed ? 'Without a systemd unit, status monitoring, logs and controls are unavailable.' : draft.scope === 'system'
      ? 'System controls require exact sudo permissions configured by an administrator.'
      : remote ? 'Remote user services run under the SSH account. Journal access and controls use noninteractive SSH commands.' : 'Local user services run under the dashboard account.');
  }

  function validate() {
    const unit = form.elements.unit;
    const url = form.elements.open_url;
    unit.setCustomValidity(form.elements.host_id.value === 'external' || !unit.value.trim() || /^[A-Za-z0-9_][A-Za-z0-9_@:.\-]*\.(service|socket)$/.test(unit.value.trim())
      ? '' : 'Enter a systemd unit ending in .service or .socket.');
    url.setCustomValidity('');
    if (url.value.trim()) {
      try {
        const parsed = new URL(url.value.trim());
        if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) throw new Error();
      } catch { url.setCustomValidity('Enter an HTTP or HTTPS URL without embedded credentials.'); }
    }
    form.elements.display_name.setCustomValidity(form.elements.display_name.value.trim() ? '' : 'Enter a display name.');
    return form.reportValidity();
  }

  form.addEventListener('input', event => {
    event.target.setCustomValidity?.('');
    feedback.textContent = '';
    render();
  });
  form.addEventListener('change', render);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (registering || !validate()) return;
    registering = true; render();
    feedback.textContent = values().unit ? 'Checking the selected unit and registering the service…' : 'Registering the service…';
    try {
      const submitted = values();
      await api('/api/services', { method: 'POST', body: JSON.stringify(submitted) });
      showToast('Service added to Services.');
      form.reset(); render();
      feedback.textContent = submitted.unit && submitted.scope === 'system' ? '✓ Service added. System controls require exact sudo rules on its host. Registration does not start the service.' : '✓ Service added. Open Services to view it.';
      await refreshAll();
      await window.HostDashboard.refreshHosts();
    } catch (error) { feedback.textContent = error.message; showToast(error.message, 'error'); }
    finally { registering = false; render(); }
  });
  window.addEventListener('dashboard:hosts', event => {
    hosts = event.detail;
    const select = form.elements.host_id;
    const previous = select.value;
    const remoteGroup = document.createElement('optgroup');
    remoteGroup.label = 'Remote SSH hosts';
    if (!hosts.length) {
      const empty = new Option('Add a host in Hosts first', '');
      empty.disabled = true;
      remoteGroup.append(empty);
    }
    hosts.forEach(host => remoteGroup.append(new Option(`${host.name} · ${host.username}@${host.address}${host.trusted ? '' : ' · verify fingerprint first'}`, host.id)));
    select.replaceChildren(new Option('This host', 'local'), remoteGroup, new Option('External website · link only', 'external'));
    if (previous === 'external' || hosts.some(host => host.id === previous)) select.value = previous;
    render();
  });
  render();
})();
