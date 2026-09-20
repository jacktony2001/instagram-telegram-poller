# Instagram → Telegram downloader bot

Checks the accounts listed in `config.yaml` and uploads every new post or story straight to your
Telegram bot as real files. Runs on the free GitHub Actions schedule — no server.

> **Status: archived.** The code and every verified finding are here, but it does not run right now.
> The one remaining blocker is Instagram's `checkpoint_required` on the reader account's session (see
> "The Instagram checkpoint" below), and no technical trick opens it. To bring it back: clear the
> challenge in a browser → rebuild `IG_SESSION_B64` → enable the workflow.

## Warnings

- **Unofficial access.** The bot talks to Instagram through the private API the official mobile app
  uses (`i.instagram.com`, with the app's `X-IG-App-ID` and user agent). That is not a public,
  permitted interface. It breaches Instagram's Terms of Service and can get the reader account
  rate-limited, checkpointed, disabled or banned. You carry that risk, not this repo.
- **A session is a password.** `IG_SESSION_B64`, `cookies.txt` and `instagram.session` are live logins
  — whoever holds one *is* that account, with no second factor to stop them. Never paste them into an
  issue, a log, a chat or a commit. If one leaks, log out everywhere in Instagram, change the password,
  and build a new session. Revoke a leaked Telegram token in BotFather the same way.
- **Poll the minimum, not more.** Runs are the pressure on the account: keep the schedule at 2 hours or
  slower, keep `MAX_NEW_PER_RUN` small, and never fire several `workflow_dispatch` runs back to back to
  watch something happen — that alone has burned two sessions here.
- **Delete the secrets when you stop.** This repo is public. Even though nothing secret is committed,
  the four Actions secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `IG_USER`, `IG_SESSION_B64`) still
  sit in it while it is archived. Remove them under Settings → Secrets and variables → Actions, and
  delete the ignored local files (`cookies.txt`, `instagram.session`, `.token.tmp`) once you are done.
- **Only your own or authorized content.** Private targets require the reader account to follow them,
  and that is the only permission check here. Downloading and redistributing other people's media can
  be a copyright problem independently of Instagram's rules — settle that yourself.
- **The measurements are dated.** Everything in "Which routes actually work" was measured from a GitHub
  runner in September 2026. Instagram changes endpoints and thresholds without notice, so those tables
  are history, not a promise about today.
- **No warranty.** Provided as a record of what was tried and what answered. Use it at your own risk.

## Files

- `bot.py` — the core: fetch new posts and stories, download them, upload to Telegram.
- `config.yaml` — which accounts to follow.
- `session_from_cookies.py` — run once on your own computer to build a session from browser cookies.
- `make_session.py` — alternative that logs in with a password.
- `state.json` — ids of already-delivered items. The bot writes it and commits it back each run so
  nothing is sent twice.

## Setup

Two things are needed.

1. Create a bot in BotFather and take its token, then send the bot a message so you can read your own
   `chat_id` (for example from `@userinfobot`). Store both as `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_CHAT_ID` under Settings → Secrets and variables → Actions.

2. Build an Instagram session once, locally. Password logins are usually refused with a manual check,
   so use browser cookies instead:

- Log in to `instagram.com` in the browser with the account the bot should read as.
- `F12` → `Application` tab → `Cookies` → `https://www.instagram.com`.
- Take the `sessionid`, `ds_user_id` and `csrftoken` rows with their values and put them in a
  `cookies.txt` file in this folder, one per line: `sessionid=value`.
- Run:

```bash
.venv/Scripts/python session_from_cookies.py your_instagram_username   # Windows
python3 session_from_cookies.py your_instagram_username                # Linux and macOS
```

If the session is alive it confirms the account name and prints a base64 string; store that as
`IG_SESSION_B64`. `cookies.txt` and `instagram.session` never reach GitHub — they are in `.gitignore`.

`make_session.py` logs in with a password instead. Only reach for it if you have to, because
Instagram frequently sends that path to a checkpoint.

If the project has no virtualenv yet:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

3. List the target accounts in `config.yaml` and push. Run the workflow once from the Actions tab;
  after that it runs on the schedule (every 2 hours).

## Which routes actually work

GitHub Actions runners have datacenter IPs, and Instagram answers those with `429`. Temporary probes
run **on the runner itself** (the probe files were deleted once they had answered) mapped exactly
which doors are open and which are not:

