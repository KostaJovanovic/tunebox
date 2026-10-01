# Tunebox patch notes - the source

THE ONLY PLACE THE PAGE'S PROSE IS WRITTEN. `python dev/patch.py` builds one
file from it, and that file may not be hand-edited:

  web/patch.html   the patch notes as a page, at /patch, dressed by the app's
                   own colours (base.css) and the device's theme and accent
                   (shared/look.js)
  web/patch.json   the same notes as data, for the patch notes page on the Ele
                   home page (homeapps), which shows every app's notes

`save.bat` and `save.sh` run it on every commit, after stamping the version, so
what is committed follows the prose. Settings links to the page from its last
section, Version.

## What goes on the page, and what does not

**Write only what a person in the house would notice.** That is the whole
selection rule. A reader opens /patch to find out what is different for them:
the people who pick songs, and the one who runs the server. Bullets about
module splits, refactors and deploy tooling do not answer that. They bury it.

So: a feature, a repair somebody could have hit, or a speed-up somebody could
have felt. Nothing else. If a day has nothing in it for them, say so in one
plain line and move on.

**The admin's secret ways in are never mentioned here.** The page is read by
the whole house. Say that the admin has a password; do not say how its prompt
is opened.

**The page never says "seminar".** Groups are called seminars in the code; a
reader only ever sees "groups".

## Versioning

The version is the commit count. `save.bat` and `save.sh` stamp `COMMIT_COUNT`
and `VERSION` into `web/shared/version.js` on every commit (`dev/patch.py bump`,
which counts up from that file, never from git), so commit number N is version
`0.NN`. A group carries the span of commit numbers its day covers, and the high
end of the newest group must equal `VERSION`. The page prints the version in
its header, and `dev/patch.py` warns when the newest group ends anywhere else.
Never let them drift.

Milestones are crowned, not reached. `RELEASE_COMMITS` in version.js holds the
commit numbers promoted to a major release - `1.0`, `2.0` and so on. The list
is empty for now, so every version is still `0.NN`. To crown one, add its commit
number there, and give that day the boldest codename on the page. After a crown
the numbers restart: the commit after the one crowned `1.0` is `1.01`.

## One group per day

A group is a single day, and every commit of that day falls in it. The day does
not break at midnight. It breaks at 09:00: a commit before 9am counts as the day
before, so work done at 2am on the 1st belongs to the 30th. Take each commit's
time from `git log --format=%ad` and move it back nine hours to find its day.

On each save, if the new commits share the top group's day, extend that group:
move its version high end up, and add any bullets. If they open a new day, write
a new group above it.

The days are contiguous and they cover everything. Every commit from the first
to the current one falls inside exactly one day, so a gap in the record is
visible rather than plausible. Every day is a group, including a day that did
only work a reader cannot see. That day still carries a codename and a single
plain line that says as much.

## The shape of an entry

One `##` heading per day carries the codename, then two lines of metadata, a
lead line, and the bullets:

    ## House Rules
    version: 0.44 - 0.58
    date: 30 September 2026

    - **The house gets an admin.** One password runs the place.
    - [new] **Feature switches.** The admin can switch off what the house
      does not use.
    - [fix] **The radio carries on from the right song.**

`version:` is the span of commit numbers the day covers (`0.59` alone for a day
of one commit). `date:` is the single day the group's commits fall on, as
`30 September 2026`.

**A lead line opens every group.** One untagged bullet in bold says, in a
sentence, what the day is for. A reader who stops there already knows whether it
matters to them. The bullets under it are the detail.

**Bold the thing each bullet is about.** The feature or the part of the app that
changed goes in `**bold**` at the front, so a reader skimming the bold runs
reads the day as a list of what moved.

**Group a busy day under `###` subheads.** Once a day touches three or four
unrelated areas, a flat list of ten bullets is a wall. Break it into named parts
- `### The admin`, `### On a phone` - each a short run of bullets on one theme.
A quiet day needs none.

## Codenames

