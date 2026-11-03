# Manual test checklist: GUI

The credentials and chat-filtering *logic* is covered by automated tests
in `tests/`. A GUI event loop isn't practical to unit test, so the screens
themselves need a human (or a UI-automation tool) to exercise. Run through
this checklist after any change under `gui/`.

Needs: a real Telegram account, its api_id/api_hash, and a machine with a
display (this doesn't work over a headless SSH session unless you forward
X11 or a similar remote-desktop setup).

Before starting, if you want a clean-slate run: delete any saved
credentials (`~/.config/telegram_downloader/credentials.json`, or your OS
keyring entry for the "telegram_downloader" service) and delete or rename
any existing `telegram_export.session` file.

Checkboxes below are left unchecked -- this is a reusable checklist, run
again after any future change under `gui/`, not a one-time record. For
what it's worth: this checklist was run in full against a real Telegram
account on Windows during initial development (through 2026-09-04), which
surfaced and fixed several real bugs along the way -- multi-chat downloads
only updating the first row's status, group exports being named by numeric
ID instead of title, the chat table scrolling back to the top after
loading a chat's members, credentials that passed format validation but
were actually wrong leaving no way back to fix them, and the pre-commit
secret-scanning hook itself crashing on Windows. All of those have
regression tests where the fix was in pure logic (`tests/`), or are
covered by an explicit item below where it was GUI-only.

## Launching

- [ ] `python -m gui.app` opens a window titled "Telegram Downloader"
      without errors printed to the console.
- [ ] On a machine with no saved credentials, it opens directly on the
      credentials screen.

## Credentials screen -- validation

- [ ] Leave all fields empty and click "Login" -- an inline error appears,
      nothing crashes, and you stay on this screen.
- [ ] Enter a non-numeric api_id (e.g. "abc123") -- inline error mentions
      api_id.
- [ ] Enter an api_hash that isn't 32 hex characters (e.g. too short, or
      containing letters past `f`) -- inline error mentions api_hash.
- [ ] Enter an implausible phone number (e.g. "123") -- inline error
      mentions the phone number.
- [ ] Fix all three fields with valid-looking values and confirm the error
      message disappears once you click Login again.
