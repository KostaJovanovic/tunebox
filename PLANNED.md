# Planned features

What's been asked for, what's built, and what's waiting. Newest decisions at the bottom of each section.

## Built (not yet committed or deployed)

1. **The server's address in Settings.** The last section of Settings, Network, shows where other devices open Tunebox (the server's LAN address with this page's port and path), with a Copy button. Found afresh at most once a minute (`tunebox/network.py`). Also in the terminal interface's Settings and in `tunebox whoami`.
2. **The Wi-Fi's name in Settings.** Under the address. The admin types it in the House tab ("The Wi-Fi to join"); when that's empty, it is the Wi-Fi the server itself is on (Windows, macOS, or Linux through nmcli, iwgetid or iw). ele is on a cable and can't tell, so set it there by hand. `tunebox house set network NAME` (or `detect`).
3. **Switch: theme and accent.** A new feature switch (`look`). Off: the Theme and Accent pickers in Settings are hidden, and every device follows the system's light or dark with the house's accent. The admin's device keeps its own.
4. **Switch: names in Settings.** A new feature switch (`namelist`). Off: the People section in Settings is hidden (and the row in the terminal interface). The name button in the top bar still switches names, and the admin panel's People tab always stays.
5. **Search results: Play only.** Search results and a pasted link's song have no Play next button; Play (which asks now, next, or at the end) and the song's menu still offer it.
6. **The name form full-screen on phones.** Adding or editing a name takes the whole screen on a phone; picking a name stays a sheet.
7. **Drawn icons for names.** The emoji a name wears is drawn as a line icon in its badge (`web/shared/avatars.js`), and the pass phrase's 🔒 is a drawn padlock. people.json still keeps the emoji, so old names keep theirs and the command line shows them. 17 new ones: microphone, record, trumpet, violin, owl, rabbit, frog, penguin, moon, lightning, flame, mountain, wave, coffee, game controller, ghost, crown (30 in all).

8. **Performance mode**, for devices with little power: no transitions, springs, blur or shadows (`html[data-lite]`, motion.css; `calm()` in motion.js), and `api/state` every 3 seconds instead of every second, with the progress bar sliding over 2.9 s between answers. The spinner, the loading bar and the recap's bars stay. On by itself with 2 GB of memory or less (`navigator.deviceMemory`, Chrome-based browsers only) or 2 cores or fewer; Settings → This device: Auto / On / Off (`tb_perf`), with a line saying what Auto decided here. The row stays when the theme and accent switch is off.
9. **A steady 90 fps on the phone's Now playing screen.** The blurred cover behind it (`.cbg`) shows only once the canvas is still (`.canvas.still`) and fades in; it goes at once when the canvas moves. And nothing touches `<body>` when it opens or closes (a class there restyled the whole page and cost a frame when the finger lifted); `overscroll-behavior` keeps a wheel from scrolling the page behind. Before: 75–79 fps with 15–35 slow frames per opening. After: swipes, flicks and taps open and close it with no dropped frame while it moves.

Fixed while testing on a phone (Nothing Phone 4a, Firefox 156):

- **The address with a VPN on.** A machine whose VPN takes every route showed the VPN's address. Now the address shown is the server's one on the same network as the device asking (`network.best`; behind Caddy, from X-Forwarded-For), in its own route, `api/network`.
- **The keyboard over a pop-up's buttons.** Firefox and Safari don't shorten the page when the keyboard opens, so Add and Back in the name form were under it. `--kb` (ui.js) is the keyboard's height, and a phone's pop-ups sit above it.

## Parked

- **Stop polling on a hidden page.** Every page asks `api/state` once a second, even in a background tab. Pause while `document.hidden`, ask at once on return. Firefox for Android already nearly stops it (3 requests a minute in the background, 1 with the screen off, under 1% CPU), so it matters for desktop tabs and an app's webview.
- **Small tap targets.** The artist links under a card's title and Play all on Home are 16–18 px tall on a phone.
- **An app (Tauri)**: a remote control only, not the server. At launch it tries the saved Tunebox addresses (no Wi-Fi name, which needs location permission on phones) and finds a new one through an mDNS announcement from the server; nothing runs in the background. Windows and Android first; macOS needs a Mac to build, iOS a paid Apple account.
- **Install as an app (PWA).** The manifest and service worker are there, but browsers only install over HTTPS or on localhost. On plain HTTP: Add to Home Screen.

## Dropped

- **HTTPS on ele.** Every way that avoids warnings needs a domain (a bought one, or a free DuckDNS name) and a Caddy build with a DNS plugin; `tls internal` needs a certificate installed on every device. Not worth it for now.
