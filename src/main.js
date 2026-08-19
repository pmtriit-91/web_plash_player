/**
 * Main Application Entry Point
 * Universal Agent OS - Web Flash Player
 */

import { CONFIG, buildApiUrl } from './config.js';
import { FlashContainer } from './player/flash-container.js';
import { BridgeClient } from './player/bridge-client.js';
import { PlayerControls } from './player/controls.js';
import { GAME_PRESETS } from './player/presets.js';
import { SessionManager } from './player/session-manager.js';

document.addEventListener('DOMContentLoaded', async () => {
  const containerEl = document.getElementById('flash-container');
  const engineDot = document.getElementById('engine-dot');
  const engineText = document.getElementById('engine-text');
  const bridgeDot = document.getElementById('bridge-dot');
  const bridgeText = document.getElementById('bridge-text');
  const presetsListEl = document.getElementById('presets-list');

  // 1. Initialize Core Engine Container & Network Bridge Client dynamically
  const flashContainer = new FlashContainer(containerEl, {
    scaleMode: 'fit',
    quality: 'high',
    bridgeWsUrl: CONFIG.BRIDGE_WS_URL
  });

  const bridgeClient = new BridgeClient(CONFIG.BRIDGE_HTTP_URL, CONFIG.BRIDGE_WS_URL);
  const controls = new PlayerControls(flashContainer, bridgeClient);

  // 2. Initialize Ruffle WASM Core
  try {
    await flashContainer.initRuffle();
    engineDot.className = 'pulse-dot';
    engineText.textContent = 'WASM 9.1 Sẵn sàng';
  } catch (err) {
    console.error('WASM Init Failed:', err);
    engineDot.className = 'pulse-dot danger';
    engineText.textContent = 'WASM Lỗi tải';
  }

  // 3. Monitor Bridge Gateway Health
  const updateBridgeStatus = async () => {
    const isAlive = await bridgeClient.checkHealth();
    if (isAlive) {
      bridgeDot.className = 'pulse-dot';
      bridgeText.textContent = 'Bridge: Đã kết nối';
    } else {
      bridgeDot.className = 'pulse-dot warning';
      bridgeText.textContent = 'Bridge: Offline (Chạy npm run bridge)';
    }
  };

  await updateBridgeStatus();
  setInterval(updateBridgeStatus, 5000);

  // 4. Render Preset Cards with Live Search, Deletion, and Session Persistence
  const searchInput = document.getElementById('input-search-presets');
  const clearSearchBtn = document.getElementById('btn-clear-search');

  let deletedPresets = [];
  try {
    const saved = localStorage.getItem('deleted_presets');
    if (saved) deletedPresets = JSON.parse(saved);
  } catch (e) {
    deletedPresets = [];
  }

  const renderPresetList = (filterQuery = '') => {
    presetsListEl.innerHTML = '';
    const q = filterQuery.trim().toLowerCase();

    // Filter out deleted cards
    const activePresets = GAME_PRESETS.filter((p) => !deletedPresets.includes(p.id));

    const filtered = activePresets.filter((preset) => {
      if (!q) return true;
      return (
        preset.name.toLowerCase().includes(q) ||
        preset.description.toLowerCase().includes(q) ||
        preset.category.toLowerCase().includes(q) ||
        (preset.account && preset.account.toLowerCase().includes(q))
      );
    });

    if (filtered.length === 0) {
      const emptyState = document.createElement('div');
      emptyState.className = 'empty-search-state';
      emptyState.innerHTML = `
        <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          <line x1="8" y1="11" x2="14" y2="11"></line>
        </svg>
        <span>${q ? `Không tìm thấy game nào phù hợp với "<strong>${filterQuery}</strong>"` : 'Tất cả card đã bị xóa hoặc ẩn.'}</span>
      `;
      presetsListEl.appendChild(emptyState);
    } else {
      filtered.forEach((preset) => {
        const card = document.createElement('div');
        card.className = 'preset-item';
        card.innerHTML = `
          <div class="preset-header">
            <span class="preset-name">${preset.name}</span>
            <div class="preset-actions">
              <span class="preset-tag">${preset.category}</span>
              <button class="btn-delete-preset" data-id="${preset.id}" title="Xóa card này">
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"></polyline>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                </svg>
              </button>
            </div>
          </div>
          <div class="preset-account-row">
            <div class="preset-account-badge" title="Tài khoản / Nhân vật">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
              </svg>
              <span class="account-name">${preset.account || 'Khách (Guest)'}</span>
            </div>
            <span class="preset-status-pill">${preset.statusText || '⚡ Sẵn sàng'}</span>
          </div>
          <p class="preset-desc">${preset.description}</p>
        `;

        // Card Click -> Run Game with Session Persistence
        card.addEventListener('click', async () => {
          document.querySelectorAll('.preset-item').forEach((c) => c.classList.remove('active'));
          card.classList.add('active');

          // Check if we have an active saved session for this game
          const existingSession = SessionManager.getSession(preset.id);

          if (preset.isHoiUc) {
            controls.showToast(`⚡ Đang kết nối ${preset.name}...`);
            
            // If we have a saved session and it's fresh (< 2 hours), use it immediately
            if (existingSession && existingSession.proxiedSwfUrl && (Date.now() - existingSession.updatedAt < 2 * 3600 * 1000)) {
              controls.showToast(`⚡ Tái sử dụng phiên đăng nhập gần nhất (${existingSession.flashvars?.user || preset.account})`);
              controls.runGame(existingSession.proxiedSwfUrl, { flashvars: existingSession.flashvars }, preset.id);
              return;
            }

            // Retrieve credentials dynamically without hardcoded strings
            const userCreds = SessionManager.getCredentials(preset.id, {
              user: preset.account || 'bughunter001',
              pass: '123456@abcD'
            });

            try {
              const loginApiUrl = buildApiUrl('/login-gunny-hoiuc', {
                user: userCreds.user,
                pass: userCreds.pass
              });
              const res = await fetch(loginApiUrl);
              const data = await res.json();

              if (data.ok) {
                // Save session in SessionManager
                SessionManager.saveSession(preset.id, {
                  ...data,
                  userName: userCreds.user
                });
                controls.showToast(`🎉 ${data.message}`);
                controls.runGame(data.proxiedSwfUrl, { flashvars: data.flashvars }, preset.id);
              } else {
                controls.showToast(`Lỗi: ${data.error}`);
              }
            } catch (e) {
              controls.showToast(`Lỗi API: ${e.message}`);
            }
          } else if (preset.isGunny && preset.isZing) {
            // If we already have a synced Zing session, load it directly
            if (existingSession && existingSession.proxiedSwfUrl) {
              controls.showToast(`⚡ Đang nạp phiên Zing đã đồng bộ: ${existingSession.userName || 'Player'}`);
              controls.runGame(existingSession.proxiedSwfUrl, { flashvars: existingSession.flashvars || {}, baseUrl: existingSession.baseUrl }, preset.id);
              return;
            }

            // Otherwise trigger Chrome sync
            controls.showToast(`⚡ Đang kết nối ${preset.name}...`);
            const btnSync = document.getElementById('btn-sync-zing');
            if (btnSync) {
              btnSync.click();
            } else {
              controls.runGame(preset.swfUrl, { flashvars: preset.flashvars }, preset.id);
            }
          } else {
            controls.showToast(`Đang nạp preset: ${preset.name}...`);
            controls.runGame(preset.swfUrl, { flashvars: preset.flashvars }, preset.id);
          }
        });

        // Delete Button Click
        const btnDelete = card.querySelector('.btn-delete-preset');
        if (btnDelete) {
          btnDelete.addEventListener('click', (e) => {
            e.stopPropagation();
            if (!deletedPresets.includes(preset.id)) {
              deletedPresets.push(preset.id);
              localStorage.setItem('deleted_presets', JSON.stringify(deletedPresets));
            }
            controls.showToast(`🗑️ Đã xóa card "${preset.name}".`);
            renderPresetList(searchInput ? searchInput.value : '');
          });
        }

        presetsListEl.appendChild(card);
      });
    }

    // Append Restore Bar if any presets are deleted
    if (deletedPresets.length > 0) {
      const restoreBar = document.createElement('div');
      restoreBar.className = 'restore-presets-bar';
      restoreBar.innerHTML = `
        <span>Đã ẩn ${deletedPresets.length} card</span>
        <button class="btn-restore-presets" id="btn-restore-all">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
          Khôi phục tất cả
        </button>
      `;

      const btnRestore = restoreBar.querySelector('#btn-restore-all');
      if (btnRestore) {
        btnRestore.addEventListener('click', () => {
          deletedPresets = [];
          localStorage.removeItem('deleted_presets');
          controls.showToast('✨ Đã khôi phục toàn bộ danh sách card ban đầu!');
          renderPresetList(searchInput ? searchInput.value : '');
        });
      }

      presetsListEl.appendChild(restoreBar);
    }
  };

  renderPresetList();

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const val = e.target.value;
      if (clearSearchBtn) {
        clearSearchBtn.style.display = val ? 'flex' : 'none';
      }

      // Auto switch to Presets tab when searching
      const presetsTabBtn = document.querySelector('.tab-btn[data-tab="tab-presets"]');
      if (presetsTabBtn && !presetsTabBtn.classList.contains('active')) {
        presetsTabBtn.click();
      }

      renderPresetList(val);
    });

    if (clearSearchBtn) {
      clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearSearchBtn.style.display = 'none';
        renderPresetList('');
        searchInput.focus();
      });
    }
  }

  console.log('[App] Web Flash Player initialized completely.');
});
