# TechBooth — brand guide

**TechBooth** is the productized form of this codebase: the operating
system for a church's tech ministry. A D2 product, alongside
**LiveNotes**, **GigMix**, and **FedUp**.

**Planning Center runs the service. TechBooth runs the booth.**

> Name due diligence (July 2026): "TechBooth" has no software product
> collision — only a Kenyan tech-news site (techbooth.africa) in an
> unrelated category. In our space, CallBoard, VirtualCallboard,
> StageCall, and SideStage are all taken; earlier candidate "MicMap"
> was clean but too narrow — the product is all of tech, not mics.
> Register domains/trademark before public launch.

## The one-liner

**TechBooth — run the booth.**

Longer: *Everything the tech team owns and runs — wireless, patch,
in-ears, gear, crew, displays — in one place, on every screen in the
building, fed by the files your team already makes.*

## Scope — the six pillars

The brand talks about the whole booth, never just one pillar:

1. **Displays** — backstage walls, the micboard, WYSIWYG dashboards on
   any TV (and Rokus).
2. **Wireless** — mic + IEM assignments, "the mic map" (kept as a
   lowercase feature name inside the product).
3. **Patch** — the input list, phantom, mute groups, monitor routing.
4. **Assets** — every piece of gear tagged, QR-labeled, status-tracked.
5. **Crew** — who's behind the controls, week by week.
6. **Prep** — weekly imports (Planning Center, input-list workbook),
   auto-clear after Sunday, auto-drawn stage plots.

## Naming rules

- Written **TechBooth** — one word, two caps. Never "Tech Booth",
  "Techbooth". The team using it is "the booth team" — market-native
  language, use it.
- Family lockup: "TechBooth — a D2 product" (see wordmark SVG).
- The venue keeps its own identity on the displays — TechBooth brands
  the admin, the site, the docs. **The wall always wears the venue's
  face.**

## Voice

Terse, booth-literal, zero SaaS-speak. Every sentence should sound
right whispered over comms during a service. "Run the booth", "The
sheet is the truth", "Doors at 8:15". No "empower", no "seamless",
no "solutions", no "ministry impact platform".

## Palette — dark-native

The booth is a dim room at the back of the house; the brand lives
there. Light mode exists only for the admin.

| Token | Hex | Use |
|---|---|---|
| Stage black | `#0E0E10` | background, app icon tile |
| Panel | `#1A1A1D` | cards, tiles |
| Hairline | `#26262B` | borders, house rows |
| Signal amber | `#FFB020` | THE accent — the lit booth window, CTAs, "Booth" |
| Live green | `#3DDC84` | tally: live/on-air states |
| Alert red | `#E5484D` | over-time, missing, errors |
| Off-white | `#F4F4F2` | primary text |
| Gray | `#7C7C82` | secondary text |

Amber is deliberately nobody's church green — instance colors belong
to venues; amber belongs to TechBooth.

## Marks

- `techbooth-icon.svg` — the lit booth window at the back of a dark
  house: three crew heads at the consoles, green tally light on, faint
  seating rows below. The amber window survives to 16 px.
- `techbooth-wordmark.svg` — Inter 800, "Tech" off-white + "Booth"
  amber, "A D2 PRODUCT" caption.
- Type: **Inter** everywhere, same as the product UI.

## Positioning

For the tech director who runs the booth every week: Planning Center
schedules the people and the songs; TechBooth runs everything the tech
team actually touches — assignments on backstage walls, the patch on
the tech dashboard, QR-tagged gear, crew seats, and build-your-own
dashboards for every TV in the building. Runs on an $80 Raspberry Pi
you own; your data stays in one SQLite file.

Against: the whiteboard and gaff-tape labels (what booths actually
use), micboard (telemetry only), CallBoard/VirtualCallboard (crew
scheduling, not the booth), a spreadsheet on a TV, and doing it all
in Planning Center notes fields.

## Productization roadmap (engineering)

1. **Theming**: venue name/logo/colors as instance settings (the CSS
   is already variable-driven; Immanuel becomes the first theme).
2. **De-hardcode**: schedule (service times/rehearsal), zone names,
   slot counts → settings; importer column maps → per-venue profiles.
3. **Planning Center API** (OAuth) instead of PDF parsing — the killer
   integration for the church market.
4. **Licensing/packaging**: public Docker image + license key, or
   fully open core + paid cloud sync/backup. Immanuel stays a free
   instance either way.
