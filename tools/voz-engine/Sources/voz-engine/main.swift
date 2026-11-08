// voz-engine - see Package.swift.
//
//   voz-engine INPUT [-o OUT.json] [--language en] [--no-align]
//
// INPUT: any audio or video file AVFoundation reads (transcribe.py hands it a 16 kHz mono WAV
// when ffmpeg is available, so every tool in the pipeline decodes the same samples). Decoded
// once to 16 kHz mono Float32, which is both models' native rate.
//
// Output JSON: {"engine", "model", "language", "duration", "words": [{"text","start","end"}],
// "stats": {...}}. Progress and errors on stderr. Exit 0 ok, 1 failure, 2 usage.
import AVFoundation
import Align
import Foundation
import Voz

struct Fail: Error, CustomStringConvertible { let description: String }

func log(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }
func now() -> Double { Date().timeIntervalSince1970 }

func arg(_ name: String, _ args: [String]) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

/// Any container / codec -> 16 kHz mono Float32 via AVAssetReader (it resamples and downmixes).
/// The first audio track, as ffmpeg's `-ac 1` default would pick.
func decode16k(_ path: String) async throws -> [Float] {
    let asset = AVURLAsset(url: URL(fileURLWithPath: path))
    guard let track = try await asset.loadTracks(withMediaType: .audio).first else {
        throw Fail(description: "\(path): no audio track")
    }
    let reader = try AVAssetReader(asset: asset)
    let out = AVAssetReaderTrackOutput(track: track, outputSettings: [
        AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
        AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true, AVLinearPCMIsBigEndianKey: false,
        AVLinearPCMIsNonInterleaved: false,
    ])
    reader.add(out)
    guard reader.startReading() else { throw Fail(description: "\(path): \(reader.error?.localizedDescription ?? "unreadable")") }
    var samples: [Float] = []
    while let sb = out.copyNextSampleBuffer() {
        guard let bb = CMSampleBufferGetDataBuffer(sb) else { continue }
        let n = CMBlockBufferGetDataLength(bb) / MemoryLayout<Float>.size
        let start = samples.count
        samples.append(contentsOf: repeatElement(0, count: n))
        samples.withUnsafeMutableBytes { raw in
            _ = CMBlockBufferCopyDataBytes(bb, atOffset: 0, dataLength: n * MemoryLayout<Float>.size,
                                           destination: raw.baseAddress! + start * MemoryLayout<Float>.size)
        }
    }
    if reader.status == .failed { throw Fail(description: "\(path): \(reader.error?.localizedDescription ?? "decode failed")") }
    return samples
}

/// Align refines each boundary independently, so some neighbours come back overlapping and a
/// few starts out of order. Starts are made non-decreasing (a word that jumped before its
/// predecessor gets its input start back), then every end is clamped to the next start and to
/// its own start.
func clamp(_ refined: [WordTiming], original: [WordTiming]) -> ([WordTiming], Int, Int) {
    var w = refined, starts = 0, ends = 0
    for i in w.indices.dropFirst() where w[i].start < w[i - 1].start {
        w[i].start = max(original[i].start, w[i - 1].start); starts += 1
    }
    for i in w.indices {
        if i + 1 < w.count, w[i].end > w[i + 1].start { w[i].end = w[i + 1].start; ends += 1 }
        if w[i].end < w[i].start { w[i].end = w[i].start }
    }
    return (w, starts, ends)
}

let args = Array(CommandLine.arguments.dropFirst())
guard let input = args.first, !input.hasPrefix("-") else {
    log("usage: voz-engine INPUT [-o OUT.json] [--language en] [--no-align]"); exit(2)
}
let language = arg("--language", args) ?? "en"
let useAlign = !args.contains("--no-align")

do {
    guard Voz.supportedLanguages.contains(language) else {
        throw Fail(description: "Voz does not know language '\(language)' (it has: \(Voz.supportedLanguages.sorted().joined(separator: " ")))")
    }
    let t0 = now()
    let samples = try await decode16k(input)
    guard !samples.isEmpty else { throw Fail(description: "\(input): decoded to no audio") }
    let duration = Double(samples.count) / 16000
    let t1 = now()
    if !Voz.isDownloaded() { log("downloading the Voz model (about 470 MB, once) ...") }
    let voz = try await Voz()
    let t2 = now()
    let result = try await voz.transcribe(samples: samples, sampleRate: 16000)
    let t3 = now()
    var words = result.words.map { WordTiming(text: $0.text, start: $0.start, end: $0.end) }
    var stats: [String: Any] = ["decode_s": t1 - t0, "load_s": t2 - t1, "voz_s": t3 - t2, "words": words.count]
    if useAlign, !words.isEmpty {
        let align = Align()
        try await align.download()
        if try await align.isSupported(languageCode: language) {
            let t4 = now()
            let refined = try await align.refine(words, audio: samples, sampleRate: 16000, languageCode: language)
            let (fixed, starts, ends) = clamp(refined, original: words)
            stats["align_s"] = now() - t4
            stats["refined"] = refined.filter(\.refined).count
            stats["clamped_starts"] = starts
            stats["clamped_ends"] = ends
            words = fixed
        } else {
            log("Align has no model for '\(language)'; keeping Voz's own word times")
        }
    }
    stats["zero_length"] = words.filter { $0.end <= $0.start }.count
    let doc: [String: Any] = [
        "engine": useAlign ? "voz+align" : "voz", "model": "desert-ant-core 3.5.0 Voz + Align",
        "language": language, "duration": duration, "stats": stats,
        "words": words.map { ["text": $0.text, "start": $0.start, "end": $0.end] as [String: Any] },
    ]
    let data = try JSONSerialization.data(withJSONObject: doc, options: [.sortedKeys])
    if let o = arg("-o", args) { try data.write(to: URL(fileURLWithPath: o)) }
    else { FileHandle.standardOutput.write(data) }
} catch {
    log("voz-engine: \(error)"); exit(1)
}