Every group carries one, a quiet day included. One to three words, Title Case,
punchy and plain, tied to the headline change - `Take Turns`, `Open House`,
`House Rules`. Never reuse a name. Save the boldest for a crowned milestone.

## The three tags

`[new]`, `[fix]` and `[faster]` lead a bullet, and there are only three on
purpose: a set that grows past what the eye tells apart at a glance is a legend,
and nobody reads a legend on a changelog.

- `[new]` - a feature or a capability that was not there before.
- `[fix]` - a repair to something that was meant to work and did not.
- `[faster]` - a speed-up or a size cut somebody could feel.

A bullet with no tag is prose about the day as a whole: the lead line, or a
housekeeping note. Lead a housekeeping note with its own bold phrase -
**`Maintenance:`** for internal work a reader should see named rather than spun.

## Tone

Written for somebody who uses Tunebox and does not read the code. Say what is
different for them, not what was refactored. Lead with the benefit. Keep
sentences short, concrete and calm. Be honest: a trivial or internal day gets a
plain `Maintenance` line, not spin.

British spelling, to match the rest of the app: colour, equaliser, centre. A
label quoted inside backticks is spelt the way it appears on screen.

## Marks and links

Use `**bold**` for the thing a bullet is about, `_word_` for the one
accent-coloured word, and backticks for a literal string from the interface or a
key to press. A bullet may wrap: an indented line continues the one above it,
folded with a single space.

Separators are ` - `, a spaced hyphen. Bullets do not link out: name a feature
in bold rather than linking it. The only link the page carries is its own way
back to the player.

## Do not

- Do not use an em-dash or an emoji.
- Do not leave a commit out of a day, or let the newest group disagree with
  `VERSION` in version.js.
- Do not hand-edit `web/patch.html`; it is generated. Write here, then run
  `python dev/patch.py`.
- Do not fill the page with work a reader cannot see.

## Releases

## House Rules
version: 0.44 - 0.61
date: 30 September 2026

- **The house gets an admin, and Tunebox reaches past the browser.** One
  password runs the place, your own files play beside YouTube, and a terminal
  can do everything the page does.

### The admin
- [new] **One admin password for the house.** It opens a panel to edit, merge,
  block and remove people, and to clean up plays, likes and playlists. It locks
  again after 15 minutes left alone, and a run of wrong passwords locks it for
  everyone for a while.
- [new] **Every admin change is written down** in a log the admin can read.
- [new] **Playlists have owners.**
- [new] **A forgotten admin password can be reset** on the server itself, with
  `run.py --reset-admin`.
- [new] **A backup made without the admin leaves the pass phrases out.**
  Restoring one, and signing in to YouTube, need the admin.

### The house's setup
- [new] **Feature switches.** The admin can switch off names, groups,
  playlists, likes, Home and Explore, pasted links, the radio, lyrics, Stats,
  the recap, the wall screen, the alarm, the sleep timer, the equaliser, local
  songs, the theme and accent pickers, and the names in Settings. What is off is
  hidden for everyone, and nothing is deleted.
- [new] **Presets** set the switches in one go: `Home`, `Office`, `Party` and
  `Solo`.
- [new] **A House tab** for the house's name, accent and time zone, sign-ups,
  groups with any name and the house's own word for them, and the wall screen's
  options.
- [new] **A blocklist for songs and artists.** A blocked song cannot be added,
  and the radio and the queue drop it.

### Local songs
- [new] **Upload your own audio files** on a Local page, with a button or by
  dropping them, with progress for each file. They play, queue, like and count
  like any other song.
- [new] **Tags and covers are read from the files,** and can be edited.
- [new] **WAV and AIFF are kept as FLAC,** and unusual formats as Opus.
- [new] **Search shows local matches first.** The radio after a local song
  plays YouTube's copy of the same song, or the other local songs.
- [new] **The admin's Local tab** shows the disk use, a cap, the free space to
  keep and the biggest file, and makes a full backup as a zip with the audio in
  it.

