// Appended to /run/web/config/config.js at container start
// (see web/rootfs/etc/s6-overlay/scripts/config:143-145).

// Dynamic branding: logo + English label overrides ("Jitsi Meet" -> "DNS Meet").
// English strings are baked into libs/app.bundle.min.js, so lang/main.json alone
// is not enough; this JSON is merged into i18n at runtime.
config.dynamicBrandingUrl = '/static/branding.json';

// ---------------------------------------------------------------------------
// Layout: always speaker (stage) view. Whoever speaks is shown large for
// everyone, including Jibri recordings. Tile/grid view button is removed.
// See RECORDING-AND-LAYOUT.md.
config.disableTileView = true;
config.filmstrip = Object.assign({}, config.filmstrip, {
    // Show only the dominant speaker on stage, not several at once.
    disableStageFilmstrip: true
});

// ---------------------------------------------------------------------------
// Moderator "Turn camera on/off" for a participant (NOT a stock Jitsi feature).
// Adds two entries to the remote participant "..." menu. On click, a moderator
// sends a private endpoint message; the target's browser turns its own camera
// on/off if the sender is a moderator. Relies on Jitsi internals (APP.conference,
// APP.API) - re-test after every image upgrade. See RECORDING-AND-LAYOUT.md.
(function() {
    function camIcon(slashed) {
        return 'data:image/svg+xml;base64,' + btoa(
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
            + '<path fill="#fff" d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z"/>'
            + (slashed ? '<path stroke="#fff" stroke-width="2" d="M2 2l20 20"/>' : '')
            + '</svg>');
    }

    config.customParticipantMenuButtons = [
        { id: 'force-cam-on', text: 'Turn camera on', icon: camIcon(false) },
        { id: 'force-cam-off', text: 'Turn camera off', icon: camIcon(true) }
    ];
})();

(function forceCamera() {
    // Menu button id / message type -> muted state to apply on the target.
    var ACTIONS = { 'force-cam-on': false, 'force-cam-off': true };
    var ENDPOINT_MESSAGE = 'conference.endpoint_message_received';
    var boundRoom = null;
    var apiPatched = false;

    function patchApi() {
        if (apiPatched || !window.APP || !APP.API || !APP.API.notifyParticipantMenuButtonClicked) {
            return;
        }
        var original = APP.API.notifyParticipantMenuButtonClicked.bind(APP.API);

        APP.API.notifyParticipantMenuButtonClicked = function(key, participantId) {
            var room = APP.conference && APP.conference._room;

            if (ACTIONS.hasOwnProperty(key) && room) {
                if (room.isModerator()) {
                    room.sendEndpointMessage(participantId, { type: key });
                } else {
                    console.warn('[force-cam] only moderators can turn cameras on/off');
                }
            }

            return original.apply(null, arguments);
        };
        apiPatched = true;
    }

    function bindRoom() {
        var room = window.APP && APP.conference && APP.conference._room;

        if (!room || room === boundRoom) {
            return;
        }
        boundRoom = room;
        room.on(ENDPOINT_MESSAGE, function(sender, payload) {
            if (!payload || !ACTIONS.hasOwnProperty(payload.type)) {
                return;
            }
            if (!sender || sender.getRole() !== 'moderator') {
                console.warn('[force-cam] ignored request from non-moderator');

                return;
            }
            APP.conference.muteVideo(ACTIONS[payload.type]);
        });
    }

    // Config runs before the app boots and the room is recreated on reconnect,
    // so keep checking.
    setInterval(function() {
        patchApi();
        bindRoom();
    }, 1000);
})();
