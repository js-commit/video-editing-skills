import Foundation
import Clear

// clearlab IN.wav OUT.wav <studio|natural> <strength 0-1>
// Mono 48 kHz 16-bit WAV out, sample-aligned with the input, mastering bypassed (the caller
// loudness-normalises). Prints one JSON line.
let a = CommandLine.arguments
guard a.count == 5, let s = Double(a[4]), ["studio", "natural"].contains(a[3]) else {
    FileHandle.standardError.write("usage: clearlab IN.wav OUT.wav studio|natural STRENGTH\n".data(using: .utf8)!)
    exit(64)
}
let variant: ModelVariant = a[3] == "natural" ? .clearNatural : .clearStudio
let clear = Clear(variant: variant)
let r = try await clear.enhance(path: a[1], to: a[2], options: .init(strength: .init(s), mastering: .bypass))
let out: [String: Any] = ["variant": variant.rawValue, "strength": s, "model_revision": r.modelRevision ?? "",
                          "duration_s": r.durationSec, "realtime_factor": r.realtimeFactor]
print(String(data: try JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), encoding: .utf8)!)
