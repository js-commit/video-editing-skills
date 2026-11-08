# voz-engine

The offline speech-to-text engine behind `tools/transcribe.py --engine voz`:
a small Swift command that runs [Desert Ant Labs'](https://github.com/Desert-Ant-Labs/desert-ant-core)
**Voz** (NVIDIA Parakeet TDT 0.6B v3 on the Neural Engine) for the words and
their **Align** model for the word edges, then clamps the few overlaps Align
leaves so word times never go backwards.

- Apple silicon Mac, macOS 26 or newer. Your audio and transcripts stay on the
  Mac; the SDK sends Desert Ant Labs a small usage signal (a generated device
  id, a call count, the program and SDK names, and the OS name and major version;
  never audio or text).
- `tools/bin/voz-engine` is a prebuilt binary, signed and notarized (about 2 MB,
  SDK compiled in), so there is nothing to build.
  The ~470 MB model downloads into `~/Library/Caches/desert-ant-models` the
  first time it runs; after that it works offline.
- `./build.sh` rebuilds the binary from this source (needs `swift` from Xcode
  or the Command Line Tools). Only needed if you change `main.swift` or bump
  the SDK version in `Package.swift`.

```
voz-engine INPUT [-o OUT.json] [--language en] [--no-align]
```

Output: `{"engine", "model", "language", "duration", "words": [{"text", "start", "end"}], "stats"}`.
`tools/vidkit/engines/voz.py` turns that into the transcript sidecar.