| endpoint | result from the runner |
|---|---|
| `www.instagram.com/api/v1/users/web_profile_info/` (the path instaloader uses) | `429` — with HTTP/1.1, HTTP/2 and with curl_cffi's faked Chrome TLS |
| `i.instagram.com/api/v1/feed/timeline/` (the reader's own feed, private API) | `200` with real items and working pagination; `400 checkpoint_required` once the session is challenged |
| `i.instagram.com/api/v1/feed/reels_media/` (stories) | `200` with a live reel; also `400` when challenged |
| `i.instagram.com/api/v1/feed/user/<pk>/` and `users/<pk>/info/` | `404`/`fail` — a web cookie does not open them |
| `www.instagram.com/<username>/` as HTML, and `?__a=1&__d=dis` | `200` but no post data at all: only the shell; cookie-less it is `429` |
| direct image and video URLs on the CDN | `200` with no cookie |

The identity probes (2026-09-20) settled two things: with the **web** `X-IG-App-ID` the error reads
`checkpoint_required`, and with the **app** one (`567067343352427` plus Instagram's own user agent) it
reads `challenge_required` — two words for the same lock, so the headers are not the problem, the
session is. `curl_cffi` with a Chrome TLS fingerprint did not open it either. The bot therefore sends
the same app identity the real app sends, builds `rank_token` as `"<user id>_<uuid>"`, and drops the
irrelevant web headers (`X-IG-WWW-Claim`, `X-Requested-With`).

So the bot reads through `api` first: take the feed, keep the items belonging to the accounts in
`config.yaml`, and pull their files directly from the CDN; for stories it calls `reels_media` with the
same `pk`. That is three or four requests per run instead of hundreds.

If Instagram returns `429` or drops the connection, the same request is retried up to three times with
doubling waits (20 s then 40 s, never less than their own `Retry-After`). A challenge error is never
retried, because retrying makes the account worse.

- `api` — the default and the only method that ever answered from GitHub's servers. Posts and stories.
  Requires the reader account to follow the target accounts, because only those appear in its feed.
- `profile` — the old instaloader fallback. Blocked with `429` from this IP.
- `feed` — instaloader reading the feed. Returns an empty GraphQL payload; useless for now.
- `auto` — try `api`, fall back to `profile`.

## What arrives in Telegram

- One post is one message, not several. Carousels go as a single album via `sendMediaGroup` with the
  caption on the first slide; Telegram caps an album at 10 files, so longer carousels split into
  follow-up albums. Stories arrive separately, since each one is its own event.
- The Instagram feed is ranked, not chronological, so the bot reads the whole feed first, sorts the
  target accounts' items by `taken_at`, keeps the newest `MAX_NEW_PER_RUN`, and then sends them oldest
  first so the chat stays readable.
- Anything older than `max_post_age_hours` in `config.yaml` (default 24) is never sent, so a page's
  old history does not flood in on the first run.
- A story stays alive for a day and the bot sees that whole day in `reels_media` every run, so stories
  have their own limits: only newer than `max_story_age_hours` (default 4) and at most
  `max_stories_per_run` (default 6) per account per run. Without that, a busy account like `wwe` would
  send dozens of 20-hour-old stories instead of new posts.
- If Instagram answers with a non-200 code, its body goes into the log and into the Telegram message.
  Without it you cannot tell a rate limit from a dead session.

ProxyScrape rotation is still in the code (`proxies: true`) but did not help in a real test: of 8
addresses, six refused or timed out and the two that connected got the same `429`. The reason is that
Instagram identifies you by the session cookie, not just the IP, so free proxies fix nothing. The
default is now `false`.

So that no run wastes the job's 15 minutes for no reason, two deadlines live in the code: each route
(direct, or one proxy) has at most `ROUTE_BUDGET` seconds (default 150) and the whole run
`RUN_BUDGET` seconds (default 600, overridable from a variable). After that it moves to the next
route, and if every route is dead it turns the workflow off.

When all routes fail, the bot disables its own schedule through the GitHub API and says so in
Telegram, so that repeated runs stop adding risk to the account. To bring it back, press Enable
workflow in the Actions tab. The same happens when Instagram challenges the session, but proxies are
useless there: repeat step 2 and replace `IG_SESSION_B64`.

## What did not work: a source with no account

Before binding the bot to a reader account's cookie, every account-free option was measured — from two
different IPs (a GitHub datacenter range and a v2ray exit). Same verdict both times:

| route | result |
|---|---|
| public mirrors (`imginn` api/v3, `picuki`, `picnob`, `pixwox`, `imgsed`, `pixnoy`, `storiesig`) | `403` with `server=cloudflare` and a `Just a moment` page — with both `requests` and `curl_cffi impersonate="chrome"`. Two of them have no DNS at all |
| public RSS-Bridge instance (`bridge=Imgsed&context=Username&u=wwe&format=RSS`) | `500` — the bridge itself connects to those same Cloudflare-blocked mirrors, so self-hosting it buys nothing |
| profile and post HTML, `?__a=1&__d=dis`, `web/search/topsearch` | either an empty shell, `429`, or a `302` to the login page |
| `robots.txt` and `sitemap.xml` (including `instagram.com/wwe/sitemap.xml`) | Instagram publishes no crawlable sitemap; you get the same shell back |
| the one cookie-less door that does open: `www.instagram.com/api/v1/oembed/?url=.../p/<code>/` | `200 application/json` with the full caption in `title`, plus `media_id` and a `thumbnail_url` on `scontent-*.cdninstagram.com` — from both IPs. But it is **the cover only**: no carousel slides, no video file, and above all there is no cookie-free way to learn which shortcode is new, so it can never be the primary source |

Conclusion: Instagram's protection follows the endpoint and the cookie, not just the IP. The one thing
oEmbed leaves us is a fallback: when an item's CDN link has expired, the same `code` still yields a
fresh, cookie-free one.

There is also a half-paid option: hosted services such as `socialcrawl.dev` read through their own
account and proxy pools and hand you an API (`profile/posts` costs 1 credit, `stories` 5, with 100
one-time free credits and no card). For two accounts polled three times a day that is roughly 6
credits/day for posts only, or 36 with stories. None of that fits a permanently-zero budget, and
whether they answer from GitHub's IP was never measured.

## The Instagram checkpoint (why this is archived)

The `api` method genuinely worked: 10 items in ~40 seconds, no 429, no proxies. After several
scheduled runs back to back, `feed/timeline` returned `400` with the body
`{"message":"checkpoint_required","checkpoint_url":".../challenge/...","lock":true}`.

- This is the same checkpoint you get when logging in with a password — but this time on a healthy,
  still-valid cookie.
- None of these opened it: switching `X-IG-App-ID` between the web and app identity, Android app
  headers, a correct `rank_token`, Chrome TLS fingerprinting via `curl_cffi`, eight free proxies, or
  dropping the cookie entirely.
- The only fix is a human completing `instagram.com/challenge/` in a browser or on a phone, then
  building a fresh `IG_SESSION_B64`. That is why `bot.py` turns the workflow off itself in this case
  and sends the challenge link to Telegram, instead of raising the account's risk every two hours.
- Worth keeping as a habit: never fire several `workflow_dispatch` runs in a row to test. That is what
  burned through the cookie's allowance twice.

## Notes

- If a target account is private, the account you log in as must follow it or nothing arrives. The
  same applies to public accounts on the `feed` method.
- If the session dies after a while, the bot reports a login error in the log; just repeat step 2 and
  replace `IG_SESSION_B64`.
- The first run delivers only 10 new items so Telegram does not get spammed; the rest wait for the next
  run (the bot remembers it is behind). Change it with the `MAX_NEW_PER_RUN` variable in Actions.
- The real risk is that one Instagram account getting limited, since the bot calls with its session
  every 2 hours. A proxy hides the server IP but not the cookie, so if the account is ever warned, set
  `proxies: false` and widen the gap (make the cron `0 */6 * * *`).
- Write access to the repo is required, because `state.json` is committed back. The `actions: write`
  permission is needed for the automatic workflow shutdown and is already set in the workflow file.
- The laptop plays no part in a run. Only `session_from_cookies.py` or `make_session.py` execute
  locally, and only to produce the session string; all monitoring happens in Actions.
- `IG_SESSION_B64` is effectively a logged-in key to your Instagram account: anyone holding it holds a
  stolen cookie. Never paste it into an issue, a log, or a chat. If it leaks, log out from all devices
  in the browser and build a new session. Same rule for the Telegram bot token — revoke it in BotFather
  (`Revoke current token`) and update `TELEGRAM_BOT_TOKEN`.