### The terminal
- [new] **The `tunebox` command** does what the page does, from a terminal:
  what is playing, adding by words, link or id, the controls, the queue, search,
  playlists, likes, stats, the admin and the rest. `install.sh` puts it on the
  server, and `tunebox.bat` starts it on Windows.
- [new] **`tunebox tui` is the whole player full-screen in a terminal,** with
  tabs for Home, Search, Queue, Playlists, History, Local, Stats, Lyrics,
  Settings and the admin, and Up next beside the player on a wide window.
  `--ascii` and `NO_COLOR` work.
- [fix] **The player line in the terminal no longer jumps back** when a slow
  answer arrives late.

### Playing
- [fix] **The radio carries on from the added song that plays last,** not from
  the newest one added. Play next, Play now and a song taking its turn in the
  middle leave it alone. Removing, moving or blocking the last song moves it
  along.
- [new] **The wall screen dims to its clock after 30 seconds paused,** where it
  waited two minutes.

### Moving and touch
- [new] **Panels slide out the way they came in, and a finger can drag them
  away.** Drawers, pop-ups and the menu sheet follow the finger, and Now playing
  rises from the mini bar and goes back down. A flick counts as much as the
  distance.
- [new] **A removed queue row keeps going and the rest close up,** and a dropped
  row travels to its place. Every button answers a press at once, and the menu
  grows from where you pressed.
- [new] **Reduced motion fades** instead of switching everything off.
- [new] **On a phone, the volume button opens a small volume bar** over the
  player, not Settings.
- [new] **A tap on the big cover shows the lyrics,** and a swipe sideways skips.
- [new] **The name form takes the whole screen on a phone.**
- [faster] **Now playing holds a steady frame rate on a phone.** The blurred
  cover behind it waits until the screen stops moving.
- [fix] **Hover colours no longer stick** to the last button tapped on a touch
  screen.
- [fix] **A pop-up's buttons stay above the keyboard** in Firefox and Safari.

### Who's listening
- [new] **Names are big tiles,** yours first with a ring around it, so most
  houses fit without scrolling.
- [new] **Find your name** in a search box that ignores accents and matches
  groups too, or **filter by group** with a row of chips. When nothing matches,
  one tap adds what you typed as a new name.
- [new] **A padlock on a name** says it has a pass phrase before you tap it.
- [new] **`Listening as` sits at the top with an `Edit` link,** in place of
  `Edit my profile`.
- [new] **A new group is made with `+ New`** in the name form.

### Settings
- [new] **Performance mode** for devices with little power: no movement, blur
  or shadows, and fewer requests to the server. `Auto` turns it on for a slow
  device.
- [new] **A Network section shows the address** other devices open Tunebox at,
  with a `Copy` button, and the Wi-Fi to join. The admin can type the Wi-Fi's
  name, or the server's own is shown.
- [fix] **The address is right with a VPN on.** It is the server's address on
  the same network as the device asking.
- [new] **Names wear drawn icons,** and a pass phrase shows a drawn padlock.
- [new] **Search results offer Play only.** Play next is still in Play's
  question and in the song's menu.

### Stats
- [new] **Fun stats:** skips, songs cut short with Play now, and awards for the
  house - The DJ, On repeat, Itchy finger, Can't wait, Tough crowd, Night owl
  and Explorer. One person's Stats and recap show their own habits instead.
- [new] **On this day,** a row on Home with what the house played on this date
  a year ago, or a month ago.
- [new] **A song's menu says how often the house played it,** since when, and
  whose song it mostly is.
- [new] **Stats download as a spreadsheet:** `Download as CSV` gives every play
  in the period on screen.

### Home and playlists
- [new] **Home opens with songs.** Your own rows come first, then a new
  `Recommended` row from a song played lately, then YouTube's song rows. Mixes
  and albums follow.
- [new] **Top 30,** next to Liked songs: the house's most played songs of the
  last 30 days, with how often each played. It keeps itself up to date.
- [new] **Find and sort inside a playlist** by title or artist, once it has more
  than a few songs.
