# Free stock footage and press images

Only when the user agrees to look online for a slot. Licences change:
read the licence page of the site (and of the file, where it has one) at
download time and record what it said.

## The bar

- Free for use in a monetised video, no account wall for the download, no
  watermark, no ripped video from video platforms.
- Record per file: page URL, author, licence name, whether credit is
  required and the exact credit line.
- Prefer real footage of the exact thing being said. A generic "lifestyle"
  shot over specific words is a miss; a gap is better.

## Where to look

| Source | Good for | Licence notes |
|---|---|---|
| Pexels (video and photos) | establishing shots, places, generic actions | Pexels licence: free, credit appreciated but not required; people and brands in shot are not endorsements |
| Pixabay | same | its own content licence; some downloads need an account, skip those |
| Wikimedia Commons | real-world photos of specific products, places, events | per file: public domain, CC0, CC BY or CC BY-SA; copy the attribution string from the file page |
| Openverse | a search across openly licensed images | the licence of each result's source |
| Unsplash | photos | Unsplash licence: free, no credit required |
| Manufacturer press kits / newsrooms | clean product shots | editorial use with the credit the company asks for; not stock, never re-host |

WebSearch with `site:<domain> <terms>` finds candidates; fetch the page to
read the licence and the real resolution.

## Verify every download

1. `ffprobe` it: reject HTML error pages, portrait clips for a landscape
   timeline, anything under 1080p, clips shorter than the slot.
2. Extract a few frames (`frames.py <file> <dir> --interval 1`) and READ
   them. Reject anything the page over-claimed.
3. Photos: never a bare portrait or 4:3 image on a 16:9 timeline (the a-roll
   shows at the sides). Build a full-frame card: the image on a blurred or
   dark background at timeline resolution, with the credit line if required.

## Where files go

`<project>/<project_layout.footage>/stock-web/<topic>/`, with a
`SOURCES.md` table (file, URL, author, licence, credit, resolution, fps,
duration, one-line description). Report every credit line the video
description needs.

Stock usually runs at 25, 30 or 60 fps. In Resolve, conforming the clip to
the timeline rate (Clip Attributes > Video Frame Rate) plays it slightly
slower or faster but frame for frame; plan seconds stay in the file's own
real time either way.
