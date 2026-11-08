import CryptoKit
import Foundation

enum MediaKind: String, Sendable { case video, photo }

/// One video or photo under the open folder.
struct Clip: Identifiable, Hashable, Sendable {
    let url: URL
    let size: Int64
    let modified: Date
    let created: Date
    let kind: MediaKind
    /// The path under the open folder, "a.mov" or "Trip/IMG_1.HEIC": what
    /// staged edits and notes are keyed by (names repeat across subfolders).
    let key: String

    var id: URL { url }
    var name: String { url.lastPathComponent }
    var isPhoto: Bool { kind == .photo }
    /// The subfolder it is in, "" for the open folder itself.
    var folderPath: String { (key as NSString).deletingLastPathComponent }
}

/// How far a scan has got, read by the UI a few times a second; `stop()`
/// ends it with what it has found.
final class ScanProgress: @unchecked Sendable {
    private let lock = NSLock()
    private var files = 0
    private var folders = 0
    private var current = ""
    private var halted = false

    var stopped: Bool { lock.withLock { halted } }
    func stop() { lock.withLock { halted = true } }
    func found() { lock.withLock { files += 1 } }
    func entering(_ path: String) { lock.withLock { folders += 1; current = path } }
    /// Files found, folders entered, the folder being read ("" for the open one).
    var snapshot: (files: Int, folders: Int, current: String) { lock.withLock { (files, folders, current) } }
}

/// A run of the list from one folder, under its header.
struct ClipSection: Identifiable, Sendable {
    /// The subfolder, "" for the open folder.
    let path: String
    let range: Range<Int>
    var id: String { path }
}

enum Library {
    /// What AVFoundation plays and ImageIO reads. Everything else in the folder is left alone.
    static let videoExtensions: Set<String> = ["mov", "mp4", "m4v"]
    static let photoExtensions: Set<String> = ["jpg", "jpeg", "heic", "heif", "png", "tif", "tiff", "gif", "bmp", "webp", "avif"]
    /// Folders never worth a look: thousands of icons, no photos.
    static let skippedFolders: Set<String> = ["node_modules"]

    static func kind(_ url: URL) -> MediaKind? {
        let e = url.pathExtension.lowercased()
        return videoExtensions.contains(e) ? .video : photoExtensions.contains(e) ? .photo : nil
    }

    /// The folder's videos and photos in Finder name order, then (with
    /// `subfolders`) each subfolder's, depth first, folders in name order.
    /// Hidden files and folders are skipped, which covers macOS's `._`
    /// AppleDouble files on exFAT cards and drives and the app's own
    /// `.bulkcut-…` temp files; so are packages (an .app, a Photos library)
    /// and symlinked folders. Symlinked files are skipped too (Apply would
    /// act on the link, not the file), except with `followLinks`: a review
    /// folder (Manifest.swift) may link to the originals instead of copying
    /// them, and nothing there is ever trimmed or trashed. A network share can
    /// take seconds a folder, so `progress` hears of each file found, and
    /// stopping it ends the scan with what was found so far.
    static func scan(_ folder: URL, subfolders: Bool, followLinks: Bool = false,
                     progress: ScanProgress? = nil) throws -> [Clip] {
        var out: [Clip] = []
        try walk(folder, prefix: "", subfolders: subfolders, followLinks: followLinks, local: MediaCache.isLocal(folder),
                 progress: progress ?? ScanProgress(), into: &out)
        return out
    }

    /// No .isPackageKey: on an SMB share without Apple's extensions it costs
    /// two more round trips an entry, so it is asked of folders alone.
    static let scanKeys: [URLResourceKey] = [.isRegularFileKey, .isDirectoryKey, .isSymbolicLinkKey,
                                             .fileSizeKey, .contentModificationDateKey, .creationDateKey]

    private static func walk(_ dir: URL, prefix: String, subfolders: Bool, followLinks: Bool, local: Bool,
                             progress: ScanProgress, into out: inout [Clip]) throws {
        guard !progress.stopped else { return }
        progress.entering(prefix)
        // An enumerator, not contentsOfDirectory: entries arrive as the
        // server sends them, so a slow folder shows progress and can be stopped.
        // On a network share hidden means a leading dot: .skipsHiddenFiles
        // reads each file's Finder info, a round trip more an entry, and up to
        // ~15 beside `._` files (a NAS without Apple's SMB extensions).
        var failure: Error?
        guard let e = FileManager.default.enumerator(at: dir, includingPropertiesForKeys: scanKeys,
                                                     options: local ? [.skipsHiddenFiles, .skipsSubdirectoryDescendants]
                                                                    : [.skipsSubdirectoryDescendants],
                                                     errorHandler: { _, err in failure = failure ?? err; return true })
        else { throw CocoaError(.fileReadUnknown) }
        var files: [Clip] = []
        var dirs: [URL] = []
        var seen = 0
        for case let u as URL in e {
            if progress.stopped { break }
            seen += 1
            if !local, u.lastPathComponent.hasPrefix(".") { continue }
            guard let v = try? u.resourceValues(forKeys: Set(scanKeys)) else { continue }
            if v.isDirectory == true {
                if v.isSymbolicLink != true, !skippedFolders.contains(u.lastPathComponent),
                   (try? u.resourceValues(forKeys: [.isPackageKey]))?.isPackage != true { dirs.append(u) }
                continue
            }
            guard let kind = kind(u) else { continue }
            var facts = v
            if v.isSymbolicLink == true {
                // The link's target's size and dates (the session checks them).
                guard followLinks, let t = try? u.resolvingSymlinksInPath().resourceValues(forKeys: Set(scanKeys))
                else { continue }
                facts = t
            }
            guard facts.isRegularFile == true else { continue }
            files.append(Clip(url: u, size: Int64(facts.fileSize ?? 0),
                              modified: facts.contentModificationDate ?? .distantPast,
                              created: facts.creationDate ?? facts.contentModificationDate ?? .distantPast,
                              kind: kind, key: prefix + u.lastPathComponent))
            progress.found()
        }
        // The open folder itself unreadable is an error; a subfolder is skipped.
        if prefix.isEmpty, seen == 0, let failure { throw failure }
        out += files.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        guard subfolders else { return }
        for d in dirs.sorted(by: { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }) {
            try? walk(d, prefix: prefix + d.lastPathComponent + "/", subfolders: true, followLinks: followLinks,
                      local: local, progress: progress, into: &out)
        }
    }

