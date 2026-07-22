# TechBooth — brand guide

**TechBooth** is the productized form of this codebase: the operating
system for a church's production world — the booth **and the stage**.
A D2 Audio product, alongside **LiveNotes**, **GigMix**, and **FedUp**.

**Planning Center runs the service. TechBooth runs the booth — and
the stage.**

> Name due diligence (July 2026): "TechBooth" has no software product
> collision — only a Kenyan tech-news site (techbooth.africa) in an
> unrelated category. In our space, CallBoard, VirtualCallboard,
> StageCall, and SideStage are all taken; earlier candidate "MicMap"
> was clean but too narrow. Register techbooth.d2audio.io + trademark
> before public launch.

## The house style (family consistency)

The visual system is D2's, lifted from the live FedUp site
(fedup.d2audio.io) — every D2 product wears it:

| Token | Value | Use |
|---|---|---|
| `--ink` | `#10100e` | THE ground — warm near-black; dark-first |
| `--paper` | `#f3f0e8` | warm bone — inverted sections, print |
| `--acid` | `#d8ff35` | THE accent — spent in one place at a time |
| `--muted` | `#8d8b83` | secondary text (warm gray, never pure) |
| `--line` | `#ffffff24` | hairlines — white at 14% alpha |
| on-air red | `#ff4438` | tally states only, never decorative |

Type: **Geist** (display + body) and **Geist Mono** (eyebrows, specs,
data). Mono ALL-CAPS eyebrows with wide tracking mark sections
("THE BUILD STANDARD" style). Numbered 01 / 02 / 03 only for real
sequences. Stat rows in the FedUp pattern: big value, mono caption.

## The one-liner + triad

**TechBooth — church production OS.**

The hero triad (FedUp pattern — "More vocal. Less room. No howl."):

> **Who's on. What they're on. Where they stand.**

Longer: *Everything the booth and the band need to run a service —
mics, ears, patch, personal mixers, gear, crew, stage positions —
live on every screen in the building, fed by the files your team
already makes.*

## Audience — two rooms, one product

1. **The booth team** — sound, lights, graphics, stream. They get the
   tech dashboard, the patch, assets, crew seats.
2. **The musicians** — vocalists and band. They get the backstage
   wall: which mic is theirs, which pack, which MyMix channel, where
   they stand. The product started as their wall; never write them
   out of the story.

## Scope — six pillars

1. **Displays** — backstage walls, the micboard, WYSIWYG dashboards
   on any TV (and Rokus).
2. **Wireless & ears** — mic + IEM assignments ("the mic map" lives on
   as a feature name).
3. **Patch & mixes** — the input list, phantom, mute groups, monitor
   routing, MyMix personal mixers.
4. **Assets** — every piece of gear tagged, QR-labeled, status-tracked.
5. **People** — booth crew and band, seat by seat, week by week.
6. **Prep** — weekly imports (Planning Center, input-list workbook),
   Sunday auto-clear, auto-drawn stage plots.

## Naming rules

- Written **TechBooth** — one word, two caps. Never "Tech Booth".
- Lockup: mono caps "A D2 AUDIO PRODUCT". Product sites live at
  `<product>.d2audio.io`.
- Wordmark: Geist 700, tight tracking, acid full-stop: **TechBooth.**
- The venue keeps its own identity on the displays — TechBooth brands
  the admin, the site, the docs. **The wall always wears the venue's
  face.**

## Voice

FedUp's honest-engineer register, aimed at both rooms. Terse, literal,
priced in plain sight ("$X · No subscription"), comfortable saying
what it won't do. Every sentence should sound right whispered over
comms — or shouted from the drum riser. "Run the booth", "The sheet
is the truth", "Runs on a Pi you own". No "empower", no "seamless",
no "ministry impact platform".

## Marks

- `techbooth-icon.svg` — **the XLR**: a face-on connector, acid pins
  on ink. The three pins carry the product's whole story —
  **People** (top left, head-and-shoulders), **Tech** (top right, a bolt), **Church** (bottom, a cross — the foundation the other two
  connect across). Everything plugs in here.
- `techbooth-icon-small.svg` — the same connector with plain pins for
  favicons and anything under ~48 px; the glyphs return with size.
- `techbooth-wordmark.svg` — Geist 700 "TechBooth" with acid period,
  mono lockup caption.

## Positioning

For the tech director who runs the booth every week — and the band
who just need to grab the right pack: Planning Center schedules the
people and the songs; TechBooth runs everything they touch on a
Sunday. Runs on an $80 Raspberry Pi you own; your data stays in one
SQLite file.

Against: the whiteboard and gaff-tape labels, micboard (telemetry
only), CallBoard/VirtualCallboard (crew scheduling, not the booth),
a spreadsheet on a TV, and Planning Center notes fields doing a job
they were never built for.

## Productization roadmap (engineering)

1. **Theming**: venue name/logo/colors as instance settings (the CSS
   is already variable-driven; Immanuel becomes the first theme).
2. **De-hardcode**: schedule, zone names, slot counts → settings;
   importer column maps → per-venue profiles.
3. **Planning Center API** (OAuth) instead of PDF parsing — the killer
   integration for the church market.
4. **Licensing/packaging**: FedUp's model — flat price, no
   subscription, or open core + paid cloud backup. Immanuel stays a
   free instance either way.
