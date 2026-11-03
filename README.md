```
████████╗███████╗██╗     ███████╗ ██████╗ ██████╗  █████╗ ███╗   ███╗
╚══██╔══╝██╔════╝██║     ██╔════╝██╔════╝ ██╔══██╗██╔══██╗████╗ ████║
   ██║   █████╗  ██║     █████╗  ██║  ███╗██████╔╝███████║██╔████╔██║
   ██║   ██╔══╝  ██║     ██╔══╝  ██║   ██║██╔══██╗██╔══██║██║╚██╔╝██║
   ██║   ███████╗███████╗███████╗╚██████╔╝██║  ██║██║  ██║██║ ╚═╝ ██║
   ╚═╝   ╚══════╝╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
██████╗  ██████╗ ██╗    ██╗███╗   ██╗██╗      ██████╗  █████╗ ██████╗ ███████╗██████╗ 
██╔══██╗██╔═══██╗██║    ██║████╗  ██║██║     ██╔═══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗
██║  ██║██║   ██║██║ █╗ ██║██╔██╗ ██║██║     ██║   ██║███████║██║  ██║█████╗  ██████╔╝
██║  ██║██║   ██║██║███╗██║██║╚██╗██║██║     ██║   ██║██╔══██║██║  ██║██╔══╝  ██╔══██╗
██████╔╝╚██████╔╝╚███╔███╔╝██║ ╚████║███████╗╚██████╔╝██║  ██║██████╔╝███████╗██║  ██║
╚═════╝  ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝
```

a python app that downloads data from telegram

## create a python virtual environment (venv)
Requires Python 3.11 or newer (check with `py --version` on Windows,
`python3 --version` on Linux).

Windows shortcut: from the project folder in PowerShell, this does steps 1
and 3 below in one go (the leading dot keeps the venv active afterwards):
```
. .\setup.ps1
```

1. create and activate the venv from the project folder

   Windows (PowerShell):
```
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```
   If activation fails with "running scripts is disabled on this system",
   run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then
   activate again. If `py` isn't found, install Python first
   (`winget install Python.Python.3.13`, then reopen PowerShell).

   Linux / WSL:
```
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```
   In every new terminal, re-run just the activate line before using the app.
2. if requirements.txt exists this is optional -- only needed if you change
   a dependency in pyproject.toml:
run
```
pip install uv
uv pip compile --universal --generate-hashes -o requirements.txt pyproject.toml
uv pip compile --universal --extra dev --generate-hashes -c requirements.txt -o requirements-dev.txt pyproject.toml
```
   `--universal` matters here: this project installs on both Linux and
   Windows, and plain `pip-compile` only resolves platform-specific
   dependencies (e.g. keyring's Windows backend, pywin32-ctypes) for
   whatever OS you run it on, silently dropping the others -- which then
   breaks `pip install --require-hashes` on any other platform. `uv pip
   compile --universal` resolves and hashes every platform's dependencies
   into the one file, each correctly marked with its `sys_platform`
   condition.
3. run
```
pip install --require-hashes -r requirements.txt -r requirements-dev.txt
```
4. run once per clone to activate the pre-commit hooks (see "Secret
   scanning" below):
```
pre-commit install
```


## Secret scanning

GitHub's own secret scanning only catches a secret once it has been
pushed. As an earlier line of defense, `pre-commit` runs two checks
locally before every commit (after `pre-commit install`, see above):

- [`detect-secrets`](https://github.com/Yelp/detect-secrets) -- catches
  known secret shapes (AWS/GitHub/JWT/Artifactory tokens, high-entropy
  strings in an assignment, etc.), tracked against `.secrets.baseline`.
- `scripts/check_url_credentials.py` -- a small companion check for
  credentials embedded in a URL (`<scheme>://<user>:<password>@<host>`),
  including when the "user" portion itself contains an "@" (e.g. an
  email address). detect-secrets' own URL-credential detector misses that
  exact shape (e.g. a private package-index URL with a token in
  `requirements.txt`), so this exists as a dedicated backstop for it
  rather than trusting one heuristic to catch everything.

A false positive can be silenced with a trailing `# pragma: allowlist
secret` comment on that line (both checks honor it), or by re-running
`detect-secrets scan --baseline .secrets.baseline` to update the baseline
after reviewing what changed.


## the the api-id and -hash and the chat id

1. get the api-id and api-hash from https://my.telegram.org/auth
    - the names don't matter put something that it accepts, set the category it to "desktop" (does not matter) and don't put anything in URL 

2. create a .env file if not exist from .env_example in the same folder
3. paste the api-id and api-hash in the .env file
4. get the chat id from the URL of the chat. For example for https://web.telegram.org/a/#1234567890 the chat id is 1234567890

## run the python script
1. use the chat id number established earler
```python
python telegram_export.py --chat "1234567890" --html
```
2. the output files are in html and json and carry the name of the chat id. I the chat id contains a leading "-", it is ommited.

## GUI

A PySide6 GUI is also available as an alternative to the command-line
script above: enter your credentials once, then search your chats and
download several of them at a time.

Framework choice: PySide6 over tkinter, because the chat selection screen
needs a proper filterable table with checkboxes, which is a lot more work
to build well in tkinter. PySide6 is LGPL-licensed, so depending on it is
fine.

### Running it

1. Set up the venv and install dependencies as above -- PySide6 is already
   in requirements.txt.
2. Run:
```
python -m gui.app
```

### Credentials screen

- Enter api_id, api_hash and your phone number. The fields are validated
  before saving (api_id numeric, api_hash a 32-character hex string), with
  the error shown inline rather than failing later at connect time.
- The "Open my.telegram.org" button opens the page where you get api_id
  and api_hash (same steps as the "the the api-id and -hash and the chat
  id" section above); the URL in the help text is also a clickable link.
- "Login" logs in for real -- it asks for the login code Telegram sends
  you, and your 2FA password if you have one set. Credentials are only
  saved and the app only moves on to chat selection once that login
  actually succeeds, so a typo can never leave you on chat selection with
  nothing behind it -- you'll see the error right there on this screen
  instead.
- Credentials go into your OS keyring if one is available. If not (for
  example a headless Linux machine with no secret service running), they
  fall back to an unencrypted file at
  `~/.config/telegram_downloader/credentials.json` -- outside this repo,
  so it can never be committed by accident, but readable by anyone with
  access to your account.

### Chat selection screen

- The dialog list loads automatically once you log in (or immediately on
  startup, if you're already logged in from an earlier run).
- Type in the search box to filter live by chat name, chat ID, or a loaded
  chat's member names (see "Load members" below). "Hide chats with no
  name", next to the search box, additionally drops chats with a blank
  display name.
- Click a column header to sort by it (click again to reverse); every
  column can also be resized by dragging its border. ID and Participants
  sort numerically, not as text.
- Click "Load members" on a chat's row to fetch its member list. This is
  not done automatically for every chat -- it's slow and rate-limited --
  but once loaded, the search box also matches against that chat's member
  names.
- The checkbox above the Select column selects/deselects every currently
  visible (filtered) chat at once.
- Check the boxes for the chats you want, set an output directory / HTML /
  message limit if needed, and click "Download selected". Downloading more
  than one chat asks for confirmation first, naming the count and the
  current message limit. Each row's Status column updates as its download
  finishes or fails; one chat failing doesn't stop the rest.
- "Log out" revokes the Telegram session and clears your saved credentials,
  returning you to a blank credentials screen.

See `manual_test_gui.md` for a step-by-step checklist to exercise these
screens by hand -- a GUI event loop isn't practical to unit test, so the
automated tests only cover the pure logic underneath it (`credentials.py`,
`chat_filter.py`).