- [ ] Enter values that pass format validation but are actually wrong
      (e.g. a made-up 32-char-hex api_hash) and click Login -- it fails
      with an error on this screen, nothing gets saved, and you do NOT
      end up on chat selection (this used to be possible via a separate
      Save button and was a dead end; Login combines save+connect so
      that's no longer reachable at all).

## Credentials screen -- help and links

- [ ] Click "Open my.telegram.org" -- your default browser opens
      https://my.telegram.org/apps in a new tab.
- [ ] The numbered help text (log in, "API development tools", create an
      app, copy api_id/api_hash) is visible on screen, not just in the
      README.
- [ ] The "https://my.telegram.org" text inside step 1 of the help text is
      itself a clickable link that also opens the site in your browser.
- [ ] The api_hash field is masked (dots/asterisks) by default; toggling
      "Show" reveals the plaintext value and toggling it back re-masks it.

## Credentials screen -- login (first-time)

- [ ] With valid real credentials and no existing session file, click
      "Login". A dialog asks for the Telegram login code.
- [ ] Enter the code Telegram actually sent you -- if your account has 2FA
      enabled, a second dialog asks for your password.
- [ ] On success, credentials are saved and the app moves straight to the
      chat selection screen (no separate Save step).
- [ ] Cancelling the code or password dialog shows a failure message
      instead of crashing the app, and you stay on the credentials screen
      with nothing saved.
- [ ] Entering a deliberately wrong code shows a failure message (not a
      crash), nothing is saved, and you can retry Login again afterward.

## Credentials screen -- persistence

- [ ] Quit and relaunch the app after a successful login -- it goes
      straight to chat selection without asking for credentials again
      (they were loaded from storage).
- [ ] Relaunch again after deleting the saved credentials file/keyring
      entry -- it asks for credentials again from a blank form.

## Chat selection screen -- loading

- [ ] After saving credentials (with an already-authorized session from
      the test-connection step above), the chat table populates with your
      real dialogs within a few seconds, without freezing the window.
- [ ] Each row shows a plausible chat name, a numeric ID, a type
      (user/group/channel) matching what that chat actually is, and a
      participant count for groups/channels where Telegram provides one
      (blank is fine for chats it doesn't).

## Chat selection screen -- search

- [ ] Typing part of a chat's name filters the table live, on every
      keystroke, with no visible lag.
- [ ] Typing part of a chat's numeric ID filters to just that chat.
- [ ] Clearing the search box restores the full list.
- [ ] Checking a box, then typing a search query that hides that row, then
      clearing the search -- the checkbox is still checked (selection
      survives filtering).
- [ ] The select-all checkbox sits directly above the per-row checkboxes,
      at the top-left of the table (over the blank "Select" column
      header), not floating somewhere else on the screen.
- [ ] Check it -- every currently visible (filtered) row gets checked.
      Uncheck it -- they're all cleared. Filter down to a subset first and
      confirm it only affects the visible rows, not chats hidden by the
      current search.
- [ ] Resize the Select column (drag its right edge) -- the select-all
      checkbox moves and resizes to stay aligned above it.
- [ ] Check "Hide chats with no name" (next to the search box) -- any
      chats with a blank display name disappear from the table. Uncheck it
      -- they come back. Combine it with a search query -- both filters
      apply together (a chat needs a non-empty name AND match the query).

## Chat selection screen -- columns

- [ ] Drag a column border to resize it -- every column (including Select,
      ID, Type, Participants, Members, Status) can be resized, not just
      Name.
- [ ] Click a column header to sort by it; click again to reverse the
      order. Sort by Name (or ID) and confirm each row's data stays
      correct together -- no chat's name ends up paired with a different
      chat's ID/type/participant count after sorting.
- [ ] Sort by ID or Participants -- the order is numeric (1, 2, 10), not
      alphabetical-string order (1, 10, 2).

## Chat selection screen -- load members

- [ ] "Load members" looks like a link (blue, underlined) with visible
      padding around it, and the column is wide enough that its text isn't
      clipped.
- [ ] Click it on a group/channel you're in -- it shows a loading state,
      then changes to "Loaded (N)" in green and stops being clickable.
- [ ] Sort the table by another column after loading a chat's members, then
      confirm that chat's "Loaded (N)" status is still attached to the
      right row.
- [ ] Search for a member's first name or username who is only findable
      this way (not in any chat's title) -- after loading that chat's
      members, the chat now appears in search results for that name; before
      loading, it did not.
- [ ] Loading members on a large group doesn't freeze the rest of the UI --
      you can still type in the search box while it's loading.
- [ ] Scroll partway down a long chat list, then click "Load members" on a
      row that's currently visible -- the table stays scrolled to roughly
      the same place afterward instead of jumping back to the top.

## Chat selection screen -- download

- [ ] Select exactly one small chat and click "Download selected" -- no
      confirmation dialog appears (single-chat downloads don't prompt),
      and the row's Status column changes to "Downloading..." then "Done".
- [ ] Check the resulting `export/<name-or-id>.json` file exists and looks
      right.
- [ ] Download a basic (non-super) group -- the file is named after the
      group's title, not its bare numeric ID (basic groups never have a
      username in Telegram's data model, so this used to always fall back
      to the ID). Try a group whose title has spaces/punctuation and
      confirm the file name is still valid (no `: " / \ | ? *`).
- [ ] Select two or more chats and click "Download selected" -- a
      confirmation dialog appears naming the number of chats and the
      currently-set message limit (e.g. "Download 3 chats (up to 50
      messages per chat)?" or "... (all messages per chat)?" if the limit
      is unset). Clicking No/Cancel does not start any download. Clicking
      Yes proceeds as normal.
- [ ] Check "Also write HTML" before downloading -- an `.html` file is also
      produced.
- [ ] Set a small message limit (e.g. 5) -- the downloaded JSON has at most
      5 messages.
- [ ] Use "Browse..." to pick a different output directory -- the files
      land there instead of "export".
- [ ] Select two chats where one of them is invalid or inaccessible (e.g.
      a chat you've since left) -- the valid one still downloads
      successfully and shows "Done" while the other shows a "Failed: ..."
      status; one failure doesn't block the rest of the batch.
- [ ] Select three or more chats and download them together -- **each
      row's Status column updates independently** as its own download
      finishes (not just the first one; the others aren't left blank or
      stuck on "Downloading..." forever). This was broken once already
      (multi-chat downloads reconnected to the session file per chat,
      which could stall past the first) -- pay close attention here.
- [ ] Click "Download selected" with nothing checked -- a message tells you
      to select at least one chat, instead of silently doing nothing.
- [ ] After a download finishes, searching and loading members on other
      chats still works without any extra delay (downloads now reuse the
      same browsing connection instead of reconnecting).

## Chat selection screen -- log out

- [ ] Click "Log out" -- the app returns to the credentials screen with a
      blank form.
- [ ] Relaunch the app -- it asks for credentials again rather than
      skipping to chat selection (both the stored credentials and the
      local Telegram session were cleared).
- [ ] Enter fresh, correct credentials (or the same ones again) and
      confirm you can log back in and reach chat selection normally.
- [ ] Separately, this is also how to exercise the credentials screen's
      wrong-credentials paths noted above -- log out first to get back to
      a blank form, then try an invalid api_id/api_hash/phone or a
      deliberately wrong login code.
- [ ] If a previously-successful login's session ever gets invalidated
      externally (e.g. you revoke it from Telegram's own "Active
      Sessions" list, or log out from another device) and you relaunch
      the app, it goes straight to chat selection using the old saved
      credentials (Login itself can no longer save invalid ones, but a
      once-valid session can still go stale later) and you land on chat
      selection with a "Failed to load chats" message and an empty table
      -- **Log out is still clickable** in that state (this used to be a
      dead end otherwise). Use it to get back to a blank form and log in
      again.

## General

- [ ] Resize the window -- the table and buttons lay out sensibly, nothing
      is clipped.
- [ ] No unhandled exceptions/tracebacks appear in the terminal during any
      of the above.
