/**
 * Presets Library for Web Flash Player
 * Includes Gunny / DDTank server configs, retro game benchmarks, and sample SWFs
 */

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
    swfUrl: 'http://localhost:8081/host/flash1.gunnyhoiuc.com:88/Loading.swf',
    flashvars: {
      user: 'bughunter001',
      config: 'http://localhost:8081/host/flash1.gunnyhoiuc.com:88/config.xml'
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
    swfUrl: 'http://localhost:8081/host/123gn.net/flash3/Loading.swf',
    isGunny: true,
    isPrivate: true,
    serverUrl: 'https://123gn.net/play/1001',
    flashvars: {
      config: 'http://localhost:8081/host/123gn.net/flash3/config3.xml'
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
    swfUrl: 'http://localhost:8081/host/res737.gn.zing.vn/flash/Loading.swf',
    isGunny: true,
    isZing: true,
    serverUrl: 'https://id-levelup.gn.zing.vn',
    flashvars: {
      config: 'http://localhost:8081/host/s737.gn.zing.vn/config.xml'
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
    swfUrl: '/samples/alien_hominid.swf',
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
    swfUrl: '/samples/flyguy.swf',
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
    swfUrl: '/samples/logo-anim.swf',
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  }
];
