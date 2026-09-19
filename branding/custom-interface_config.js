// Appended to /run/web/config/interface_config.js at container start
// (see web/rootfs/etc/s6-overlay/scripts/config:147-150).
// Later assignments override the defaults above.

interfaceConfig.APP_NAME = 'DNS Meet';
interfaceConfig.NATIVE_APP_NAME = 'DNS Meet';
interfaceConfig.PROVIDER_NAME = 'DNS';

// Logo on welcome page header and in-meeting top-left watermark.
interfaceConfig.DEFAULT_WELCOME_PAGE_LOGO_URL = 'images/logo.png';
interfaceConfig.DEFAULT_LOGO_URL = 'images/logo.png';
interfaceConfig.SHOW_JITSI_WATERMARK = true;
interfaceConfig.JITSI_WATERMARK_LINK = '';
interfaceConfig.SHOW_POWERED_BY = false;

// Welcome page footer ("… on mobile" + App Store / Google Play / F-Droid links).
interfaceConfig.DISPLAY_WELCOME_FOOTER = false;
// Mobile-browser interstitial that pushes the store apps.
interfaceConfig.MOBILE_APP_PROMO = false;
