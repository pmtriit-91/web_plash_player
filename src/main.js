/**
 * Main Application Entry Point
 * Universal Agent OS - Web Flash Player
 */

import { FlashContainer } from './player/flash-container.js';
import { BridgeClient } from './player/bridge-client.js';
import { PlayerControls } from './player/controls.js';
import { GAME_PRESETS } from './player/presets.js';

document.addEventListener('DOMContentLoaded', async () => {
  const containerEl = document.getElementById('flash-container');
  const engineDot = document.getElementById('engine-dot');
  const engineText = document.getElementById('engine-text');
  const bridgeDot = document.getElementById('bridge-dot');
  const bridgeText = document.getElementById('bridge-text');
  const presetsListEl = document.getElementById('presets-list');

  // 1. Initialize Core Engine Container & Network Bridge Client
  const flashContainer = new FlashContainer(containerEl, {
    scaleMode: 'fit',
    quality: 'high',
    bridgeWsUrl: 'ws://localhost:8080'
  });

  const bridgeClient = new BridgeClient('http://localhost:8081', 'ws://localhost:8080');
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

  // 4. Render Preset Cards with Live Search
  const searchInput = document.getElementById('input-search-presets');
  const clearSearchBtn = document.getElementById('btn-clear-search');

  const renderPresetList = (filterQuery = '') => {
    presetsListEl.innerHTML = '';
    const q = filterQuery.trim().toLowerCase();

    const filtered = GAME_PRESETS.filter((preset) => {
      if (!q) return true;
      return (
        preset.name.toLowerCase().includes(q) ||
        preset.description.toLowerCase().includes(q) ||
        preset.category.toLowerCase().includes(q)
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
        <span>Không tìm thấy game nào phù hợp với "<strong>${filterQuery}</strong>"</span>
      `;
      presetsListEl.appendChild(emptyState);
      return;
    }

    filtered.forEach((preset) => {
      const card = document.createElement('div');
      card.className = 'preset-item';
      card.innerHTML = `
        <div class="preset-header">
          <span class="preset-name">${preset.name}</span>
          <span class="preset-tag">${preset.category}</span>
        </div>
        <p class="preset-desc">${preset.description}</p>
      `;

      card.addEventListener('click', () => {
        document.querySelectorAll('.preset-item').forEach((c) => c.classList.remove('active'));
        card.classList.add('active');

        if (preset.isHoiUc) {
          controls.showToast(`⚡ Đang kết nối ${preset.name}...`);
          fetch('http://localhost:8081/login-gunny-hoiuc?user=bughunter001&pass=123456%40abcD')
            .then((r) => r.json())
            .then((data) => {
              if (data.ok) {
                controls.showToast(`🎉 ${data.message}`);
                controls.runGame(data.proxiedSwfUrl, { flashvars: data.flashvars });
              } else {
                controls.showToast(`Lỗi: ${data.error}`);
              }
            })
            .catch((e) => {
              controls.showToast(`Lỗi API: ${e.message}`);
            });
        } else if (preset.isGunny && preset.isZing) {
          controls.showToast(`⚡ Đang kết nối ${preset.name}...`);
          const btnSync = document.getElementById('btn-sync-zing');
          if (btnSync) {
            btnSync.click();
          } else {
            controls.runGame(preset.swfUrl, { flashvars: preset.flashvars });
          }
        } else {
          controls.showToast(`Đang nạp preset: ${preset.name}...`);
          controls.runGame(preset.swfUrl, { flashvars: preset.flashvars });
        }
      });

      presetsListEl.appendChild(card);
    });
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
