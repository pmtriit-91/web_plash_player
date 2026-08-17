/**
 * Presets Library for Web Flash Player
 * Includes Gunny / DDTank server configs, retro game benchmarks, and sample SWFs
 */

export const GAME_PRESETS = [
  {
    id: 'gunny-local',
    name: 'Gunny DDTank (Local / Private Server)',
    category: 'MMORPG / Turn-based Shooter',
    description: 'Cấu hình kết nối Game Server Gunny qua WebSocket-to-TCP Bridge (AVM2 / ActionScript 3.0).',
    swfUrl: 'http://localhost:8081/proxy?url=https://raw.githubusercontent.com/pmtriit-91/web_plash_player/main/sample-assets/gunny_demo.swf',
    fallbackSwf: 'https://raw.githubusercontent.com/pmtriit-91/web_plash_player/main/sample-assets/gunny_demo.swf',
    isGunny: true,
    serverConfig: {
      host: '127.0.0.1',
      port: 9200,
      resourcePath: 'http://127.0.0.1/resource/',
      user: 'admin',
      key: 'gunny_session_key'
    },
    flashvars: {
      user: 'player_test',
      key: 'd41d8cd98f00b204e9800998ecf8427e',
      v: '1000',
      rand: '123456',
      config: 'http://127.0.0.1/config.xml'
    },
    width: 1000,
    height: 600,
    aspectRatio: '5:3'
  },
  {
    id: 'as3-benchmark',
    name: 'ActionScript 3.0 Physics & Vector Benchmark',
    category: 'Benchmark Engine',
    description: 'Thử nghiệm hiệu năng AVM2, WebGL rendering và tính toán vật lý đa đối tượng.',
    swfUrl: 'https://raw.githubusercontent.com/ruffle-rs/ruffle/master/web/packages/demo/public/assets/as3_ball.swf',
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  },
  {
    id: 'retro-classic',
    name: 'Retro Flash Arcade Demo',
    category: 'Arcade / Retro',
    description: 'Trò chơi Flash kinh điển thử nghiệm âm thanh, bàn phím và đồ họa vector 60 FPS.',
    swfUrl: 'https://raw.githubusercontent.com/ruffle-rs/ruffle/master/web/packages/demo/public/assets/as2_pacman.swf',
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  }
];
