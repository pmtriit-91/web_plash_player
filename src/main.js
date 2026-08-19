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

  // 4. Render Preset Cards
  GAME_PRESETS.forEach((preset) => {
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

  console.log('[App] Web Flash Player initialized completely.');
});
