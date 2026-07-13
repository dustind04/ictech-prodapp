# ictech-prodapp

Production A/V support tooling for **Immanuel Church** (Gurnee, IL — immanuelhome.org, "Welcome home.") under the **icTech Services** sub-brand.

## What this is

A Flask/SQLite web app whose primary surface is a **backstage wall display** — a TV mounted above the wireless mic rack. It serves **two audiences on one screen**:

1. Singers walking up to grab their mic pack
2. The backstage manager monitoring during a service

**This is one screen, not two views.** Do not split it into separate singer/manager modes. This has been a recurring correction.

An admin UI (light mode) manages the data behind it. The wall display is dark mode.

## Repo

- `github.com/dustind04/ictech-prodapp`
- Forked from **micboard** (karlcswanson). The `py/` directory is retained as a **reference for the Shure wireless protocol only** — the frontend is fully replaced.
- Branch: `master`

### Commit history (5 commits, all landed)

| # | SHA | What |
|---|-----|------|
| 1 | `38a5a14` | Flask skeleton + 3-table schema |
| 2 | `6b40336` | Admin CRUD + branded wall display |
| 3 | `97b3064` | Photo upload for people |
| 4 | `70c5825` | Stage positions + mic label fix |
| 5 | `6bf4ba6` | MyMix channel on slot |

Work was explicitly stopped at commit 5.

## Data model

Four tables: `person`, `channel`, `slot`, `position` (plus `app_setting`, gear catalogs).

Slots: 1–6 paired (vocal handheld + IEM), 7–10 mic_only (wireless
speakers), 11–16 band (instrument seats; IEM/mic optional — mic only
when they lead/sing). Wall zones: Vocals left, Band middle, Speakers
right. A person on both a vocal and a speaker slot renders once, with
the vocalists, with a "+ Speaker" callout.

`slot` is the join point — it links to:
- `person`
- mic `channel`
- IEM `channel`
- `position`
- `mymix_channel` (a plain field **on the slot**)

**MyMix channel is per-slot, not per-channel.** It varies week to week based on FOH routing. Do not normalize it onto `channel`.

## Wall display tile layout

Bottom → top within each tile:

1. IEM label (Immanuel green; only on paired slots)
2. MyMix channel (subtle gray)
3. Mic label
4. Position pill (green, outlined)
5. Person name (dominant element)
6. Photo circle (green background, initials as fallback)
7. Slot number

## Brand

Confirmed against immanuelhome.org. `icTech` renders as "ic" in Immanuel green + "Tech" in charcoal, matching the icKids/icYouth/icSports pattern.

| Token | Hex |
|-------|-----|
| Immanuel green | `#7AB648` |
| Charcoal | `#1F1F1F` |
| Off-white | `#F7F7F5` |
| Gray | `#6B6B6B` |
| Gray border | `#E2E2E0` |

Font: **Inter**. Admin = light mode. Wall display = dark mode.

## Environments

**Dev:** Windows 11 (no WSL/Docker/Python on the current machine — the old `D2Surface` WSL2 environment is gone). Work happens against the git clone at `C:\ICT\ictech-prodapp`; deploys go to Linux boxes via `git pull`. Git identity `dustind04`.

**Internet-facing deployment:** Debian box running `docker-compose.prod.yaml` — app + `cloudflared` sidecar publishing it via a Cloudflare tunnel. Port 8058 is localhost-only on the box; the tunnel is the sole public path. `/admin` gets HTTP Basic Auth via `ICTECH_ADMIN_USER`/`ICTECH_ADMIN_PASSWORD` (auth is off when unset). See `DEPLOY.md`.

**Backstage target:** Raspberry Pi 5 — hostname `micboard`, user `audio`, ARM64, Pi OS Bookworm, Docker installed. Lives on the production VLAN, runs the display in kiosk mode, uses the plain `docker-compose.yaml` (LAN-exposed, no auth).

## Dead ends — do not revisit

- **micboard via Docker:** the published image is x86-only → `exec format error` on ARM.
- **micboard from source:** Python 2 dependencies; node-sass / webpack 4 incompatibilities.
- **Pre-built micboard assets:** none exist in the repo.

These paths are exhausted. The Flask rewrite is the correct direction.

## Stakeholders

- **Dave Hunsberger** — Tech Director, system owner. Produces three files each week: a Stage Layout PDF, an Input List `.xlsx` (FOH patch w/ MyMix channel assignments), and a Backstage Mic Board `.xlsx` (singer-facing rack info).
- **Pete** — FOH / sound engineer.

## Working style

- Terse and goal-oriented. Minimize back-and-forth.
- Hold the whole picture before building. Don't over-narrow scope, don't build before understanding, don't fire off sequential clarifying questions when the context is already available.
- Stopping points are explicit and they're meant literally.
