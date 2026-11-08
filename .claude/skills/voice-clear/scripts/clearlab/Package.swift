// swift-tools-version: 6.2
// clearlab: a tiny CLI over Desert Ant Labs' Clear SDK (voice denoise + dereverb, Core ML on the
// Neural Engine). The SDK's own `da clear` CLI has no variant / strength / mastering flags, so the
// voice-clear skill builds this instead. A prebuilt binary is committed at ../bin/clearlab;
// `voice_clear.py build` rebuilds it after a wrapper or SDK change.
import PackageDescription

let package = Package(
    name: "clearlab",
    platforms: [.macOS(.v15)],
    dependencies: [.package(url: "https://github.com/Desert-Ant-Labs/desert-ant-core.git", exact: "3.5.0")],
    targets: [.executableTarget(name: "clearlab",
                                dependencies: [.product(name: "Clear", package: "desert-ant-core")])]
)
