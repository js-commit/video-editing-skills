# Notice

`engine/motion.js` (the spring engine, the morphing-shape scene runner, the cursor) and the clip-authoring model
(`reference/engine-api.md`, the cursor in `scripts/build.py`) are adapted from **motion-broll** in
github.com/Barty-Bart/motion-graphics (commit e8d610a), under the MIT License:

> MIT License
>
> Copyright (c) 2026 Bart
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
> rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
> persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
> Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
> WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
> COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

`reference/look.md` (and the look step in `SKILL.md`) adapt the method of **HyperFrames** by HeyGen,
github.com/heygen-com/hyperframes (commit 88db830), from `skills/hyperframes/references/look.md`, `spec.md`, `motion.md`
and `types/data.md`: a look taken from outside input and written as numbers, the list of generated-video defaults to
ban, a look as the rules of one medium, motion by role, charts as pictures. Licensed under the Apache License, Version
2.0 (http://www.apache.org/licenses/LICENSE-2.0), Copyright 2026 HeyGen, Inc. The text here is rewritten for this skill
and changed from the original; no HyperFrames code, CLI, registry item, font or preset is used.

Icon paths in `M.IC` are adapted from Lucide (lucide.dev), under the ISC License. Some of those icons (among them
arrow-right, check, x, plus, clock, search, terminal, star and cpu) are derived from Feather, which Lucide redistributes
under the MIT License:

> ISC License
>
> Copyright (c) 2026 Lucide Icons and Contributors
>
> Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby
> granted, provided that the above copyright notice and this permission notice appear in all copies.
>
> THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL
> IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
> INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
> AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
> PERFORMANCE OF THIS SOFTWARE.

> The MIT License (MIT) (for the Lucide icons derived from Feather)
>
> Copyright (c) 2013-present Cole Bemis
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
> rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
> persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
> Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
> WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
> COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Changed here: no Playwright or downloaded Chromium (any Chromium-family browser already installed is driven over its
DevTools protocol from standard-library Python), no npm/pip setup, word timings from the project's own transcript
instead of estimated subtitles, ffmpeg encoding through vidkit, the recipe as the deliverable instead of preview pages,
a themeable palette, and system fonts instead of bundled ones.
