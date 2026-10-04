/* Manual network ports are checked from the dashboard host, without SSH. */
(() => {
  const $ = selector => document.querySelector(selector);
  const { api, refreshAll, showToast, resizeTextareas } = window.HostDashboard;
  const dialog = $('#manual-port-modal');
  const form = $('#manual-port-form');
  const confirmDialog = $('#manual-port-confirm');
  let records = [];
  let editId = null;
  let editGeneration = 0;
  let checkedSignature = '';
  let checkedResult = null;
  let confirmResolve = null;

  function payload() {
    return {
      name: $('#manual-port-name').value.trim(),
      source: $('#manual-port-source').value.trim(),
      host_id: $('#manual-port-host').value,
      address: $('#manual-port-host').value === 'custom' ? $('#manual-port-address').value.trim() : '',
      port: Number($('#manual-port-number').value)
    };
  }

  function resetCheck() {
    checkedSignature = '';
    checkedResult = null;
    $('#manual-port-check-result').textContent = '○ Not checked';
    $('#manual-port-check-result').className = 'manual-port-check-result';
    $('#manual-port-save').disabled = true;
  }

  function updateAddress() {
    const custom = $('#manual-port-host').value === 'custom';
    $('#manual-port-address-row').hidden = !custom;
    $('#manual-port-address').required = custom;
    resetCheck();
  }

  async function open(record = null) {
    const generation = ++editGeneration;
    try {
      const result = await api('/api/hosts');
      if (generation !== editGeneration) return;
      const select = $('#manual-port-host');
      select.innerHTML = '<option value="local">This host</option>';
      for (const host of result.hosts || []) select.add(new Option(`${host.name} · ${host.address}`, host.id));
      select.add(new Option('Other IP / hostname', 'custom'));
      editId = record?.id || null;
      document.querySelector('#manual-port-modal .tracking-control')?.remove();
      if (record) window.HostTracking?.bind($('#manual-port-close'), 'manual-port', record.id);
      $('#manual-port-title').textContent = record ? 'Edit port' : 'Add port';
      $('#manual-port-delete').hidden = !record;
      $('#manual-port-name').value = record?.name || '';
      $('#manual-port-source').value = record?.source || '';
      $('#manual-port-number').value = record?.port || '';
      const knownHost = record && [...select.options].some(option => option.value === record.host_id);
      select.value = record ? knownHost ? record.host_id : 'custom' : 'local';
      $('#manual-port-address').value = record?.address || '';
      updateAddress();
      dialog.showModal();
      resizeTextareas();
      $('#manual-port-name').focus();
    } catch (error) { showToast(error.message, 'error'); }
  }

  function settleConfirm(accepted) {
    if (confirmDialog.open) confirmDialog.close();
    confirmResolve?.(accepted);
    confirmResolve = null;
  }

  function confirm(title, copy, accept) {
    $('#manual-port-confirm-title').textContent = title;
    $('#manual-port-confirm-copy').textContent = copy;
    $('#manual-port-confirm-accept').textContent = accept;
    confirmDialog.showModal();
    return new Promise(resolve => { confirmResolve = resolve; });
  }

  $('#manual-port-add').addEventListener('click', () => open());
  $('#manual-port-close').addEventListener('click', () => dialog.close());
  $('#manual-port-cancel').addEventListener('click', () => dialog.close());
  $('#manual-port-delete').addEventListener('click', async () => {
    const record = records.find(item => item.id === editId);
    if (!record) return;
    if (!await confirm('Remove port entry?', `Remove ${record.name} on ${record.host_name}:${record.port} from the dashboard? Unsaved edits will be discarded.`, 'Remove port')) return;
    const generation = editGeneration;
    try {
      await api(`/api/ports/manual/${encodeURIComponent(record.id)}`, {method: 'DELETE'});
      if (generation === editGeneration && editId === record.id) {
        if (dialog.open) dialog.close();
        editId = null;
        editGeneration++;
      }
      showToast('Port entry removed.');
      await refreshAll();
    } catch (error) { showToast(error.message, 'error'); }
  });
  $('#manual-port-host').addEventListener('change', updateAddress);
  form.addEventListener('input', event => { if (event.target.matches('input, textarea')) resetCheck(); });
  $('#manual-port-check').addEventListener('click', async () => {
    if (!form.reportValidity()) return;
    const body = payload();
    const signature = JSON.stringify(body);
    const button = $('#manual-port-check');
    button.disabled = true;
    $('#manual-port-check-result').textContent = 'Checking…';
    try {
      const result = await api(`/api/ports/manual/check${editId ? `?exclude_id=${encodeURIComponent(editId)}` : ''}`, {
        method: 'POST', body: JSON.stringify(body)
      });
      if (signature !== JSON.stringify(payload())) { resetCheck(); return; }
      checkedSignature = signature;
      checkedResult = result;
      const duplicate = result.duplicates.length ? ` · Already recorded: ${result.duplicates.join(', ')}` : ' · No existing record';
      $('#manual-port-check-result').textContent = `✓ Checked · ${result.status}${duplicate}`;
      $('#manual-port-check-result').className = `manual-port-check-result ${result.status === 'Open' ? 'is-open' : 'is-unreachable'}`;
      $('#manual-port-save').disabled = false;
    } catch (error) { resetCheck(); showToast(error.message, 'error'); }
    finally { button.disabled = false; }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const submittingId = editId;
    const generation = editGeneration;
    const body = payload();
    if (!checkedResult || checkedSignature !== JSON.stringify(body)) { resetCheck(); return; }
    if (checkedResult.duplicates.length) {
      const accepted = await confirm('Port already recorded', `This host and port are already recorded for ${checkedResult.duplicates.join(', ')}. Save another entry?`, 'Save anyway');
      if (!accepted) return;
      body.confirm_duplicate = true;
    }
    const button = $('#manual-port-save');
    button.disabled = true;
    try {
      const path = submittingId ? `/api/ports/manual/${encodeURIComponent(submittingId)}` : '/api/ports/manual';
      const save = () => api(path, {method: submittingId ? 'PUT' : 'POST', body: JSON.stringify(body)});
      try { await save(); }
      catch (error) {
        if (error.status !== 409 || body.confirm_duplicate) throw error;
        const accepted = await confirm('Port already recorded', `${error.message} Save another entry?`, 'Save anyway');
        if (!accepted) return;
        body.confirm_duplicate = true;
        await save();
      }
      if (generation === editGeneration && editId === submittingId && dialog.open) dialog.close();
      showToast(submittingId ? 'Port entry updated.' : 'Port entry added.');
      await refreshAll();
    } catch (error) { showToast(error.message, 'error'); }
    finally { if (generation === editGeneration && editId === submittingId) button.disabled = false; }
  });

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-manual-port-action]');
    if (!button || button.dataset.manualPortAction !== 'edit') return;
    const record = records.find(item => item.id === button.dataset.id);
    if (record) open(record);
  });

  $('#manual-port-confirm-cancel').addEventListener('click', () => settleConfirm(false));
  $('#manual-port-confirm-accept').addEventListener('click', () => settleConfirm(true));
  confirmDialog.addEventListener('cancel', event => { event.preventDefault(); settleConfirm(false); });
  window.addEventListener('dashboard:manual-ports', event => { records = event.detail; });
})();