- [new] **Select several songs** in Up next or a playlist, then play them next,
  add them to a playlist or take them out in one go.
- [new] **Recent searches** show under the empty search box, one tap to search
  again.
- [new] **Not for the radio:** anyone can tell the radio to stop picking a song
  from its menu. It can still be added by hand, and the admin can bring it back.
- [new] **Songs without a cover get a drawn one,** headphones, a record or a
  note, the same one every time.
- [new] **Local sits between Playlists and History** in the menu.
- [fix] **A short last row of tiles** no longer leaves a grey block beside it.

### Up next
- [new] **Every queued song says when it plays,** and the player bar says when
  your next one is up.
- [new] **`Mine` shows only your songs in Up next,** with `Take mine out`.
- [new] **Adding a song that is already waiting asks first.**
- [new] **A queued song shows who added it by name** beside their icon, in place
  of their groups.
- [fix] **The number on the queue button counts only queued songs,** not the
  radio's.
- [new] **A tap on a synced lyric line plays from there** at once, on the wall
  too.
- [new] **Now playing loads the cover at full size.**
- [new] **A bar along the top says when the server can't be reached,** and the
  buttons rest until it is back.

### The wall screen
- [new] **A new background, after Nothing OS 5's:** big soft lights and a
  few soft discs in the cover's colours float slowly about, under hairline
  circles and dashed lines that drift too, and a fine grain. Each song has its own, the same every time it plays, and the shapes glide
  into their new places when the song changes.
- [new] **The cover takes gestures:** tap its left or right half for the
  previous or next song, double-tap to like, drag up or down for the volume.
- [new] **Add songs from the wall:** the magnifying glass at the top right opens
  a big search. Songs added there are the house's, not anyone's, and Stats counts
  them.
- [new] **The lyrics scroll** with a finger or the wheel, and pick up the line
  being sung again a few seconds later.
- [new] **The cover, title and buttons sit in one centred column.**
- [new] **A button shows or hides the lyrics** on that wall, and the full screen
  button steps aside while the wall is full screen.
- [new] **Leaving the wall takes four presses of the X** at the top right, so
  a stray tap doesn't close it.
- [new] **A join code** under the idle clock and in the search: guests scan it
  to open Tunebox on their phone.
- [new] **Night hours,** set by the admin: the wall dims to the clock and the
  song.
- [new] **The picture drifts a few pixels** every two minutes, so a TV left on
  all day does not burn in.
- [new] **Bigger targets for fingers** on a touch screen.

### For the admin
- [new] **Quiet hours:** in the hours set, nobody can turn the volume above the
  limit, and a louder volume comes down to it.
- [new] **Here now,** in the People tab: every device with Tunebox open, and
  the name it picked.
- [new] **A backup every night,** kept for 14 nights on the server.

### The terminal
- [new] **`tunebox now --short`** prints the song for a shell prompt or a status
  bar.
- [new] **`tunebox tray`** puts Tunebox in the Windows notification area, and
  the keyboard's media keys play, pause and skip on the house's speakers.

- **Maintenance:** deploying goes to any server, from a list kept on each
  computer, and `save.sh` does it from macOS and Linux.

## Open House
version: 0.08 - 0.43
date: 29 September 2026

- **Tunebox grows up.** A Now playing screen, groups and pass phrases, Stats
  and a recap, and it runs on any computer, not only the house server.

### Now playing
- [new] **A Now playing screen:** the big cover on a blurred copy of itself,
  with the song, a like, the controls, volume, lyrics and Up next. On a phone it
  opens from the mini bar with a tap or a swipe up. On a desktop, click the song
  in the bar, or press `N`.
- [new] **A mini bar on a phone** with the cover, the title, a like, play and a
  thin progress line. Swipe it sideways to skip.
- [new] **Play and pause fade** over half a second, on every page and the wall
  screen at once.
- [new] **Every Lyrics button shows the lyrics beside the cover** while Now
  playing is open.

