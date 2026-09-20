-- Extra options for mod_reservations. Mounted into the prosody container as
-- /config/conf.d/, which the entrypoint copies next to the generated
-- jitsi-meet.cfg.lua. Module itself is enabled by PROSODY_RESERVATION_ENABLED=1.
-- Re-open the host section so these attach to meet.jitsi, not to whatever
-- Component the generated file ended on.
VirtualHost "meet.jitsi"
    -- let the reservation API return a "password" field that locks the room
    reservations_enable_password_support = true
    -- fail fast if the scheduler is down (default 20s)
    reservations_api_timeout = 5
