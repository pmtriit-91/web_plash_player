/**
 * Session Manager
 * Persists and restores game session tokens, flashvars, and user credentials across refreshes, popouts, and launches
 */

const SESSIONS_STORAGE_KEY = 'web_flash_game_sessions';
const CREDENTIALS_STORAGE_KEY = 'web_flash_user_credentials';
const ACTIVE_SESSION_KEY = 'web_flash_active_session_id';

export class SessionManager {
  /**
   * Retrieve all stored game sessions
   * @returns {Record<string, any>}
   */
  static getStoredSessions() {
    try {
      const raw = localStorage.getItem(SESSIONS_STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  /**
   * Save a game session
   * @param {string} presetId 
   * @param {object} sessionData 
   */
  static saveSession(presetId, sessionData) {
    if (!presetId || !sessionData) return;
    try {
      const sessions = this.getStoredSessions();
      sessions[presetId] = {
        ...sessionData,
        presetId,
        updatedAt: Date.now()
      };
      localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions));
      localStorage.setItem(ACTIVE_SESSION_KEY, presetId);
      console.log(`[SessionManager] Saved session for "${presetId}":`, sessions[presetId]);
    } catch (e) {
      console.warn('[SessionManager] Failed to save session:', e);
    }
  }

  /**
   * Get session for a specific preset
   * @param {string} presetId 
   * @returns {object|null}
   */
  static getSession(presetId) {
    if (!presetId) return null;
    const sessions = this.getStoredSessions();
    return sessions[presetId] || null;
  }

  /**
   * Get the active session ID
   * @returns {string|null}
   */
  static getActiveSessionId() {
    return localStorage.getItem(ACTIVE_SESSION_KEY) || null;
  }

  /**
   * Set active session ID
   * @param {string} presetId 
   */
  static setActiveSessionId(presetId) {
    if (presetId) {
      localStorage.setItem(ACTIVE_SESSION_KEY, presetId);
    }
  }

  /**
   * Get active session object
   * @returns {object|null}
   */
  static getActiveSession() {
    const activeId = this.getActiveSessionId();
    return activeId ? this.getSession(activeId) : null;
  }

  /**
   * Clear session for a preset
   * @param {string} presetId 
   */
  static clearSession(presetId) {
    const sessions = this.getStoredSessions();
    delete sessions[presetId];
    localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions));
  }

  /**
   * Clear all stored sessions
   */
  static clearAllSessions() {
    localStorage.removeItem(SESSIONS_STORAGE_KEY);
    localStorage.removeItem(ACTIVE_SESSION_KEY);
  }

  /**
   * Get user credentials for a preset
   * @param {string} presetId 
   * @param {object} defaultCreds 
   * @returns {object}
   */
  static getCredentials(presetId, defaultCreds = {}) {
    try {
      const raw = localStorage.getItem(CREDENTIALS_STORAGE_KEY);
      const allCreds = raw ? JSON.parse(raw) : {};
      return allCreds[presetId] || defaultCreds;
    } catch {
      return defaultCreds;
    }
  }

  /**
   * Save user credentials for a preset
   * @param {string} presetId 
   * @param {object} credentials 
   */
  static saveCredentials(presetId, credentials) {
    if (!presetId) return;
    try {
      const raw = localStorage.getItem(CREDENTIALS_STORAGE_KEY);
      const allCreds = raw ? JSON.parse(raw) : {};
      allCreds[presetId] = credentials;
      localStorage.setItem(CREDENTIALS_STORAGE_KEY, JSON.stringify(allCreds));
    } catch (e) {
      console.warn('[SessionManager] Failed to save credentials:', e);
    }
  }
}
