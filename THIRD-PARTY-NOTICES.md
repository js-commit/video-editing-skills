# Third-party notices

This repository is MIT licensed (see `LICENSE`). It ships or downloads the
following third-party components, each under its own terms.

## Desert Ant Labs SDK (desert-ant-core 3.5.0)

Powered by [Desert Ant Labs](https://desertant.com). The prebuilt programs `tools/bin/voz-engine`
(Voz speech recognition + Align word timing) and
`.claude/skills/voice-clear/scripts/bin/clearlab` (Clear speech enhancement)
embed the Desert Ant Labs SDK, which is distributed under the Desert Ant Labs
Source-Available License 1.0 (https://license.desertant.com/1.0): free below
100,000 monthly active devices per platform, attribution required, no training
of competing models on its outputs. The SDK is source-available, not open source,
and this repository's MIT licence does not cover it. It sends Desert Ant Labs a
small usage signal to count devices (a generated device id, a call count, the
program and SDK names, and the OS name and major version; never audio, text or
anything else you put in). The model weights are downloaded by the SDK
on first use under the same licence; nothing from Desert Ant Labs is modified
here. Source: https://github.com/Desert-Ant-Labs/desert-ant-core (the Swift
wrappers in `tools/voz-engine/` and `.claude/skills/voice-clear/scripts/clearlab/`
are this repository's own, MIT).

## Qwen3.5-9B (mlx-community/Qwen3.5-9B-4bit)

Not shipped; `tools/vlm-describe` downloads it from Hugging Face on first use
under the model's own licence (Apache-2.0 for the Qwen3.5 family at the time of
writing; check the model card).

## motion-graphics engine

See `.claude/skills/motion-graphics/NOTICE.md`.
