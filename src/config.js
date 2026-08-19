/**
 * Global Configuration & Environment Resolver
 * Dynamic endpoint discovery without hardcoded IP/hosts
 */

export const CONFIG = {
  get HTTP_HOST() {
    return window.location.hostname || 'localhost';
  },
  get BRIDGE_PORT() {
    return 8081;
  },
  get WS_PORT() {
    return 8080;
  },
  get BRIDGE_HTTP_URL() {
    return `http://${this.HTTP_HOST}:${this.BRIDGE_PORT}`;
  },
  get BRIDGE_WS_URL() {
    return `ws://${this.HTTP_HOST}:${this.WS_PORT}`;
  }
};

/**
 * Build dynamic API URL with query params
 * @param {string} path 
 * @param {Record<string, any>} params 
 * @returns {string}
 */
export function buildApiUrl(path, params = {}) {
  const base = CONFIG.BRIDGE_HTTP_URL;
  const url = new URL(path.startsWith('/') ? path : `/${path}`, base);
  Object.entries(params).forEach(([key, val]) => {
    if (val !== undefined && val !== null && val !== '') {
      url.searchParams.set(key, String(val));
    }
  });
  return url.toString();
}

/**
 * Build host proxy path: /host/<domain>/<path>
 * @param {string} targetHost 
 * @param {string} targetPath 
 * @returns {string}
 */
export function buildHostProxiedUrl(targetHost, targetPath = '/') {
  const cleanHost = targetHost.replace(/^https?:\/\//i, '').replace(/\/+$/, '');
  const cleanPath = targetPath.startsWith('/') ? targetPath : `/${targetPath}`;
  return `${CONFIG.BRIDGE_HTTP_URL}/host/${cleanHost}${cleanPath}`;
}
