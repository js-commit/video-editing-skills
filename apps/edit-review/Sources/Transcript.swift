import AppKit
import Foundation

/// One word of the transcript sidecar, plus where it sits in the rendered text.
struct TranscriptWord {
    let start: Double
    let end: Double
    let text: String
    let range: NSRange
}

/// The word-level transcript next to the video (`<stem>.transcript.json`,
/// written by the repo's tools/transcribe.py), rendered once into an
/// attributed string: paragraphs at pauses, a clickable timecode in front
/// of each, and every word carrying a link so a click seeks to it.
final class Transcript {
    let words: [TranscriptWord]
    /// ⌘F: built on the first search, not on load.
    private(set) lazy var search = TranscriptSearch(words: words.map(\.text))
    /// The characters words `w` cover in the rendered text, gaps between them included.
    func range(of w: ClosedRange<Int>) -> NSRange {
        let a = words[w.lowerBound].range, b = words[w.upperBound].range
        return NSRange(location: a.location, length: NSMaxRange(b) - a.location)
    }
    /// Built at `baseFontSize`; `attributed(size:)` rescales the fonts.
    let attributed: NSAttributedString
    static let baseFontSize: CGFloat = 14
    private var sizedCache: (size: CGFloat, string: NSAttributedString)?

    /// The transcript with body text at `size` points (paragraph timecodes
    /// 3 pt smaller). Word ranges are unchanged, only fonts are swapped.
    func attributed(size: CGFloat) -> NSAttributedString {
        if let c = sizedCache, c.size == size { return c.string }
        let out = NSMutableAttributedString(attributedString: attributed)
        let body = NSFont.systemFont(ofSize: size)
        let mono = NSFont.monospacedSystemFont(ofSize: max(size - 3, 9), weight: .regular)
        out.enumerateAttribute(.font, in: NSRange(location: 0, length: out.length)) { value, range, _ in
            guard let f = value as? NSFont else { return }
            out.addAttribute(.font, value: f.isFixedPitch ? mono : body, range: range)
        }
        sizedCache = (size, out)
        return out
    }
    let changed: Bool                   // sidecar _meta bytes differ from the file (re-exported)
    let stale: Bool                     // …and the length differs too: word times no longer line up
    let changeDetail: String?           // "length 12:04.3 → 12:03.3" when stale
    let sourceDuration: Double?         // the length of the file this was transcribed from
    /// The engine named in the sidecar's `_meta.engine` (e.g. "voz"); nil
    /// when the sidecar does not say.
    let engine: String?

    static let wordScheme = "edit-review-word"
    static let paragraphGap = 1.5       // seconds of silence that start a new paragraph

    static func sidecarURL(for video: URL) -> URL {
        video.deletingPathExtension().appendingPathExtension("transcript.json")
    }

    /// Returns nil when there is no readable sidecar with words in it.
    /// ffprobe's duration (in the sidecar) and AVFoundation's differ by up to
    /// ~0.6 s on the same file (container vs. track length), so a length
    /// change has to be bigger than that to count.
    static let lengthTolerance = 1.0

