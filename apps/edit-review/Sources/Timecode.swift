import Foundation

/// Resolve-style `HH:MM:SS:FF` timecode, non-drop.
///
/// `fps` is the file's real frame rate (23.976, 29.97, 59.94, 25, 30, 60);
/// the nominal timecode base (24, 30, 60 frames per timecode-second) is
/// derived by rounding. Non-drop timecode at 29.97 runs slightly slower than
/// wall-clock — that is exactly what Resolve's non-drop ruler shows, so frame
/// counts, not seconds, are the unit that lines up with the timeline.
enum Timecode {
    static func base(for fps: Double) -> Int { max(1, Int(fps.rounded())) }

    /// Frame index of a file-relative time.
    static func frames(seconds: Double, fps: Double) -> Int {
        max(0, Int((seconds * fps + 1e-6).rounded(.down)))
    }

    static func string(frames: Int, fps: Double) -> String {
        let b = base(for: fps)
        let f = max(0, frames)
        let ff = f % b
        let s = (f / b) % 60
        let m = (f / (b * 60)) % 60
        let h = f / (b * 3600)
        return String(format: "%02d:%02d:%02d:%02d", h, m, s, ff)
    }

    static func string(seconds: Double, fps: Double, startFrames: Int = 0) -> String {
        string(frames: frames(seconds: seconds, fps: fps) + startFrames, fps: fps)
    }

    /// Parse `HH:MM:SS:FF` (`;` accepted too) into a frame count at `fps`.
    static func parse(_ text: String, fps: Double) -> Int? {
        let parts = text.trimmingCharacters(in: .whitespaces)
            .split(whereSeparator: { $0 == ":" || $0 == ";" })
            .map { Int($0) }
        guard parts.count == 4,
              let h = parts[0], let m = parts[1], let s = parts[2], let f = parts[3],
              h >= 0, (0..<60).contains(m), (0..<60).contains(s) else { return nil }
        let b = base(for: fps)
        guard (0..<b).contains(f) else { return nil }
        return ((h * 60 + m) * 60 + s) * b + f
    }

    /// Render a drop-frame frame number as the `HH:MM:SS:FF` label it carries.
    /// Only used to read a drop-frame timecode track's start label; the app
    /// itself counts non-drop.
    static func dropFrameString(frames: Int, fps: Double) -> String {
        let b = base(for: fps)
        let drop = Int((fps * 0.066666).rounded())          // 2 @ 29.97, 4 @ 59.94
        guard drop > 0 else { return string(frames: frames, fps: fps) }
        let per10Min = b * 600 - drop * 9
        let perMin = b * 60 - drop
        var f = max(0, frames)
        let d = f / per10Min
        let m = f % per10Min
        f += drop * 9 * d + (m > drop ? drop * ((m - drop) / perMin) : 0)
        return string(frames: f, fps: fps)
    }
}
