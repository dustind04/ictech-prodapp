# MicMap — brand guide

**MicMap** is the productized form of this codebase: backstage display
software for live production. A D2 product, alongside **LiveNotes**,
**GigMix**, and **FedUp**.

> Name due diligence (July 2026): "CallBoard" and "VirtualCallboard"
> are existing products in this space; "StageCall" and "SideStage" are
> taken. "MicMap" searched clean. Register domains/trademark before
> public launch.

## The one-liner

**MicMap — who's on what.**

Longer: *The backstage wall that knows. Who's on which mic, pack, and
position — live on every screen in the building, fed by the files your
team already makes.*

## Naming rules

- Written **MicMap** — one word, two caps. Never "Mic Map", "Micmap".
- Family lockup: "MicMap — a D2 product" (see wordmark SVG).
- The venue/church instance keeps its own identity on the displays
  (that's the point — MicMap is the frame, the venue is the face).
  MicMap brands the admin, the site, the docs — never the wall.

## Voice

Terse, stagehand-literal, zero SaaS-speak. Every sentence should sound
right shouted across a stage during soundcheck. "Who's on what", "The
sheet is the truth", "Doors at 8:15". No "empower", no "seamless", no
"solutions".

## Palette — dark-native

The product lives on TVs in dim rooms; the brand does too. Light mode
exists only for the admin.

| Token | Hex | Use |
|---|---|---|
| Stage black | `#0E0E10` | background, app icon tile |
| Panel | `#1A1A1D` | cards, tiles |
| Hairline | `#26262B` | borders, the dot grid |
| Signal amber | `#FFB020` | THE brand accent — wordmark "Map", pins, CTAs |
| Live green | `#3DDC84` | live/on-air states, the pin's dot |
| Alert red | `#E5484D` | over-time, missing, errors |
| Off-white | `#F4F4F2` | primary text |
| Gray | `#7C7C82` | secondary text |

Amber is deliberately NOT Immanuel green — instance colors belong to
venues; amber belongs to MicMap.

## Marks

- `micmap-icon.svg` — the pin-mic: a microphone grille that is also a
  map pin (who + where in one shape), live-green dot at the point,
  dot-grid board behind. Works at 16 px.
- `micmap-wordmark.svg` — Inter 800, "Mic" off-white + "Map" amber,
  "A D2 PRODUCT" caption.
- Type: **Inter** everywhere, same as the product UI.

## Positioning

For the tech director at a church, school, theater, or small venue who
runs wireless every week: MicMap turns the files you already make
(Planning Center reports, input-list spreadsheets) into live backstage
displays — mic assignments, IEM packs, stage positions, patch, crew —
plus QR-labeled asset tracking and build-your-own dashboards for every
TV in the building. Runs on a $80 Raspberry Pi you own; your data
stays in one SQLite file.

Against: whiteboards and gaff-tape labels (what everyone actually
uses), micboard (telemetry only, no people), VirtualCallboard/CallBoard
(scheduling & crew comms, not the wall), spreadsheets on a TV.

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
