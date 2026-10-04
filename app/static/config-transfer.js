/* Portable service configuration downloads and confirmed imports. */
(() => {
  const { readBounded, stringifyBounded, MAX_IMPORT_BYTES } = window.HostInputLimits;
  const { api, refreshAll, showToast, auth, registerCleanup } = window.HostDashboard;
  const exportModal = document.getElementById('config-export-modal');
  const importModal = document.getElementById('config-import-modal');
  const selection = document.getElementById('config-export-selection');
  const target = document.getElementById('config-export-target');
  const targetRow = document.getElementById('config-export-target-row');
  const downloadButton = document.getElementById('config-export-download');
  const fileInput = document.getElementById('import-services-file');
  const confirmButton = document.getElementById('config-import-confirm');
  const skipButton = document.getElementById('config-import-skip');
  let services = [];
  let pending = null;
  let importing = false;
  let generation = 0;
  const current = (epoch, attempt) => auth.authenticated && epoch === auth.epoch && attempt === generation;
  registerCleanup(() => {
    generation++; pending = null; importing = false; services = [];
    fileInput.value = ''; selection.value = 'all'; target.replaceChildren();
    confirmButton.disabled = false; skipButton.disabled = false;
    exportModal.close(); importModal.close();
  });

  function renderExportTargets() {
    const mode = selection.value;
    const previous = target.value;
    targetRow.hidden = !['category', 'service'].includes(mode);
    target.replaceChildren();
    if (mode === 'category') {
      [...new Set(services.map(service => service.category))].sort().forEach(category => target.add(new Option(category, category)));
    } else if (mode === 'service') {
      [...services].sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name))
        .forEach(service => target.add(new Option(`${service.display_name || service.name} · ${service.host_name || 'This host'}`, service.id)));
    }
    if ([...target.options].some(option => option.value === previous)) target.value = previous;
    downloadButton.disabled = !targetRow.hidden && !target.value;
  }

  async function download(mode, value = '') {
    downloadButton.disabled = true;
    const epoch = auth.epoch;
    try {
      const query = new URLSearchParams({ selection: mode, value });
      const config = await api(`/api/services/export?${query}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2) + '\n'], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url;
      const suffix = mode === 'service' ? value : mode === 'category' ? value : mode;
      link.download = `host-services-${suffix.replace(/[^a-zA-Z0-9_-]/g, '-')}-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast(`Exported ${config.services.length} service setting${config.services.length === 1 ? '' : 's'}.`);
    } catch (error) { if (!error.stale) showToast(error.message, 'error'); }
    finally { if (epoch === auth.epoch) renderExportTargets(); }
  }

  window.addEventListener('dashboard:inventory', event => { services = event.detail.services; renderExportTargets(); });
  window.addEventListener('dashboard:export-service', event => download('service', event.detail));
  document.getElementById('export-services').addEventListener('click', () => { selection.value = 'all'; renderExportTargets(); exportModal.showModal(); });
  selection.addEventListener('change', renderExportTargets);
  downloadButton.addEventListener('click', async () => {
    const epoch = auth.epoch;
    await download(selection.value, targetRow.hidden ? '' : target.value);
    if (epoch === auth.epoch) exportModal.close();
  });
  document.getElementById('config-export-close').addEventListener('click', () => exportModal.close());
  document.getElementById('config-export-cancel').addEventListener('click', () => exportModal.close());

  document.getElementById('import-services').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    fileInput.value = '';
    if (!file) return;
    const epoch = auth.epoch, attempt = ++generation;
    pending = null;
    try {
      if (file.size > MAX_IMPORT_BYTES) throw new Error('Configuration file is too large (maximum 1 MiB).');
      const config = JSON.parse(await readBounded(file.stream()));
      if (!current(epoch, attempt)) return;
      if (config?.format !== 'host-service-dashboard-services' || config?.version !== 1 || !Array.isArray(config.services)) {
        throw new Error('Unsupported service configuration format or version.');
      }
      const preview = await api('/api/services/import/preview', { method: 'POST', body: stringifyBounded(config) });
      if (!current(epoch, attempt)) return;
      pending = { config, previewToken: preview.preview_token, hasConflicts: preview.conflicts.length > 0 };
      document.getElementById('config-import-summary').textContent = `${file.name} · ${config.services.length} service${config.services.length === 1 ? '' : 's'}`;
      document.getElementById('config-import-preview').textContent = `${preview.added} new service${preview.added === 1 ? '' : 's'}, ${preview.updated} existing service${preview.updated === 1 ? '' : 's'}, ${preview.hosts_added} new host${preview.hosts_added === 1 ? '' : 's'}.`;
      const conflicts = document.getElementById('config-import-conflicts');
      conflicts.hidden = !preview.conflicts.length;
      conflicts.textContent = preview.conflicts.length ? `Overwrite ${preview.conflicts.length} existing service setting${preview.conflicts.length === 1 ? '' : 's'}? \n${preview.conflicts.map((item, index) => `${index + 1}. ${item.name} (${item.id})`).join('\n')}` : '';
      skipButton.hidden = !preview.conflicts.length;
      confirmButton.textContent = preview.conflicts.length ? 'Overwrite & import' : 'Import services';
      document.getElementById('config-import-warning').hidden = true;
      importModal.showModal();
    } catch (error) { if (current(epoch, attempt) && !error.stale) showToast(error.message, 'error'); }
  });

  const closeImport = () => { if (!importing) { generation++; importModal.close(); pending = null; } };
  document.getElementById('config-import-close').addEventListener('click', closeImport);
  document.getElementById('config-import-cancel').addEventListener('click', closeImport);
  importModal.addEventListener('cancel', event => { if (importing) event.preventDefault(); else { generation++; pending = null; } });

  async function runImport(overwrite) {
    if (!pending || importing) return;
    const epoch = auth.epoch, attempt = generation;
    const approved = pending;
    importing = true;
    confirmButton.disabled = true;
    skipButton.disabled = true;
    try {
      const result = await api(`/api/services/import?overwrite=${overwrite}`, { method: 'POST', headers: { 'X-Import-Preview': approved.previewToken }, body: stringifyBounded(approved.config) });
      if (!current(epoch, attempt)) return;
      importModal.close();
      pending = null;
      await refreshAll();
      if (!current(epoch, attempt)) return;
      await window.HostDashboard.refreshHosts();
      if (!current(epoch, attempt)) return;
      showToast(`Imported: ${result.added} added, ${result.updated} updated, ${result.skipped} skipped, ${result.hosts_added} hosts added.`);
      if (result.hosts_added) showToast('Verify new SSH host fingerprints in Hosts before connecting.');
    } catch (error) {
      if (!current(epoch, attempt) || error.stale) return;
      if (error.status === 409) pending = null;
      const warning = document.getElementById('config-import-warning');
      warning.textContent = error.message;
      warning.hidden = false;
      showToast(error.message, 'error');
    } finally {
      if (current(epoch, attempt)) {
        importing = false;
        confirmButton.disabled = !pending;
        skipButton.disabled = !pending;
      }
    }
  }
  confirmButton.addEventListener('click', () => runImport(Boolean(pending?.hasConflicts)));
  skipButton.addEventListener('click', () => runImport(false));
  renderExportTargets();
})();
