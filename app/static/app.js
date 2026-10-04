(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { services: [], ports: [], portHosts: [], scope: "all", page: "overview", selected: null, selection: null, portFlash: null, selectionGeneration: 0, selectedTimer: null, selectedBusy: null, live: false, refreshGeneration: 0, updateVersion: 0, selectedUpdates: new Map(), renameTarget: null, renameGeneration: 0, portEditorTarget: null, logLines: [], eventSource: null, filterRefreshTimer: null, busy: new Set(), favoriteBusy: new Set(), confirmCleanup: null };
  let inventoryLoaded = false;
  const esc = (value = "") => String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", ...options, headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) } });
    if (response.status === 401) {
      showLogin();
      throw new Error("Your session expired. Please sign in again.");
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.detail || payload.message || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function showLogin() {
    window.dispatchEvent(new Event("dashboard:logout"));
    clearSelection();
    state.live = false;
    updateLiveIndicator();
    clearTimeout(state.filterRefreshTimer);
    closeDrawer();
    $("#rename-modal").hidden = true;
    state.renameTarget = null;
    state.renameGeneration++;
    closeServicePortEditor();
    $("#app-shell").hidden = true;
    $("#login-screen").hidden = false;
    setTimeout(() => $("#login-password").focus(), 30);
  }

  function showApp() {
    $("#login-screen").hidden = true;
    $("#app-shell").hidden = false;
    $("#host-name").textContent = location.hostname || "This host";
    $("#dashboard-endpoint-label").textContent = `Local service management · Port ${location.port || (location.protocol === "https:" ? "443" : "80")}`;
    navigate();
    window.dispatchEvent(new Event("dashboard:ready"));
    refreshAll();
  }

  function showToast(message, kind = "success") {
    const toast = document.createElement("div");
    toast.className = `toast${kind === "error" ? " toast-error" : ""}`;
    const text = document.createElement("span");
    text.className = "toast-message";
    text.textContent = message;
    toast.append(text);
    $("#toast-region").append(toast);
    setTimeout(() => toast.remove(), 4300);
  }

  function resizeTextareas() {
    $$('textarea[data-auto-height]').forEach(field => {
      if (!field.getClientRects().length) return;
      field.style.height = 'auto';
      const borders = field.offsetHeight - field.clientHeight;
      field.style.height = `${field.scrollHeight + borders}px`;
    });
  }

  function activePage() {
    const section = (location.hash || "#overview").slice(1);
    return ["services", "ports", "hosts", "add-service"].includes(section) ? section : "overview";
  }

  function navigate() {
    if (location.hash === "#links") { location.replace("#add-service"); return; }
    if (location.hash === "#monitor") { location.assign(`${location.protocol}//${location.hostname}:8766/`); return; }
    if (state.page !== activePage()) {
      clearSelection();
      closeDrawer();
    }
    state.page = activePage();
    requestAnimationFrame(resizeTextareas);
    const labels = { overview: "Overview", services: "Services", ports: "Open ports", hosts: "Hosts", "add-service": "Add service" };
    $("#page-crumb").textContent = labels[state.page];
    $$(".page-view").forEach(view => { view.hidden = view.id !== `${state.page}-view`; });
    $$(".nav-link").forEach(link => link.classList.toggle("active", link.dataset.nav === state.page));
    renderServices();
    renderPorts();
    if (state.page === "ports") refreshAll();
  }

  async function refreshAll() {
    const generation = ++state.refreshGeneration;
    const startedAtVersion = state.updateVersion;
    try {
      const [serviceData, configuredData, manualData] = await Promise.all([api("/api/services"), api("/api/ports"), api("/api/ports/manual")]);
      if (generation !== state.refreshGeneration) return;
      state.services = (serviceData.services || []).map(service => {
        const update = state.selectedUpdates.get(`service:${service.id}`);
        return update && update.version > startedAtVersion ? update.record : service;
      });
      state.ports = [...(configuredData.ports || []), ...(manualData.ports || [])].map(port => {
        const update = state.selectedUpdates.get(`port:${port.id}`);
        return update && update.version > startedAtVersion ? update.record : port;
      });
      if (state.selection?.kind === "manual-port" && !state.ports.some(port => port.manual && port.id === state.selection.id)) clearSelection();
      if (state.selection?.kind === "configured-port" && !state.ports.some(port => !port.manual && port.service_id === state.selection.id)) clearSelection();
      const hosts = new Map((serviceData.port_hosts || []).map(host => [host.id, host.name]));
      state.ports.forEach(port => hosts.set(port.host_id, port.host_name));
      state.portHosts = [...hosts].map(([id, name]) => ({id, name, port_count: state.ports.filter(port => port.host_id === id && port.status === "Open").length}));
      $("#manual-ports-updated").textContent = `Last checked ${new Date(manualData.checked_at).toLocaleString()}`;

      inventoryLoaded = true;
      window.dispatchEvent(new CustomEvent("dashboard:refresh-result", {detail: {ok: true}}));
      populateCategories();
      renderSummary();
      renderServices();
      renderPorts();
      populateHostFilter();
      window.dispatchEvent(new CustomEvent("dashboard:services", { detail: state.services }));
      window.dispatchEvent(new CustomEvent("dashboard:manual-ports", { detail: manualData.ports || [] }));
      if (state.selected && !state.services.some(service => service.id === state.selected)) closeDrawer();
      if (state.selected) updateDrawerSummary();
      const updatedAt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date());
      $("#updated-at").textContent = updatedAt;
      $("#services-updated-at").textContent = updatedAt;
    } catch (error) {
      if (!$("#login-screen").hidden) return;
      window.dispatchEvent(new CustomEvent("dashboard:refresh-result", {detail: {ok: false, message: error.message}}));
      showToast(error.message, "error");
    }
  }

  function updateLiveIndicator() {
    const button = $("#live-indicator");
    button.setAttribute("aria-pressed", String(state.live));
    button.setAttribute("aria-label", state.live ? "Live checks on. Switch to Not live." : "Live checks off. Switch to Live.");
    button.classList.toggle("is-live", state.live);
    $("#live-indicator-label").textContent = state.live ? "Live" : "Not live";
  }

  function clearSelection() {
    clearInterval(state.selectedTimer);
    state.selectedTimer = null;
    state.selection = null;
    state.portFlash = null;
    state.selectionGeneration++;
  }

  function updateCheckedPort(port) {
    state.selectedUpdates.set(`port:${port.id}`, { version: ++state.updateVersion, record: port });
    const index = state.ports.findIndex(item => item.id === port.id);
    if (index >= 0) state.ports[index] = port;
    else state.ports.push(port);
    state.portHosts = state.portHosts.map(host => ({ ...host,
      port_count: state.ports.filter(item => item.host_id === host.id && item.status === "Open").length }));
    $("#manual-ports-updated").textContent = `Last checked ${new Date(port.checked_at).toLocaleString()}`;
    renderPorts();
    if (state.selected === port.service_id) updateDrawerSummary();
    if (port.manual) window.dispatchEvent(new CustomEvent("dashboard:manual-ports", { detail: state.ports.filter(item => item.manual) }));
  }

  async function checkSelection(generation) {
    const selected = state.selection;
    if (!selected || generation !== state.selectionGeneration || state.selectedBusy === generation) return;
    if (window.HostTracking?.active(selected.kind, selected.id)) return;
    state.selectedBusy = generation;
    try {
      if (selected.kind === "service") {
        const result = await api(`/api/services/${encodeURIComponent(selected.id)}/live`);
        if (generation !== state.selectionGeneration) return;
        const index = state.services.findIndex(item => item.id === selected.id);
        if (index < 0) return;
        state.selectedUpdates.set(`service:${selected.id}`, { version: ++state.updateVersion, record: result.service });
        state.services[index] = result.service;
        renderSummary();
        renderServices();
        if (state.selected === selected.id) updateDrawerSummary();
        if (result.port) updateCheckedPort(result.port);
      } else {
        const kind = selected.kind === "manual-port" ? "manual" : "service";
        const result = await api(`/api/ports/check?kind=${kind}&id=${encodeURIComponent(selected.id)}`);
        if (generation !== state.selectionGeneration) return;
        updateCheckedPort(result);
      }
    } catch (error) {
      if (generation === state.selectionGeneration) showToast(error.message, "error");
    } finally {
      if (state.selectedBusy === generation) state.selectedBusy = null;
    }
  }

  function selectCheckTarget(kind, id) {
    clearSelection();
    state.selection = { kind, id };
    if (kind === "manual-port" || kind === "configured-port") state.portFlash = { kind, id, startedAt: Date.now() };
    const generation = state.selectionGeneration;
    renderServices();
    renderPorts();
    checkSelection(generation);
    if (state.live) state.selectedTimer = setInterval(() => checkSelection(generation), 3000);
  }

  function toggleLive() {
    state.live = !state.live;
    updateLiveIndicator();
    clearInterval(state.selectedTimer);
    state.selectedTimer = null;
    if (state.live && state.selection) {
      const generation = state.selectionGeneration;
      checkSelection(generation);
      state.selectedTimer = setInterval(() => checkSelection(generation), 3000);
    }
  }

  function refreshAfterFilter() {
    clearTimeout(state.filterRefreshTimer);
    state.filterRefreshTimer = setTimeout(refreshAll, 300);
  }

  function populateCategories() {
    const categories = [...new Set(state.services.map(service => service.category))].sort();
    [$("#category-filter-page")].forEach(select => {
      if (!select) return;
      const selected = select.value;
      select.innerHTML = `<option value="all">All categories</option>${categories.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join("")}`;
      if (categories.includes(selected)) select.value = selected;
    });
  }

  function renderSummary() {
    const running = state.services.filter(service => service.status === "Running").length;
    const stopped = state.services.filter(service => service.status === "Stopped").length;
    const failed = state.services.filter(service => service.status === "Failed").length;
    const unavailable = state.services.filter(service => service.status === "Unavailable").length;
    $("#count-total").textContent = state.services.length;
    $("#count-running").textContent = running;
    $("#count-stopped").textContent = stopped;
    $("#count-failed").textContent = failed;
    $("#nav-service-count").textContent = state.services.length;
    $("#failed-foot").textContent = failed || unavailable ? `${failed} failed · ${unavailable} unavailable` : "No failed or unavailable units";
  }

  function currentFilters(page = "overview") {
    const search = $(`#service-search${page === "services" ? "-page" : ""}`)?.value.trim().toLowerCase() || "";
    const status = $(`#status-filter${page === "services" ? "-page" : ""}`)?.value || "all";
    const category = $(`#category-filter${page === "services" ? "-page" : ""}`)?.value || "all";
    return { search, status, category };
  }

  function filteredServices(page = "overview") {
    const { search, status, category } = currentFilters(page);
    const activeScope = state.scope;
    return state.services.filter(service => {
      const portText = service.configured_port || "";
      const hostFilter = page === "services" ? $("#service-host-filter").value : "all";
      return (hostFilter === "all" || (service.host_id || (service.scope === "external" ? "external" : "local")) === hostFilter)
        && (status === "all" || service.status === status)
        && (category === "all" || service.category === category)
        && (activeScope === "all" || (activeScope === "favorites" ? service.favorite : service.scope === activeScope))
        && (!search || `${displayName(service)} ${service.name} ${service.description} ${service.id} ${service.unit || ""} ${service.host_name || ""} ${portText}`.toLowerCase().includes(search));
    });
  }

  function statusClass(status) { return status === "Running" ? "status-running" : status === "Failed" ? "status-failed" : status === "Unavailable" ? "status-unavailable" : status === "Linked" ? "status-linked" : "status-stopped"; }
  function isManaged(service) { return service.managed !== false; }
  function scopeLabel(service) { return service.scope === "external" ? "EXTERNAL LINK" : !isManaged(service) ? "UNMANAGED" : `${service.scope.toUpperCase()} UNIT`; }
  function canOpen(service) { return !isManaged(service) || service.status === "Running" || service.service_type === "external" || service.service_type === "remote"; }

  function populateHostFilter() {
    const select = $("#service-host-filter");
    const current = select.value;
    const hosts = new Map([["local", "This host"]]);
    state.services.forEach(service => hosts.set(service.host_id || (service.scope === "external" ? "external" : "local"), service.host_name || "This host"));
    select.innerHTML = `<option value="all">All hosts</option>${[...hosts].map(([id,name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join("")}`;
    if (hosts.has(current)) select.value = current;
  }
  function serviceInitial(service) { return service.name.replace(/[^a-z0-9]/gi, "").slice(0, 1).toUpperCase() || "S"; }
  function displayName(service) { return service.display_name || service.name; }
  function formatTime(value) {
    if (!value || value === "n/a") return "Not started";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) return value.replace(/\s+\w+$/, "");
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(parsed);
  }
  function localServiceUrl(port) {
    const url = new URL(location.origin);
    url.port = port;
    url.pathname = "/";
    url.search = "";
    url.hash = "";
    return url.href;
  }

  function getOpenUrl(service) {
    if (service.open_url) return service.open_url;
    return service.web && service.service_type !== "remote" && service.configured_port ? localServiceUrl(service.configured_port) : "";
  }

  function renderDrawerActions(service) {
    const openUrl = getOpenUrl(service);
    const unavailable = service.controllable === false || state.busy.has(service.id);
    const controls = !isManaged(service) ? '' : `<button class="mini-action" data-action="start" data-id="${esc(service.id)}" ${unavailable || service.status === 'Running' ? 'disabled' : ''}>▶ Start</button><button class="mini-action" data-action="stop" data-id="${esc(service.id)}" ${unavailable || service.status === 'Stopped' ? 'disabled' : ''}>■ Stop</button><button class="mini-action" data-action="restart" data-id="${esc(service.id)}" ${unavailable || service.status === 'Stopped' ? 'disabled' : ''}>↻ Restart</button>`;
    $('#drawer-actions').innerHTML = controls + (openUrl && canOpen(service) ? `<a class="mini-action open-action" href="${esc(openUrl)}" target="_blank" rel="noopener noreferrer">↗ Open service</a>` : '');
    $('#drawer-remove').hidden = !service.registered;
    $('#log-pause').disabled = !isManaged(service);
    $('.drawer-tab[data-tab=logs]').hidden = !isManaged(service);
    $('.drawer-tab[data-tab=status]').textContent = isManaged(service) ? 'Status' : 'Details';
    $('#log-refresh').disabled = !isManaged(service);
  }

  function serviceCard(service) {
    const openUrl = getOpenUrl(service);
    const portBadges = service.configured_port ? `<span class="port-tag">PORT ${service.configured_port}</span>` : "";
    const tags = `${portBadges || `<span class="no-port">No port assigned</span>`}<span class="scope-tag">${scopeLabel(service)}</span>${service.host_name ? `<span class="scope-tag" title="${esc(service.unit || service.host_name)}">${esc(service.host_name)}</span>` : ""}`;
    const busy = state.busy.has(service.id) || service.controllable === false;
    const startDisabled = busy || service.status === "Running";
    const stopDisabled = busy || service.status === "Stopped";
    const restartDisabled = busy || service.status === "Stopped";
    const activeTime = service.status === "Running" ? formatTime(service.active_since) : "—";
    return `<article class="service-card${state.selection?.kind === "service" && state.selection.id === service.id ? " is-selected" : ""}" data-service-id="${esc(service.id)}" tabindex="0" aria-label="Open details for ${esc(displayName(service))}">
      <div class="service-card-top"><div class="service-identity"><span class="service-mark ${service.scope === "system" ? "mark-system" : service.web ? "mark-web" : ""}">${esc(serviceInitial(service))}</span><div class="service-copy"><div class="service-title-line"><h3 data-open-detail="${esc(service.id)}" title="View service details">${esc(displayName(service))}</h3></div><p>${esc(service.description)}</p></div></div><div class="service-status-group"><span class="service-status-light ${statusClass(service.status)}" role="img" tabindex="0" aria-label="Status: ${esc(service.status)}" data-status="${esc(service.status)}"></span><button class="favorite-indicator${service.favorite ? " is-favorite" : ""}" type="button" data-toggle-favorite="${esc(service.id)}" aria-label="${service.favorite ? "Remove from favorites" : "Add to favorites"}" aria-pressed="${String(!!service.favorite)}" title="${service.favorite ? "Remove from favorites" : "Add to favorites"}">${service.favorite ? "★" : "☆"}</button></div></div>
      <div class="service-tags">${tags}</div>
      <span class="started-at service-card-time">${service.status === "Running" ? `Active since <strong>${esc(activeTime)}</strong>` : !isManaged(service) ? (openUrl ? "Website shortcut" : "No systemd unit configured") : service.status === "Unavailable" ? `<span title="${esc(service.error)}">Host or unit unavailable</span>` : `Unit <strong>${service.substate === "failed" ? "failed" : "inactive"}</strong>`}</span>
      <div class="service-card-bottom"><div class="card-actions">
        ${openUrl && canOpen(service) ? `<a class="mini-action open-action" href="${esc(openUrl)}" target="_blank" rel="noopener noreferrer" title="Open service in a new tab">↗ Open</a>` : (service.web || service.open_url) ? `<button class="mini-action open-action" data-open-service="${esc(service.id)}" disabled title="${service.status !== "Running" ? "Start service to open it" : "No open URL or service port configured"}">↗ Open</button>` : ""}
        ${!isManaged(service) ? "" : `<button class="mini-action" data-action="start" data-id="${esc(service.id)}" ${startDisabled ? "disabled" : ""} title="Start" aria-label="Start ${esc(service.name)}">▶ Start</button><button class="mini-action" data-action="restart" data-id="${esc(service.id)}" ${restartDisabled ? "disabled" : ""} title="Restart" aria-label="Restart ${esc(service.name)}">↻ Restart</button><button class="mini-action" data-action="stop" data-id="${esc(service.id)}" ${stopDisabled ? "disabled" : ""} title="Stop" aria-label="Stop ${esc(service.name)}">■ Stop</button>`}
      </div></div></article>`;
  }

  function drawServiceLists() {
    const page = filteredServices("services");
    $("#service-grid-page").innerHTML = page.map(serviceCard).join("");
    $("#service-grid-page").hidden = !page.length;
    $("#empty-services-page").hidden = !!page.length;
  }

  function publishInventory() {
    window.dispatchEvent(new CustomEvent("dashboard:inventory", {detail: {services: state.services, ports: state.ports, loaded: inventoryLoaded}}));
  }

  function captureListFocus(containerIds, itemSelector, keyFields) {
    const active = document.activeElement;
    const item = active?.closest?.(itemSelector);
    const container = item && containerIds.map(id => document.getElementById(id)).find(root => root?.contains(item));
    if (!container) return () => {};
    const key = keyFields.map(field => item.dataset[field]);
    const controls = [...item.querySelectorAll("button, a, [tabindex]")];
    const controlIndex = active === item ? -1 : controls.indexOf(active);
    return () => {
      const replacement = [...container.querySelectorAll(itemSelector)].find(candidate => keyFields.every((field, index) => candidate.dataset[field] === key[index]));
      if (!replacement) return;
      const target = controlIndex < 0 ? replacement : [...replacement.querySelectorAll("button, a, [tabindex]")][controlIndex] || replacement;
      target.focus({ preventScroll: true });
    };
  }

  function renderServices() {
    const restoreFocus = captureListFocus(["service-grid-page"], ".service-card", ["serviceId"]);
    drawServiceLists();
    restoreFocus();
    publishInventory();
  }

  function sortedPorts() {
    const search = $("#port-search").value.trim().toLowerCase();
    const host = $("#port-host-filter").value;
    return state.ports.filter(port => (host === "all" || port.host_id === host)
      && (!search || `${port.host_name} ${port.address || ""} ${port.port} ${port.name} ${port.source || ""} ${port.status}`.toLowerCase().includes(search)));
  }

  function renderPorts() {
    const restoreFocus = captureListFocus(["ports-list"], ".port-row", ["portKind", "portId"]);
    const select = $("#port-host-filter");
    const previous = select.value;
    select.innerHTML = `<option value="all">All hosts</option>${state.portHosts.map(host => `<option value="${esc(host.id)}">${esc(host.name)}</option>`).join("")}`;
    if (state.portHosts.some(host => host.id === previous)) select.value = previous;
    $("#port-host-status").innerHTML = state.portHosts.map(host => `<span class="port-host-badge port-host-connected">${esc(host.name)} <strong>${host.port_count} active</strong></span>`).join("");
    const ports = sortedPorts();
    $("#ports-list").innerHTML = `<div class="ports-header"><span>Host</span><span>Service</span><span>Service / source</span><span>Port</span><span>Status</span><span>Last checked</span><span>Actions</span></div>${ports.map(port => `<div class="port-row${state.selection?.kind === (port.manual ? "manual-port" : "configured-port") && state.selection.id === (port.manual ? port.id : port.service_id) ? " is-selected" : ""}" data-port-kind="${port.manual ? "manual-port" : "configured-port"}" data-port-id="${esc(port.manual ? port.id : port.service_id)}" tabindex="0" role="button" aria-label="Check ${esc(port.name)} on port ${port.port}"><span class="port-host-cell" title="${esc(port.address || port.host_name)}">${esc(port.host_name)}</span><span class="port-owner-cell" title="${esc(port.name)}">${esc(port.name)}</span><span class="port-owner-cell" title="${esc(port.source || "")}">${esc(port.source || "—")}</span><span class="port-number">${port.port}</span><span class="status-badge ${port.status === "Open" ? "status-running" : "status-unavailable"}" title="${esc(port.error || "")}">${esc(port.status)}</span><span class="port-checked-at">${port.checked_at ? esc(new Date(port.checked_at).toLocaleString()) : "Not checked"}</span><span class="port-row-actions">${port.manual ? `<button type="button" data-manual-port-action="edit" data-id="${esc(port.id)}" aria-label="Edit ${esc(port.name)}" title="Edit port">✎</button>` : `<button type="button" data-configured-port-action="view" data-id="${esc(port.service_id)}" aria-label="View port details for ${esc(port.name)}" title="View port details">✎</button>`}</span></div>`).join("") || `<p class="empty-state">No port records match this filter.</p>`}`;
    if (state.portFlash) {
      const elapsed = Date.now() - state.portFlash.startedAt;
      if (elapsed < 2000) {
        const row = $$(".port-row", $("#ports-list")).find(item => item.dataset.portKind === state.portFlash.kind && item.dataset.portId === state.portFlash.id);
        if (row) {
          row.classList.add("port-row-flash");
          row.style.animationDelay = `${-elapsed}ms`;
        }
      }
    }
    restoreFocus();
    publishInventory();
  }

  function openServiceDetail(serviceId) {
    const service = state.services.find(item => item.id === serviceId);
    if (!service) return;
    state.selected = serviceId;
    window.HostTracking?.bind($("#drawer-favorite"), "service", serviceId);
    state.logLines = [];
    $("#drawer-title").textContent = displayName(service);
    $("#drawer-category").textContent = `${service.category} · ${scopeLabel(service)}`;
    $("#drawer-description").textContent = service.description;
    updateFavoriteButton(service);
    $("#drawer-status-icon").textContent = serviceInitial(service);
    $("#drawer-status-icon").className = `service-mark ${service.scope === "system" ? "mark-system" : service.web ? "mark-web" : ""}`;
    $("#drawer-meta").innerHTML = drawerMeta(service);
    updateDrawerCheckedAt(service);
    renderDrawerActions(service);
    $("#detail-drawer").classList.add("open");
    $("#detail-drawer").setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    state.eventSource?.close();
    state.eventSource = null;
    switchDrawerTab(isManaged(service) ? "logs" : "status");
    loadStatus(serviceId);
    if (isManaged(service)) loadRecentLogs(serviceId, true);
  }

  async function openServiceDetailFresh(serviceId) {
    clearTimeout(state.filterRefreshTimer);
    openServiceDetail(serviceId);
    selectCheckTarget("service", serviceId);
  }

  function updateDrawerSummary() {
    const service = state.services.find(item => item.id === state.selected);
    if (!service) return;
    $("#drawer-meta").innerHTML = drawerMeta(service);
    updateDrawerCheckedAt(service);
    $("#drawer-title").textContent = displayName(service);
    $("#drawer-category").textContent = `${service.category} · ${scopeLabel(service)}`;
    $("#drawer-description").textContent = service.description;
    updateFavoriteButton(service);
    renderDrawerActions(service);
  }

  function updateDrawerCheckedAt(service) {
    const checked = $("#drawer-checked-at");
    const date = service.checked_at ? new Date(service.checked_at) : null;
    checked.textContent = date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : "Not checked yet";
    if (date && !Number.isNaN(date.getTime())) checked.dateTime = date.toISOString();
    else checked.removeAttribute("datetime");
  }

  function drawerMeta(service) {
    const port = state.ports.find(item => !item.manual && item.service_id === service.id);
    const connectivity = port ? `<span class="status-badge ${port.status === "Open" ? "status-running" : "status-unavailable"}" title="TCP connection from this dashboard host">TCP ${esc(port.status)}</span>` : "";
    return `<span class="status-badge ${statusClass(service.status)}">${esc(service.status)}</span>${service.configured_port ? `<span class="port-tag">PORT ${service.configured_port}</span>` : ""}${connectivity}`;
  }

  function updateFavoriteButton(service) {
    const button = $("#drawer-favorite");
    const favorite = !!service.favorite;
    button.classList.toggle("is-favorite", favorite);
    button.textContent = favorite ? "★" : "☆";
    button.title = favorite ? "Remove from favorites" : "Add to favorites";
    button.setAttribute("aria-label", button.title);
    button.setAttribute("aria-pressed", String(favorite));
  }

  async function toggleServiceFavorite(serviceId, source = "drawer") {
    const service = state.services.find(item => item.id === serviceId);
    if (!service || state.favoriteBusy.has(serviceId)) return;
    state.favoriteBusy.add(serviceId);
    $$(".service-card").filter(card => card.dataset.serviceId === serviceId).forEach(card => { card.querySelector("[data-toggle-favorite]").disabled = true; });
    if (state.selected === serviceId) $("#drawer-favorite").disabled = true;
    try {
      const result = await api(`/api/services/${encodeURIComponent(serviceId)}/favorite`, { method: "PUT", body: JSON.stringify({ favorite: !service.favorite }) });
      service.favorite = result.favorite;
      state.favoriteBusy.delete(serviceId);
      renderServices();
      if (state.selected === serviceId) updateFavoriteButton(service);
      if (result.favorite) {
        const buttons = source === "drawer"
          ? [$("#drawer-favorite")]
          : $$(".service-card").filter(card => card.dataset.serviceId === serviceId).map(card => card.querySelector("[data-toggle-favorite]"));
        buttons.filter(Boolean).forEach(button => {
          button.classList.remove("favorite-bounce");
          void button.offsetWidth;
          button.classList.add("favorite-bounce");
        });
      }
      showToast(result.favorite ? "Added to Favorites." : "Removed from Favorites.");
    } catch (error) { showToast(error.message, "error"); }
    finally {
      state.favoriteBusy.delete(serviceId);
      $$(".service-card").filter(card => card.dataset.serviceId === serviceId).forEach(card => { const button = card.querySelector("[data-toggle-favorite]"); if (button) button.disabled = false; });
      if (state.selected === serviceId) $("#drawer-favorite").disabled = false;
    }
  }

  function closeDrawer() {
    if (!$("#detail-drawer")) return;
    if (state.selection?.kind === "service") { clearSelection(); renderServices(); }
    $("#detail-drawer").classList.remove("open");
    $("#detail-drawer").setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    state.eventSource?.close();
    state.eventSource = null;
    state.selected = null;
  }

  async function loadStatus(serviceId) {
    $("#status-output").textContent = "Loading status…";
    try { $("#status-output").textContent = (await api(`/api/services/${encodeURIComponent(serviceId)}/status`)).status; }
    catch (error) { $("#status-output").textContent = error.message; }
  }

  async function loadRecentLogs(serviceId, follow) {
    if (!isManaged(state.services.find(service => service.id === serviceId) || { managed: false })) return;
    if (window.HostTracking?.active("service", serviceId)) follow = false;
    state.eventSource?.close();
    state.eventSource = null;
    $("#log-live-label").textContent = follow ? "Following live" : "Live paused";
    $("#log-pause").textContent = follow ? "Pause" : "Resume";
    $("#log-viewer").innerHTML = `<div class="loading-state">Loading journal…</div>`;
    try {
      const result = await api(`/api/services/${encodeURIComponent(serviceId)}/logs?lines=150`);
      if (state.selected !== serviceId) return;
      state.logLines = result.lines || [];
      renderLogLines();
      if (follow && state.services.find(service => service.id === serviceId)?.scope !== "external") startLogStream(serviceId);
      else if (state.services.find(service => service.id === serviceId)?.scope === "external") $("#log-live-label").textContent = "Logs unavailable for external links";
    } catch (error) {
      $("#log-viewer").innerHTML = `<div class="log-empty">${esc(error.message)}</div>`;
    }
  }

  function startLogStream(serviceId) {
    if (window.HostTracking?.active("service", serviceId)) return;
    if (!isManaged(state.services.find(service => service.id === serviceId) || { managed: false })) return;
    state.eventSource?.close();
    const source = new EventSource(`/api/services/${encodeURIComponent(serviceId)}/logs/stream?lines=30`, { withCredentials: true });
    state.eventSource = source;
    source.onopen = () => { if (state.selected === serviceId) { $("#log-live-label").textContent = "Following live"; $("#log-pause").textContent = "Pause"; } };
    source.onmessage = event => {
      try {
        const payload = JSON.parse(event.data);
        state.logLines.push(payload.line);
        if (state.logLines.length > 800) state.logLines.splice(0, state.logLines.length - 800);
        renderLogLines(true);
      } catch { /* Ignore malformed journal events. */ }
    };
    source.onerror = () => { if (state.selected === serviceId) $("#log-live-label").textContent = "Reconnecting…"; };
  }

  function logSeverity(line) {
    if (/\b(error|err|fatal|critical|crit|panic|failed|failure)\b/i.test(line)) return "error";
    if (/\b(warn|warning)\b/i.test(line)) return "warning";
    return "info";
  }

  function renderLogLines(scroll = false) {
    const query = $("#log-search").value.trim().toLowerCase();
    const severity = $("#log-severity").value;
    const visible = state.logLines.filter(line => {
      const level = logSeverity(line);
      return (!query || line.toLowerCase().includes(query)) && (severity === "all" || level === severity);
    });
    const viewer = $("#log-viewer");
    viewer.innerHTML = visible.length ? visible.map(line => {
      const level = logSeverity(line);
      const label = level === "error" ? "ERROR" : level === "warning" ? "WARN" : "LOG";
      return `<div class="log-line ${level}"><span class="log-level">${label}</span><span class="log-text">${esc(line)}</span></div>`;
    }).join("") : `<div class="log-empty">${state.logLines.length ? "No lines match this filter." : "No journal entries yet."}</div>`;
    if (scroll) viewer.scrollTop = viewer.scrollHeight;
  }

  async function copyRecentLogs(count) {
    const lines = state.logLines.slice(-count);
    if (!lines.length) { showToast("There are no log lines to copy.", "error"); return; }
    const text = lines.join("\n");
    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        try { await navigator.clipboard.writeText(text); }
        catch { legacyCopyText(text); }
      } else legacyCopyText(text);
      showToast(`Copied ${lines.length} recent log lines.`);
    } catch { showToast("Could not copy logs to the clipboard.", "error"); }
  }

  function legacyCopyText(text) {
    const input = document.createElement("textarea");
    input.value = text;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    if (!copied) throw new Error("Clipboard copy failed");
  }

  function switchDrawerTab(tab) {
    $$(".drawer-tab").forEach(button => button.classList.toggle("active", button.dataset.tab === tab));
    $("#drawer-logs").hidden = tab !== "logs";
    $("#drawer-status").hidden = tab !== "status";
  }

  function askAction(serviceId, action) {
    const service = state.services.find(item => item.id === serviceId);
    if (!service) return;
    const labels = { start: "Start", stop: "Stop", restart: "Restart" };
    const copy = {
      start: `Start ${displayName(service)}? The service will begin running in the background.`,
      stop: `Stop ${displayName(service)}? Any users currently connected to this service may be disconnected.`,
      restart: `Restart ${displayName(service)}? This will briefly interrupt the service.`
    };
    $("#confirm-title").textContent = `${labels[action]} service?`;
    $("#confirm-copy").textContent = `${copy[action]} Host: ${service.host_name || "This host"} · Unit: ${service.unit || service.id}.`;
    $("#confirm-icon").textContent = action === "start" ? "▶" : action === "stop" ? "■" : "↻";
    $("#confirm-accept").textContent = `${labels[action]} service`;
    $("#confirm-accept").className = `button ${action === "stop" ? "button-danger" : "button-primary"}`;
    const modal = $("#confirm-modal");
    modal.hidden = false;
    const accept = () => {
      modal.hidden = true;
      $("#confirm-accept").removeEventListener("click", accept);
      $("#confirm-cancel").removeEventListener("click", cancel);
      state.confirmCleanup = null;
      runAction(serviceId, action);
    };
    const cancel = () => {
      modal.hidden = true;
      $("#confirm-accept").removeEventListener("click", accept);
      $("#confirm-cancel").removeEventListener("click", cancel);
      state.confirmCleanup = null;
    };
    state.confirmCleanup = cancel;
    $("#confirm-accept").addEventListener("click", accept, { once: true });
    $("#confirm-cancel").addEventListener("click", cancel, { once: true });
  }

  async function runAction(serviceId, action) {
    state.busy.add(serviceId);
    renderServices();
    if (state.selected === serviceId) updateDrawerSummary();
    try {
      const result = await api(`/api/services/${encodeURIComponent(serviceId)}/actions/${action}`, { method: "POST", body: "{}" });
      showToast(result.message || (result.ok ? "Operation completed." : "Operation failed."), result.ok ? "success" : "error");
      await refreshAll();
      if (state.selected === serviceId) loadStatus(serviceId);
    } catch (error) { showToast(error.message, "error"); }
    finally { state.busy.delete(serviceId); renderServices(); if (state.selected === serviceId) updateDrawerSummary(); }
  }

  function updateEditorLocation() {
    const service = state.services.find(item => item.id === state.renameTarget);
    if (!service) return;
    const external = $("#service-host").value === "external";
    const registered = !!service.registered;
    $("#service-scope-row").hidden = external;
    $("#service-unit-row").hidden = external;
    $("#service-port-row").hidden = external;
    $("#service-host").disabled = !registered;
    $("#service-scope").disabled = !registered || external;
    $("#service-unit").disabled = !registered || external;
    $("#service-port").disabled = external || !$("#service-unit").value.trim();
    $("#service-open-url").required = external;
    $("#service-edit-note").textContent = registered ? "Editing these settings does not create, start, or stop a unit." : "Built-in service host, scope, and systemd unit are fixed.";
  }

  async function askRename(serviceId) {
    const service = state.services.find(item => item.id === serviceId);
    if (!service) return;
    const generation = ++state.renameGeneration;
    try {
      const result = await api("/api/hosts");
      if (generation !== state.renameGeneration) return;
      const host = $("#service-host");
      const remote = document.createElement("optgroup");
      remote.label = "Remote SSH hosts";
      (result.hosts || []).forEach(item => remote.append(new Option(`${item.name} · ${item.username}@${item.address}`, item.id)));
      host.replaceChildren(new Option("This host", "local"), remote, new Option("External website · link only", "external"));
      state.renameTarget = serviceId;
      window.HostTracking?.bind($("#rename-cancel"), "service", serviceId);
      host.value = service.service_type === "external" ? "external" : service.host_id || "local";
      $("#service-display-name").value = displayName(service);
      $("#service-category").value = service.category;
      $("#service-scope").value = service.scope === "system" ? "system" : "user";
      $("#service-description").value = service.description || "";
      $("#service-port").value = service.configured_port || "";
      $("#service-unit").value = service.unit || "";
      $("#service-open-url").value = service.open_url || "";
      $("#service-open-url").placeholder = getOpenUrl(service) || "https://service.example.com";
      $("#service-favorite").checked = !!service.favorite;
      $("#service-port-delete").hidden = !service.configured_port;
      updateEditorLocation();
      $("#rename-modal").hidden = false;
      resizeTextareas();
      setTimeout(() => { $("#service-display-name").focus(); $("#service-display-name").select(); }, 30);
    } catch (error) { showToast(error.message, "error"); }
  }

  async function saveDisplayName(event) {
    event.preventDefault();
    if (!state.renameTarget) return;
    const unitField = $("#service-unit");
    const urlField = $("#service-open-url");
    const external = $("#service-host").value === "external";
    unitField.setCustomValidity(external || !unitField.value.trim() || /^[A-Za-z0-9_][A-Za-z0-9_@:.-]*\.(service|socket)$/.test(unitField.value.trim()) ? "" : "Enter a systemd unit ending in .service or .socket.");
    urlField.setCustomValidity("");
    if (urlField.value.trim()) {
      try {
        const parsed = new URL(urlField.value.trim());
        if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) throw new Error();
      } catch { urlField.setCustomValidity("Enter an HTTP or HTTPS URL without embedded credentials."); }
    }
    if (!$("#rename-form").reportValidity()) return;
    const serviceId = state.renameTarget;
    const generation = state.renameGeneration;
    const hostId = $("#service-host").value;
    const serviceType = hostId === "external" ? "external" : hostId === "local" ? "local" : "remote";
    const unit = serviceType === "external" ? "" : $("#service-unit").value.trim();
    const body = {
      service_type: serviceType, host_id: serviceType === "external" ? "" : hostId,
      display_name: $("#service-display-name").value.trim(), category: $("#service-category").value,
      scope: serviceType === "external" ? "external" : $("#service-scope").value,
      description: $("#service-description").value.trim(), unit,
      port: unit && $("#service-port").value ? Number($("#service-port").value) : null,
      open_url: $("#service-open-url").value.trim(), favorite: $("#service-favorite").checked
    };
    try {
      await api(`/api/services/${encodeURIComponent(serviceId)}/edit`, { method: "PUT", body: JSON.stringify(body) });
      const drawerOpen = state.selected === serviceId && $("#detail-drawer").classList.contains("open");
      if (state.selection?.id === serviceId) clearSelection();
      if (state.renameTarget === serviceId && state.renameGeneration === generation) {
        $("#rename-modal").hidden = true;
        state.renameTarget = null;
        state.renameGeneration++;
      }
      await refreshAll();
      if (drawerOpen) selectCheckTarget("service", serviceId);
      showToast("Service settings saved.");
    } catch (error) { showToast(error.message, "error"); }
  }

  function closeServicePortEditor() {
    $("#service-port-modal").hidden = true;
    state.portEditorTarget = null;
  }

  function openServicePortEditor(serviceId) {
    const service = state.services.find(item => item.id === serviceId);
    if (!service || !service.configured_port) return;
    state.portEditorTarget = serviceId;
    window.HostTracking?.bind($("#service-port-open-service"), "service", serviceId);
    $("#service-port-name").textContent = displayName(service);
    $("#service-port-host").textContent = service.host_name || "This host";
    $("#service-port-only").textContent = service.configured_port;
    $("#service-port-modal").hidden = false;
    $("#service-port-open-service").focus();
  }

  async function removeConfiguredPort(serviceId) {
    const service = state.services.find(item => item.id === serviceId);
    if (!service) return;
    const accepted = await window.HostDashboard.confirm("Remove assigned port?", `Remove port ${service.configured_port} from ${displayName(service)}? Unsaved edits will be discarded. The service and its systemd unit will stay registered.`);
    if (!accepted) return;
    const generation = state.renameGeneration;
    try {
      await api(`/api/ports/service/${encodeURIComponent(serviceId)}`, { method: "DELETE" });
      if (state.renameTarget === serviceId && generation === state.renameGeneration) {
        $("#rename-modal").hidden = true;
        state.renameTarget = null;
        state.renameGeneration++;
      }
      if (state.selection?.kind === "configured-port" && state.selection.id === serviceId) clearSelection();
      await refreshAll();
      showToast("Assigned port removed. The service was not deleted.");
    } catch (error) { showToast(error.message, "error"); }
  }

  function bindEvents() {
    window.addEventListener("hashchange", navigate);
    $("#live-indicator").addEventListener("click", toggleLive);
    $("#login-form").addEventListener("submit", async event => {
      event.preventDefault();
      $("#login-error").textContent = "";
      try {
        const password = window.HostInputLimits.validatePassword($("#login-password").value, await window.HostInputLimits.passwordPolicy());
        await api("/api/login", { method: "POST", body: JSON.stringify({ password }) });
        $("#login-password").value = "";
        showApp();
      } catch (error) { $("#login-error").textContent = error.message; }
    });
    $("#logout-button").addEventListener("click", async () => {
      try { await api("/api/logout", { method: "POST", body: "{}" }); } catch { /* Expired session is already signed out. */ }
      showLogin();
    });
    $("#refresh-button").addEventListener("click", refreshAll);
    const applySummaryFilter = card => {
      const status = card.dataset.summaryFilter;
      $("#status-filter-page").value = status;
      $("#category-filter-page").value = "all";
      $("#service-search-page").value = "";
      $("#service-host-filter").value = "all";
      state.scope = "all";
      $$("[data-scope]").forEach(item => item.classList.toggle("selected", item.dataset.scope === "all"));
      renderServices();
      $("#services-view .filter-bar").scrollIntoView({ behavior: "smooth", block: "start" });
      refreshAll();
    };
    $$('[data-summary-filter]').forEach(card => card.addEventListener("click", () => applySummaryFilter(card)));
    ["#service-search-page"].forEach(selector => $(selector)?.addEventListener("input", () => { renderServices(); refreshAfterFilter(); }));
    ["#status-filter-page", "#category-filter-page"].forEach(selector => $(selector)?.addEventListener("change", () => { renderServices(); refreshAfterFilter(); }));
    $$("[data-scope]").forEach(button => button.addEventListener("click", () => {
      state.scope = button.dataset.scope;
      $$("[data-scope]").forEach(item => item.classList.toggle("selected", item === button));
      renderServices();
      refreshAll();
    }));
    $("#service-host-filter").addEventListener("change", () => { renderServices(); refreshAll(); });
    $("#drawer-remove").addEventListener("click", async () => {
      const id = state.selected;
      if (!id || !await window.HostDashboard.confirm("Remove service?", "This only removes the dashboard entry. It will not stop or delete the actual service.")) return;
      try { await api(`/api/services/${encodeURIComponent(id)}`, { method: "DELETE" }); closeDrawer(); showToast("Service removed from dashboard."); await refreshAll(); }
      catch (error) { showToast(error.message, "error"); }
    });
    $("#port-host-filter").addEventListener("change", () => { renderPorts(); refreshAfterFilter(); });
    $("#port-search").addEventListener("input", () => { renderPorts(); refreshAfterFilter(); });
    $("#rename-form").addEventListener("submit", saveDisplayName);
    $("#rename-form").addEventListener("input", event => event.target.setCustomValidity?.(""));
    $("#service-host").addEventListener("change", updateEditorLocation);
    $("#service-unit").addEventListener("input", updateEditorLocation);
    $("#rename-cancel").addEventListener("click", () => { $("#rename-modal").hidden = true; state.renameTarget = null; state.renameGeneration++; });
    $("#service-edit-cancel").addEventListener("click", () => { $("#rename-modal").hidden = true; state.renameTarget = null; state.renameGeneration++; });
    $("#service-port-delete").addEventListener("click", () => state.renameTarget && removeConfiguredPort(state.renameTarget));
    $("#service-port-close").addEventListener("click", closeServicePortEditor);
    $("#service-port-open-service").addEventListener("click", () => {
      const serviceId = state.portEditorTarget;
      if (!serviceId) return;
      closeServicePortEditor();
      location.hash = "#services";
      navigate();
      openServiceDetailFresh(serviceId);
    });
    $("#drawer-rename").addEventListener("click", () => state.selected && askRename(state.selected));
    $("#drawer-export").addEventListener("click", () => state.selected && window.dispatchEvent(new CustomEvent('dashboard:export-service', { detail: state.selected })));
    $("#drawer-favorite").addEventListener("click", () => state.selected && toggleServiceFavorite(state.selected));
    document.addEventListener("click", event => {
      const action = event.target.closest("[data-action]");
      if (action && !action.disabled) { askAction(action.dataset.id, action.dataset.action); return; }
      const favoriteButton = event.target.closest("[data-toggle-favorite]");
      if (favoriteButton && !favoriteButton.disabled) { toggleServiceFavorite(favoriteButton.dataset.toggleFavorite, "card"); return; }
      const copyButton = event.target.closest("[data-copy-logs]");
      if (copyButton) { copyRecentLogs(Number(copyButton.dataset.copyLogs)); return; }
      const detail = event.target.closest("[data-open-detail]");
      if (detail) { openServiceDetailFresh(detail.dataset.openDetail); return; }
      const configuredPortAction = event.target.closest("[data-configured-port-action]");
      if (configuredPortAction) {
        openServicePortEditor(configuredPortAction.dataset.id);
        return;
      }
      if (event.target.closest("[data-close-drawer]")) closeDrawer();
      const portRow = event.target.closest(".port-row[data-port-id]");
      if (portRow && !event.target.closest("button, a, input, select, textarea")) {
        selectCheckTarget(portRow.dataset.portKind, portRow.dataset.portId);
        return;
      }
      const serviceCard = event.target.closest(".service-card");
      if (serviceCard && !event.target.closest("button, a, input, select, textarea")) openServiceDetailFresh(serviceCard.dataset.serviceId);
    });
    $$(".drawer-tab").forEach(button => button.addEventListener("click", () => switchDrawerTab(button.dataset.tab)));
    $("#log-search").addEventListener("input", () => renderLogLines());
    $("#log-severity").addEventListener("change", () => renderLogLines());
    $("#log-pause").addEventListener("click", () => {
      if (state.eventSource) { state.eventSource.close(); state.eventSource = null; $("#log-live-label").textContent = "Live paused"; $("#log-pause").textContent = "Resume"; }
      else if (state.selected) startLogStream(state.selected);
    });
    $("#log-refresh").addEventListener("click", () => state.selected && loadRecentLogs(state.selected, true));
    document.addEventListener("keydown", event => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (state.page !== "services" && state.page !== "overview") { location.hash = "#overview"; navigate(); }
        (state.page === "overview" ? $("#service-search") : $("#service-search-page")).focus();
      }
      if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-summary-filter]")) { event.preventDefault(); applySummaryFilter(event.target); }
      if ((event.key === "Enter" || event.key === " ") && event.target.matches(".service-card")) { event.preventDefault(); openServiceDetailFresh(event.target.dataset.serviceId); }
      if ((event.key === "Enter" || event.key === " ") && event.target.matches(".port-row[data-port-id]")) { event.preventDefault(); selectCheckTarget(event.target.dataset.portKind, event.target.dataset.portId); }
      if (event.key === "Escape") {
        if (!$("#manage-confirm-modal").hidden || $("#manual-port-confirm").open) return;
        closeDrawer();
        state.confirmCleanup?.();
        $("#rename-modal").hidden = true;
        state.renameTarget = null;
        state.renameGeneration++;
        closeServicePortEditor();
      }
    });
  }

  async function init() {
    bindEvents();
    try {
      const session = await api("/api/session");
      if (!session.password_configured) {
        showLogin();
        $("#login-error").textContent = "Dashboard password is not configured. Run scripts/setup.sh first.";
      } else if (session.authenticated) showApp();
      else showLogin();
    } catch { showLogin(); }
  }

  document.addEventListener("input", event => { if (event.target.matches("textarea[data-auto-height]")) resizeTextareas(); });
  window.addEventListener("resize", () => requestAnimationFrame(resizeTextareas));
  window.addEventListener("pagehide", clearSelection);
  function syncTrackingLog() {
    const tracking = state.selected && window.HostTracking?.active("service", state.selected);
    $("#log-pause").disabled = !!tracking;
    if (tracking) {
      state.eventSource?.close(); state.eventSource = null;
      $("#log-live-label").textContent = "Tracking · every 5s";
    } else if ($("#log-live-label").textContent.startsWith("Tracking")) {
      $("#log-live-label").textContent = "Live paused";
      $("#log-pause").textContent = "Resume";
    }
  }

  async function trackingCheck(kind, id, signal) {
    const options = {signal};
    if (kind === "manual-port") {
      const port = await api(`/api/ports/check?kind=manual&id=${encodeURIComponent(id)}`, options);
      if (!signal.aborted) updateCheckedPort(port);
      return;
    }
    const result = await api(`/api/services/${encodeURIComponent(id)}/live`, options);
    if (signal.aborted) return;
    const index = state.services.findIndex(item => item.id === id);
    if (index < 0) return;
    state.selectedUpdates.set(`service:${id}`, {version: ++state.updateVersion, record: result.service});
    state.services[index] = result.service;
    renderSummary(); renderServices();
    if (result.port) updateCheckedPort(result.port);
    if (state.selected === id) updateDrawerSummary();
    if (isManaged(result.service)) {
      const logs = await api(`/api/services/${encodeURIComponent(id)}/logs?lines=150`, options);
      if (!signal.aborted && state.selected === id) {
        state.eventSource?.close(); state.eventSource = null;
        state.logLines = logs.lines || []; renderLogLines();
        $("#log-live-label").textContent = "Tracking · every 5s";
        $("#log-pause").textContent = "Resume";
      }
    }
  }

  window.HostDashboard = { trackingCheck, syncTrackingLog, api, refreshAll, showToast, resizeTextareas, navigate, openServiceDetailFresh, selectCheckTarget, displayName, getOpenUrl, canOpen };
  init();
})();