### Playing
- [new] **Tunebox asks before interrupting.** While a song is on, a tap on a
  song, an album's Play or a shelf asks: play it now, play it next, or add it to
  the end of the queue. Play next and Add all still act at once.
- [new] **Right-click for a menu** on a song, a card, a page header, the player
  or the queue, or press and hold on a touch screen: play, play next, add to the
  end, add to a playlist, like, go to the artist or the album, copy the link.
- [new] **Artist and album names link to their pages,** and Back walks back
  through them.
- [fix] **A change to the equaliser is heard at once.** It waited for the next
  pause.
- [fix] **A new audio quality applies at once,** not after a restart.
- [fix] **A player crash in the middle of a fade** no longer leaves the volume
  turned down.
- [fix] **Home, Explore and moods say what went wrong** when YouTube fails.
- [new] **One interface.** Classic is gone, and its old addresses open the
  player.

### People and groups
- [new] **Groups.** Everyone belongs to at least one, with three letters and a
  colour, shown beside the name in the queue, the history and People.
- [new] **A name can have a pass phrase.** A device types it once and keeps a
  key; without it the name cannot be used or edited. Add, change or remove it
  from People in Settings.
- [new] **The names list and the name form are apart,** and the form shows a
  live preview of the badge. `Edit my profile` is in the Who's listening menu.
- [new] **Liked songs shows who liked each song,** and filters by person or
  group. So does the Liked mix on Home.
- [fix] **Two quick taps without a name** ask who is listening once, not twice.

### Stats
- [new] **Every play is kept:** the song, who added it, radio or not, and the
  seconds actually heard.
- [new] **A Stats page,** on `T`, for any period, the house, a person or a
  group: minutes, plays, songs, artists, new songs, the best streak, top songs
  and artists, who added the most, the time of day and the day of the week.
- [new] **The recap:** story slides for any period, person or group, opened
  from Stats, ending with Play the top songs.

### Around the app
- [new] **Backup and restore in Settings:** one file with everything the house
  made except the YouTube sign-in. A restore keeps what it replaced.
- [new] **Tunebox can be installed as an app,** with its own icon.
- [new] **Tunebox runs on any computer.** `start.bat` on Windows and `start.sh`
  on Linux fetch what is missing the first time, and `install.sh` sets up a
  Linux server.
- [fix] **The alarm works on Python 3.14 and on Windows.**
- [new] **Text no longer selects on clicks and drags.** Fields still do.
- **Maintenance:** the code was split into parts, and Tunebox moved out of
  homeapps into its own repository.

## Take Turns
version: 0.01 - 0.07
date: 28 September 2026

- **Tunebox learns who is listening.** Names, a queue that takes turns, the
  house's own shelves on Home, and a screen for the wall.

- [new] **Who's listening.** Everyone picks a name once per device, with a
  colour and an icon, and the queue and the history show who added each song.
  Likes stay shared, and remember who liked them.
- [new] **A queue in two parts:** the songs people added, taking turns between
  them, then the radio, which follows the last song added.
- [new] **Play next and Play now on every song,** and Play, Play next and Add
  all on albums, playlists and the history.
- [new] **Undo any change to the queue** from a toast, from the queue, or with
  `Z`, and go back to an earlier queue from a list.
- [new] **On a touch screen,** swipe a queue row left to remove it, right to
  play it next, and drag it by its grip.
- [new] **For you shelves on Home:** Most played in the last 30 days, Liked mix
  and House mix. Explore shows new albums, and moods and genres.
- [new] **Paste a YouTube or YouTube Music link** into search to open its album,
  playlist, artist or song.
- [new] **The wall screen** at `/wall`, for a tablet or a TV: the cover, synced
  lyrics, big controls, and a dimmed clock when nothing plays.
- [new] **A Settings button in Up next.**
- [fix] **Up next keeps a tap that lands while it updates,** and the radio stays
  after Clear, with a `Start radio` button.
- [fix] **A page that finishes loading after you moved on** no longer takes
  over.
- [fix] **A cover that fails to load** shows an empty tile, not a broken image.