    static func load(for video: URL, duration: Double, timecode: (Double) -> String) -> Transcript? {
        let url = sidecarURL(for: video)
        guard let data = try? Data(contentsOf: url),
              let doc = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let segments = doc["segments"] as? [[String: Any]] else { return nil }
        var changed = false, stale = false
        var detail: String?
        let meta = doc["_meta"] as? [String: Any]
        let sourceDuration = meta?["source_duration_s"] as? Double
        let engine = (meta?["engine"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        if let meta, let bytes = meta["source_bytes"] as? Int,
           let size = (try? FileManager.default.attributesOfItem(atPath: video.path)[.size]) as? Int,
           bytes != size {
            changed = true
            if let was = sourceDuration, duration > 0 {
                stale = abs(was - duration) > lengthTolerance
                if stale { detail = "length \(ReviewStore.mmss(was)) → \(ReviewStore.mmss(duration))" }
            } else {
                stale = true            // no length to compare: assume the worst
                detail = "file changed"
            }
        }
        let t = Transcript(segments: segments, changed: changed, stale: stale, detail: detail,
                           sourceDuration: sourceDuration, engine: engine, timecode: timecode)
        return t.words.isEmpty ? nil : t
    }

    private init(segments: [[String: Any]], changed: Bool, stale: Bool, detail: String?,
                 sourceDuration: Double?, engine: String?, timecode: (Double) -> String) {
        self.engine = engine
        self.changed = changed
        self.stale = stale
        self.changeDetail = detail
        self.sourceDuration = sourceDuration
        let body = NSFont.systemFont(ofSize: Self.baseFontSize)
        let mono = NSFont.monospacedSystemFont(ofSize: Self.baseFontSize - 3, weight: .regular)
        // Every sentence is its own paragraph (a real newline: TextKit 2 hangs
        // on U+2028 line separators in a long paragraph). The first sentence
        // after a pause carries the timecode and extra space above it.
        let paraHead = NSMutableParagraphStyle()
        paraHead.lineSpacing = 3
        paraHead.paragraphSpacing = 2
        paraHead.paragraphSpacingBefore = 12
        let paraBody = NSMutableParagraphStyle()
        paraBody.lineSpacing = 3
        paraBody.paragraphSpacing = 2
        var para: NSParagraphStyle = paraHead
        let out = NSMutableAttributedString()
        var words: [TranscriptWord] = []
        var lastEnd = -Double.infinity

        for seg in segments {
            guard let ws = seg["words"] as? [[String: Any]], !ws.isEmpty else { continue }
            let segStart = (seg["start"] as? Double) ?? (ws.first?["start"] as? Double) ?? 0
            let newParagraph = words.isEmpty || segStart - lastEnd > Self.paragraphGap
            if newParagraph {
                para = paraHead
                if !words.isEmpty { out.append(NSAttributedString(string: "\n", attributes: [.font: body, .paragraphStyle: para])) }
                let label = NSAttributedString(string: timecode(segStart) + "  ", attributes: [
                    .font: mono, .foregroundColor: NSColor.secondaryLabelColor, .paragraphStyle: para,
                    .link: URL(string: "\(Self.wordScheme)://seek/\(segStart)")!,
                ])
                out.append(label)
            } else {
                let brk = Self.endsSentence(words.last?.text)
                out.append(NSAttributedString(string: brk ? "\n" : " ", attributes: [.font: body, .paragraphStyle: para]))
                if brk { para = paraBody }
            }
            for (i, w) in ws.enumerated() {
                guard let text = (w["word"] as? String)?.trimmingCharacters(in: .whitespaces), !text.isEmpty else { continue }
                let start = (w["start"] as? Double) ?? segStart
                let end = (w["end"] as? Double) ?? start
                if i > 0 {
                    let brk = Self.endsSentence(words.last?.text)
                    out.append(NSAttributedString(string: brk ? "\n" : " ", attributes: [.font: body, .paragraphStyle: para]))
                    if brk { para = paraBody }
                }
                let range = NSRange(location: out.length, length: (text as NSString).length)
                out.append(NSAttributedString(string: text, attributes: [
                    .font: body, .foregroundColor: NSColor.labelColor, .paragraphStyle: para,
                    .link: URL(string: "\(Self.wordScheme)://word/\(words.count)")!,
                ]))
                words.append(TranscriptWord(start: start, end: end, text: text, range: range))
                lastEnd = max(lastEnd, end)
            }
        }
        self.words = words
        self.attributed = out
    }

    /// The word being spoken at `seconds`: the last one that has started.
    func index(at seconds: Double) -> Int? {
        guard let first = words.first, seconds >= first.start else { return nil }
        var lo = 0, hi = words.count - 1
        while lo < hi {
            let mid = (lo + hi + 1) / 2
            if words[mid].start <= seconds { lo = mid } else { hi = mid - 1 }
        }
        return lo
    }

    /// "word." / "word?" / 'word!"' end a sentence; closing quotes and brackets are skipped.
    static func endsSentence(_ text: String?) -> Bool {
        guard let t = text else { return false }
        let core = t.reversed().drop { "\"'”’)]".contains($0) }
        return core.first.map { ".?!".contains($0) } ?? false
    }

    /// Seconds a clicked link stands for, or nil if it is not ours.
    func seconds(for link: URL) -> Double? {
        guard link.scheme == Self.wordScheme else { return nil }
        let parts = link.pathComponents.filter { $0 != "/" }
        switch link.host {
        case "word": return Int(parts.first ?? "").flatMap { words.indices.contains($0) ? words[$0].start : nil }
        case "seek": return Double(parts.first ?? "")
        default: return nil
        }
    }
}


/// Runs the repo's `tools/transcribe.py VIDEO` in the background and reports
/// the sidecar it wrote (or reused). The engine is whatever the user chose in
/// the repo's settings (`transcription.engine`); the app does not care which.
/// The transcript here is for reading along and finding things.
@MainActor
final class Transcriber: ObservableObject {
    @Published private(set) var running = false
    @Published private(set) var progress = ""

    private var process: Process?

    enum Failure: Error, CustomStringConvertible {
        case notInstalled, exit(Int32, String), cancelled

        var description: String {
            switch self {
            case .notInstalled:
                return "tools/transcribe.py not found: pick the repo folder (Review › Set Skills Repo Folder…), or reinstall with apps/install_apps.sh"
            case .cancelled:
                return "transcription cancelled"
            case .exit(let code, let tail):
                let why: String
                switch code {
                case 2: why = "usage or setup problem"
                case 4: why = "no transcription engine is set up yet (ask Claude to run the setup skill, or set transcription.engine)"
                case 5: why = "the configured transcription engine cannot run on this Mac"
                case 6: why = "no speech found"
                default: why = "exit \(code)"
                }
                return tail.isEmpty ? why : "\(why) — \(tail)"
            }
        }
    }

    /// The transcription script, if the repo can be found.
    static func executable() -> URL? { RepoTools.script("tools/transcribe.py") }

    func run(video: URL) async -> Result<URL, Failure> {
        guard let script = Self.executable() else { return .failure(.notInstalled) }
        let p = RepoTools.pythonProcess(script: script, arguments: [video.path])
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        let tail = LineTail()
        err.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty, let s = String(data: d, encoding: .utf8) else { return }
            let lines = s.split(whereSeparator: \.isNewline).map(String.init)
            tail.append(lines)
            if let last = lines.last {
                Task { @MainActor in self?.progress = last }
            }
        }
        running = true
        progress = "starting transcribe.py…"
        process = p
        defer { running = false; process = nil }
        do { try p.run() } catch {
            return .failure(.exit(-1, error.localizedDescription))
        }
        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            p.terminationHandler = { _ in c.resume() }
        }
        err.fileHandleForReading.readabilityHandler = nil
        let stdout = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        if p.terminationReason == .uncaughtSignal { return .failure(.cancelled) }
        guard p.terminationStatus == 0 else {
            return .failure(.exit(p.terminationStatus, tail.last))
        }
        let path = stdout.split(whereSeparator: \.isNewline).last.map(String.init)?
            .trimmingCharacters(in: .whitespaces) ?? ""
        return .success(path.isEmpty ? Transcript.sidecarURL(for: video) : URL(fileURLWithPath: path))
    }

    func cancel() {
        process?.terminate()
    }
}

extension Transcriber.Failure {
    /// One line for the transcript pane.
    var note: String {
        if case .exit(6, _) = self { return "No speech in this file." }
        return "Transcription failed: \(description)"
    }
}


/// Last few stderr lines of the child, written from the pipe's reader thread.
private final class LineTail: @unchecked Sendable {
    private var lines: [String] = []
    private let lock = NSLock()
    func append(_ new: [String]) { lock.lock(); lines = Array((lines + new).suffix(3)); lock.unlock() }
    var last: String { lock.lock(); defer { lock.unlock() }; return lines.last ?? "" }
}
