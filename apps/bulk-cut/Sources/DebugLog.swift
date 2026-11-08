import Foundation

/// A plain-text trail of what was staged and what Apply did with it, for a
/// quick look after the fact ("why is that clip still here?"). One file per
/// day under the temporary folder, which macOS empties of files left alone
/// for a few days. Help › Show Debug Log opens today's.
enum DebugLog {
    static let dir = FileManager.default.temporaryDirectory.appendingPathComponent("BulkCut", isDirectory: true)
    static var url: URL { dir.appendingPathComponent(String(stamp(Date()).prefix(10)) + ".log") }

    // Written synchronously: a line is on disk before the app can be quit or killed.
    private static let queue = DispatchQueue(label: "bulk-cut.debug-log")
    nonisolated(unsafe) private static var launched = false
    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        return f
    }()

    private static func stamp(_ d: Date) -> String { queue.sync { formatter.string(from: d) } }

    static func write(_ line: String) {
        let now = Date()
        queue.sync {
            let t = formatter.string(from: now)
            var text = ""
            if !launched {
                launched = true
                text += "\n=== \(t)  BulkCut launched (pid \(getpid())) ===\n"
            }
            text += "\(t.dropFirst(11))  \(line)\n"
            let file = dir.appendingPathComponent(String(t.prefix(10)) + ".log")
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            if let h = try? FileHandle(forWritingTo: file) {
                h.seekToEndOfFile()
                h.write(Data(text.utf8))
                try? h.close()
            } else {
                try? Data(text.utf8).write(to: file)
            }
        }
    }

    /// One line per staged clip, "  name: delete".
    static func staged(_ edits: [String: ClipEdit]) -> String {
        edits.isEmpty ? "  (nothing staged)" : edits.keys.sorted().map { "  \($0): \(edits[$0]!.summary)" }.joined(separator: "\n")
    }

    /// One line per clip whose edit differs, "  name: before → after".
    static func changes(from a: [String: ClipEdit], to b: [String: ClipEdit]) -> String {
        let lines = Set(a.keys).union(b.keys).sorted().compactMap { k -> String? in
            let x = a[k] ?? ClipEdit(), y = b[k] ?? ClipEdit()
            return x == y ? nil : "  \(k): \(x.summary) → \(y.summary)"
        }
        return lines.isEmpty ? "  (no change)" : lines.joined(separator: "\n")
    }
}

extension ClipEdit {
    /// "delete", "keep 1.251–3.000, 4.000–5.500 · turn 180° · zoom 0.250,0.250 0.500×0.500", "nothing".
    var summary: String {
        let keep = ranges.map { r in
            String(format: "%.3f–%.3f", r.start, r.end) + (r.open.map { " (open \($0.rawValue))" } ?? "")
        }.joined(separator: ", ")
        var parts = keep.isEmpty ? [] : ["keep \(keep)"]
        if turns != 0 { parts.append("turn \(turns * 90)°") }
        if let z = zoom { parts.append(String(format: "zoom %.3f,%.3f %.3f×%.3f", z.x, z.y, z.w, z.h)) }
        let what = parts.joined(separator: " · ")
        if deleted { return what.isEmpty ? "delete" : "delete (underneath: \(what))" }
        return what.isEmpty ? "nothing" : what
    }
}
