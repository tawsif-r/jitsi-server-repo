// Appended to /run/web/config/config.js at container start
// (see web/rootfs/etc/s6-overlay/scripts/config:143-145).

// Dynamic branding: logo + English label overrides ("Jitsi Meet" -> "DNS Meet").
// English strings are baked into libs/app.bundle.min.js, so lang/main.json alone
// is not enough; this JSON is merged into i18n at runtime.
config.dynamicBrandingUrl = '/static/branding.json';
