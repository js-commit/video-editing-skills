// swift-tools-version: 6.2
// voz-engine: the local, offline speech-to-text engine behind tools/transcribe.py
// (`--engine voz`). Desert Ant Labs' Voz (NVIDIA Parakeet TDT 0.6B v3, Core ML on the
// Neural Engine) recognises the words, their Align model refines the word edges, and a
// monotonic clamp removes the overlaps Align leaves.
//
// The prebuilt binary is committed at tools/bin/voz-engine (arm64, macOS 26+; the SDK is
// compiled in, the ~470 MB model downloads on first use). Rebuild only after changing
// main.swift or the SDK version:  tools/voz-engine/build.sh
import PackageDescription

let package = Package(
    name: "voz-engine",
    platforms: [.macOS(.v26)],
    dependencies: [.package(url: "https://github.com/Desert-Ant-Labs/desert-ant-core.git", exact: "3.5.0")],
    targets: [.executableTarget(name: "voz-engine",
                                dependencies: [.product(name: "Voz", package: "desert-ant-core"),
                                               .product(name: "Align", package: "desert-ant-core")],
                                swiftSettings: [.swiftLanguageMode(.v5)])]
)