    /// One file as it is now (after Apply rewrote or wrote it); nil if it is gone.
    static func clip(at url: URL, key: String) -> Clip? {
        var u = URL(fileURLWithPath: url.path)
        u.removeAllCachedResourceValues()
        guard let kind = kind(u), var v = try? u.resourceValues(forKeys: Set(scanKeys)) else { return nil }
        if v.isSymbolicLink == true, let t = try? u.resolvingSymlinksInPath().resourceValues(forKeys: Set(scanKeys)) { v = t }
        guard v.isRegularFile == true else { return nil }
        return Clip(url: u, size: Int64(v.fileSize ?? 0), modified: v.contentModificationDate ?? .distantPast,
                    created: v.creationDate ?? v.contentModificationDate ?? .distantPast, kind: kind, key: key)
    }

    /// Consecutive clips from one folder.
    static func sections(_ clips: [Clip]) -> [ClipSection] {
        var out: [ClipSection] = []
        var start = 0
        for i in clips.indices where i + 1 == clips.count || clips[i + 1].folderPath != clips[i].folderPath {
            out.append(ClipSection(path: clips[i].folderPath, range: start..<i + 1))
            start = i + 1
        }
        return out
    }
}

/// Staged deletes and crops survive a quit: one JSON per folder in
/// ~/Library/Application Support/<bundle ID>/sessions/, keyed by the path
/// under the folder (Clip.key; a file in the folder itself is its name) and
/// checked against size and mtime (a changed file loses its edits). `seeded`
/// is the bulkcut.json id whose proposals were staged (Manifest.swift), so
/// they are staged once, not on every open.
enum SessionStore {
    static let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        .appendingPathComponent(bundleID).appendingPathComponent("sessions", isDirectory: true)

    private struct File: Codable {
        var folder: String
        var saved: Date
        var clips: [String: Entry]
        var seeded: String?
    }
    private struct Entry: Codable {
        var size: Int64
        var mtime: Double
        var edit: ClipEdit
    }

    private static func url(for folder: URL) -> URL {
        let path = folder.standardizedFileURL.resolvingSymlinksInPath().path
        let hash = SHA256.hash(data: Data(path.utf8)).prefix(10).map { String(format: "%02x", $0) }.joined()
        return dir.appendingPathComponent(hash + ".json")
    }

    /// The staged edits, and the manifest id whose proposals they started from.
    static func load(folder: URL, clips: [Clip]) -> (edits: [String: ClipEdit], seeded: String?) {
        guard let data = try? Data(contentsOf: url(for: folder)),
              let file = try? JSONDecoder().decode(File.self, from: data) else { return ([:], nil) }
        var out: [String: ClipEdit] = [:]
        for c in clips {
            guard let e = file.clips[c.key], e.size == c.size,
                  abs(e.mtime - c.modified.timeIntervalSince1970) < 1, !e.edit.isEmpty else { continue }
            out[c.key] = e.edit
        }
        return (out, file.seeded)
    }

    static func save(folder: URL, clips: [Clip], edits: [String: ClipEdit], seeded: String? = nil) {
        var entries: [String: Entry] = [:]
        for c in clips {
            guard let e = edits[c.key], !e.isEmpty else { continue }
            entries[c.key] = Entry(size: c.size, mtime: c.modified.timeIntervalSince1970, edit: e)
        }
        let target = url(for: folder)
        // Kept while it remembers a seeded manifest, or its proposals would be staged again.
        if entries.isEmpty, seeded == nil { try? FileManager.default.removeItem(at: target); return }
        let file = File(folder: folder.path, saved: Date(), clips: entries, seeded: seeded)
        guard let data = try? JSONEncoder().encode(file) else { return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? data.write(to: target, options: .atomic)
    }
}

enum Format {
    /// "0:26", "12:03", "1:02:03".
    static func duration(_ s: Double) -> String {
        let t = Int(s.rounded())
        let h = t / 3600, m = (t / 60) % 60, sec = t % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, sec) : String(format: "%d:%02d", m, sec)
    }

    /// "0:03.1", "12:40.0": a time inside a clip, to a tenth.
    static func clock(_ s: Double) -> String {
        let m = Int(s) / 60
        return String(format: "%d:%04.1f", m, s - Double(m * 60))
    }

    static func bytes(_ n: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: n, countStyle: .file)
    }
}
