# Stop motion

Stop motion is a sequence of still photos, each with the subject moved a
little, played back fast enough to look like motion. Consistency between
frames is everything: anything that changes by accident (light, focus,
camera position) flickers or jumps.

## Shooting

**Lock the camera down**
- A sturdy tripod or a rig; tape its legs or weigh it down. Never touch the
  camera between frames: trigger with a remote, a phone app, a timer, or
  tethered software.
- Tape the set and the background in place too.
- Turn off image stabilization (it nudges the frame between shots).

**Go fully manual** (anything automatic changes frame to frame and flickers)
- Exposure: manual mode, fixed shutter, aperture and ISO.
- White balance: a fixed preset or Kelvin value, not auto.
- Focus: focus once, then switch to manual focus so it doesn't hunt.
- Phones: use an app with exposure/focus lock (many stop-motion apps do),
  or a pro camera mode.

**Light**
- Use your own lamps and block windows: daylight changes minute to minute
  and clouds cause flicker. Don't stand where your shadow or a reflection
  falls on the set.
- Mains power for the camera if you can (long sessions drain batteries).

**Frame rate and "on twos"**
- Film runs at 24 frames per second (fps). Animating "on ones" = a new photo
  for every frame (24 photos per second of video: very smooth, lots of work).
- "On twos" = each photo held for two frames: 12 photos per second played in a
  24 fps video. The classic stop-motion look and half the work. Many beginners
  start at 12 fps, or even 8-10 for a deliberately choppy feel.
- Small, even moves give smooth motion; ease in and out (smaller moves at the
  start and end of a motion) so things don't start and stop abruptly.

**Onion skinning**
- Shows the previous frame semi-transparent over the live view, so you can
  judge how far to move the subject. Stop-motion apps (free and paid ones
  exist for phones and computers) have it built in; pro tools also do
  tethered capture and live preview.

**Shooting tips**
- Shoot a few frames of the empty set first (useful for cleanup).
- Name/number files sequentially (the camera does; keep the order).
- Shoot at least 16:9-friendly framing: photos are usually 3:2 or 4:3 and will
  be cropped top and bottom for a 16:9 video.

## Assembling with ffmpeg

Number the photos in order (frame_0001.jpg, frame_0002.jpg, ...). If they
are camera names in order (IMG_1234.JPG...), a glob works on macOS/Linux.

12 photos per second into a 24 fps 4K video (each photo shows twice: "on
twos"), cropped to 16:9, high quality:

```sh
ffmpeg -framerate 12 -i frame_%04d.jpg \
  -vf "scale=3840:-2,crop=3840:2160,format=yuv420p" -r 24 \
  -c:v libx264 -crf 16 -preset slow stopmotion.mp4
```

- `-framerate 12` = photos per second; `-r 24` = output frame rate (each photo
  repeated to fill it). For "on ones", use `-framerate 24` and drop `-r`.
- Camera file names in order (macOS/Linux): replace the input with
  `-pattern_type glob -i '*.JPG'`.
- Photos wider than 16:9 after scaling? `crop=3840:2160` keeps the center;
  move it with `crop=3840:2160:0:Y` (Y = pixels from the top).
- Light flicker between frames: add `deflicker=mode=pm:size=5,` at the start
  of the `-vf` chain (it averages brightness over 5 frames).
- Preview quickly at 1080p first: `scale=1920:-2,crop=1920:1080`.

## Assembling in DaVinci Resolve

1. Media page: Resolve shows a numbered sequence of images as **one clip**
   (an image sequence) by default. If you see individual frames instead,
   change the frame display mode to Sequence (in recent versions it is in
   the "..." options menu of the Media Storage panel).
2. Import the sequence. Set its speed: right-click the clip > Clip
   Attributes > Video > Video Frame Rate (e.g. 12). On a 24 fps timeline each
   photo then shows twice.
3. Make a timeline at the size you want (e.g. 3840x2160, 24 fps) and drop the
   clip in. Use the Inspector > Transform (Zoom, Position) to crop the 3:2
   photos to 16:9.
4. Studio's Deflicker effect (OpenFX, Color page) evens out light flicker.
5. Add sound effects and music; stop motion sells with sound.
