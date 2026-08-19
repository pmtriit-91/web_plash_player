/**
 * Presets Library for Web Flash Player
 * Universal game configurations consuming centralized URLs registry
 */

import { GAME_URLS, SAMPLE_SWF_PATHS } from '../utils/urls.js';

export const GAME_PRESETS = [
  {
    id: 'gunny-hoiuc',
    name: 'Gunny Hồi Ức (S3 - Gà Vàng)',
    category: 'Gunny Hồi Ức v2.3 ⚡',
    account: 'bughunter001',
    accountType: 'Tài khoản Game',
    statusText: '⚡ Đăng nhập tự động',
    description: 'Máy chủ Gunny Hồi Ức v2.3 với kết nối tốc độ cao và bộ giải mã đồ họa 60 FPS.',
    isGunny: true,
    isHoiUc: true,
    get swfUrl() {
      return GAME_URLS.getGunnyHoiUcSwf();
    },
    get flashvars() {
      return {
        user: this.account,
        config: GAME_URLS.getGunnyHoiUcConfig()
      };
    },
    width: 1000,
    height: 600,
    aspectRatio: '5:3'
  },
  {
    id: 'gunny-123gn',
    name: '123gn.net (Gà Thiện Xạ - S1001)',
    category: 'Private Server ⚡',
    account: 'player_123gn',
    accountType: 'Private Auth',
    statusText: '🔑 Smart Gateway Token',
    description: 'Máy chủ Gunny Private hồi ức với bộ định tuyến Smart Socket Gateway và bảo mật tự động.',
    isGunny: true,
    isPrivate: true,
    get serverUrl() {
      return GAME_URLS.get123gnPlayUrl();
    },
    get swfUrl() {
      return GAME_URLS.get123gnSwf();
    },
    get flashvars() {
      return {
        config: GAME_URLS.get123gnConfig()
      };
    },
    width: 1000,
    height: 600,
    aspectRatio: '5:3'
  },
  {
    id: 'gunny-zing-737',
    name: 'Zing Gunny (Gà Cầu Duyên - S737)',
    category: 'Zing Official ⚡',
    account: 'zing_session_user',
    accountType: 'Zing ID Account',
    statusText: '🔗 Đồng bộ từ Chrome',
    description: 'Máy chủ chính thức Zing Gunny. Tự động đồng bộ 1-click trực tiếp từ phiên đăng nhập trình duyệt.',
    isGunny: true,
    isZing: true,
    get serverUrl() {
      return GAME_URLS.getZingAuthUrl();
    },
    get swfUrl() {
      return GAME_URLS.getZingSwf();
    },
    get flashvars() {
      return {
        config: GAME_URLS.getZingConfig()
      };
    },
    width: 1000,
    height: 600,
    aspectRatio: '5:3'
  },
  {
    id: 'alien-hominid',
    name: 'Alien Hominid (Kinh điển)',
    category: 'Action Arcade Game',
    account: 'Khách (Guest)',
    accountType: 'Arcade Offline',
    statusText: '🎮 Chơi ngay',
    description: 'Game bắn súng Flash kinh điển nổi tiếng thế giới. Thử nghiệm đồ họa 60 FPS, âm thanh và bàn phím (A, S, Phím mũi tên).',
    get swfUrl() {
      return SAMPLE_SWF_PATHS.ALIEN_HOMINID;
    },
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  },
  {
    id: 'flyguy-game',
    name: 'FlyGuy (Phiêu lưu)',
    category: 'Adventure / Interactive',
    account: 'Khách (Guest)',
    accountType: 'Interactive Demo',
    statusText: '🎮 Chơi ngay',
    description: 'Game phiêu lưu tương tác âm nhạc và hiệu ứng vector Flash mượt mà.',
    get swfUrl() {
      return SAMPLE_SWF_PATHS.FLYGUY;
    },
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  },
  {
    id: 'logo-anim',
    name: 'Flash Vector & Animation Demo',
    category: 'Vector Graphics',
    account: 'Khách (Guest)',
    accountType: 'Graphics Demo',
    statusText: '🔮 Vector WebGL',
    description: 'Trình diễn hiệu ứng đồ họa Vector và WebGL shader của WebAssembly Flash Engine.',
    get swfUrl() {
      return SAMPLE_SWF_PATHS.LOGO_ANIMATION;
    },
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  }
];
