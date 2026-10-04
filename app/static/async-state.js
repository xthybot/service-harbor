/* Small, dependency-free request lifetimes shared by the browser and mock tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.HostAsync = api;
})(typeof globalThis === 'object' ? globalThis : this, () => {
  const cancelled = () => Object.assign(new Error(''), {name: 'AbortError', stale: true});
  class AuthLifecycle {
    constructor(fetcher, onInvalid) { this.fetcher = fetcher; this.onInvalid = onInvalid; this.epoch = 0; this.controllers = new Set(); this.authenticated = false; this.check = null; this.nextCheck = 0; this.backoff = 1000; }
    advance(authenticated = false) {
      this.epoch++; this.authenticated = authenticated;
      for (const controller of this.controllers) controller.abort();
      this.controllers.clear(); this.check = null; this.nextCheck = 0; this.backoff = 1000;
      return this.epoch;
    }
    async request(path, options = {}) {
      if (!this.authenticated && !['/api/login', '/api/logout', '/api/session'].includes(path)) throw cancelled();
      const epoch = this.epoch, controller = new AbortController();
      const upstream = options.signal;
      const abort = () => controller.abort();
      if (upstream?.aborted) abort();
      upstream?.addEventListener('abort', abort, {once: true});
      this.controllers.add(controller);
      try {
        const response = await this.fetcher(path, {...options, signal: controller.signal});
        if (epoch !== this.epoch || controller.signal.aborted) throw cancelled();
        const payload = await response.json().catch(() => ({}));
        if (epoch !== this.epoch || controller.signal.aborted) throw cancelled();
        if (!response.ok) {
          if (response.status === 401 && path !== '/api/login') {
            this.onInvalid();
            throw cancelled();
          }
          throw Object.assign(new Error(payload.detail || payload.message || `Request failed (${response.status})`), {status: response.status});
        }
        return payload;
      } catch (error) {
        if (epoch !== this.epoch || controller.signal.aborted) throw cancelled();
        throw error;
      } finally { this.controllers.delete(controller); upstream?.removeEventListener('abort', abort); }
    }
    async checkSession(now = Date.now()) {
      if (!this.authenticated) return false;
      if (this.check) return this.check;
      if (now < this.nextCheck) return null;
      const epoch = this.epoch;
      const pending = (async () => {
        try {
          const result = await this.request('/api/session');
          if (epoch !== this.epoch) return false;
          if (!result.authenticated) { this.onInvalid(); return false; }
          this.backoff = 1000; this.nextCheck = now + 2000; return true;
        } catch (error) {
          if (epoch !== this.epoch) return false;
          this.nextCheck = now + this.backoff; this.backoff = Math.min(this.backoff * 2, 30000); return null;
        } finally { if (this.check === pending) this.check = null; }
      })();
      this.check = pending;
      return pending;
    }
  }
  class Lifetime {
    constructor() { this.generation = 0; this.controller = new AbortController(); }
    renew() { this.controller.abort(); this.controller = new AbortController(); return ++this.generation; }
    capture(id) { return {id, generation: this.generation, signal: this.controller.signal}; }
    current(token, id) { return token.id === id && token.generation === this.generation && !token.signal.aborted; }
  }
  return {AuthLifecycle, Lifetime, cancelled};
});
