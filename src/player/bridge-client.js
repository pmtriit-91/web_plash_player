/**
 * Bridge Client Utility
 * Monitors Bridge Health and provides WebSocket-to-TCP tunnels for Flash Games
 */

export class BridgeClient {
  constructor(bridgeHttpUrl = 'http://localhost:8081', bridgeWsUrl = 'ws://localhost:8080') {
    this.httpUrl = bridgeHttpUrl;
    this.wsUrl = bridgeWsUrl;
    this.isAlive = false;
    this.listeners = [];
  }

  onStatusChange(callback) {
    this.listeners.push(callback);
  }

  notify(status) {
    this.isAlive = status.alive;
    this.listeners.forEach((fn) => fn(status));
  }

  async checkHealth() {
    try {
      const response = await fetch(`${this.httpUrl}/health`, { method: 'GET', signal: AbortSignal.timeout(2000) });
      if (response.ok) {
        const data = await response.json();
        this.notify({ alive: true, data, error: null });
        return true;
      }
    } catch (err) {
      this.notify({ alive: false, data: null, error: err.message });
      return false;
    }
    return false;
  }

  getProxiedUrl(targetUrl) {
    if (!targetUrl) return '';
    if (targetUrl.startsWith('data:') || targetUrl.startsWith('blob:')) return targetUrl;
    return `${this.httpUrl}/proxy?url=${encodeURIComponent(targetUrl)}`;
  }

  createSocketTunnel(host, port) {
    const wsEndpoint = `${this.wsUrl}?host=${encodeURIComponent(host)}&port=${encodeURIComponent(port)}`;
    return new WebSocket(wsEndpoint);
  }
}
