/**
 * Centralized Game URLs, Hosts, and Endpoints Registry
 * Universal Agent OS - Web Flash Player
 */

import { buildHostProxiedUrl } from '../config.js';

/**
 * Known Game Hostnames & Service Domains
 */
export const GAME_HOSTS = {
  GUNNY_HOI_UC: {
    RESOURCE_HOST: 'flash1.gunnyhoiuc.com:88',
    QUEST_HOST: 'quest1.gunnyhoiuc.com:89',
    API_HOST: 'api2.gunnyhoiuc.com',
    DEFAULT_SERVER_ID: 1001,
    SOCKET_PORT: 9200
  },
  GUNNY_123GN: {
    DOMAIN: '123gn.net',
    PLAY_URL: 'https://123gn.net/play/1001',
    FLASH_DIR: '/flash3'
  },
  ZING_GUNNY: {
    DEFAULT_SERVER_ID: '737',
    RESOURCE_DOMAIN_TEMPLATE: 'res{serverId}.gn.zing.vn',
    CONFIG_DOMAIN_TEMPLATE: 's{serverId}.gn.zing.vn',
    QUEST_DOMAIN_TEMPLATE: 'quest{serverId}.gn.zing.vn',
    AUTH_LOGIN_URL: 'https://id-levelup.gn.zing.vn'
  }
};

/**
 * Built-in Sample SWF Assets
 */
export const SAMPLE_SWF_PATHS = {
  ALIEN_HOMINID: '/samples/alien_hominid.swf',
  FLYGUY: '/samples/flyguy.swf',
  LOGO_ANIMATION: '/samples/logo-anim.swf'
};

/**
 * Dynamic URL Resolvers for Presets & Bridge Connectors
 */
export const GAME_URLS = {
  /**
   * Gunny Hồi Ức Endpoints
   */
  getGunnyHoiUcSwf() {
    return buildHostProxiedUrl(GAME_HOSTS.GUNNY_HOI_UC.RESOURCE_HOST, '/Loading.swf');
  },
  getGunnyHoiUcConfig() {
    return buildHostProxiedUrl(GAME_HOSTS.GUNNY_HOI_UC.RESOURCE_HOST, '/config.xml');
  },

  /**
   * 123gn.net Private Server Endpoints
   */
  get123gnPlayUrl() {
    return GAME_HOSTS.GUNNY_123GN.PLAY_URL;
  },
  get123gnSwf() {
    return buildHostProxiedUrl(
      GAME_HOSTS.GUNNY_123GN.DOMAIN,
      `${GAME_HOSTS.GUNNY_123GN.FLASH_DIR}/Loading.swf`
    );
  },
  get123gnConfig() {
    return buildHostProxiedUrl(
      GAME_HOSTS.GUNNY_123GN.DOMAIN,
      `${GAME_HOSTS.GUNNY_123GN.FLASH_DIR}/config3.xml`
    );
  },

  /**
   * Zing Gunny Official Server Endpoints
   * @param {string} serverId 
   */
  getZingSwf(serverId = GAME_HOSTS.ZING_GUNNY.DEFAULT_SERVER_ID) {
    const host = GAME_HOSTS.ZING_GUNNY.RESOURCE_DOMAIN_TEMPLATE.replace('{serverId}', serverId);
    return buildHostProxiedUrl(host, '/flash/Loading.swf');
  },
  getZingConfig(serverId = GAME_HOSTS.ZING_GUNNY.DEFAULT_SERVER_ID) {
    const host = GAME_HOSTS.ZING_GUNNY.CONFIG_DOMAIN_TEMPLATE.replace('{serverId}', serverId);
    return buildHostProxiedUrl(host, '/config.xml');
  },
  getZingAuthUrl() {
    return GAME_HOSTS.ZING_GUNNY.AUTH_LOGIN_URL;
  },

  /**
   * Sample Flash Games
   */
  getSampleUrl(key) {
    return SAMPLE_SWF_PATHS[key] || '';
  }
};
