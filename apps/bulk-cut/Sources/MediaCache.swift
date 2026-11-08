import CryptoKit
import Foundation

/// The rebuildable per-video caches — waveform peaks and the poster
/// thumbnail — live in ~/Library/Caches/<bundle ID>/<hash of the
/// video's path>/, never next to the video. Each one checks the file's size
/// and mtime, so a changed file rebuilds it; a wiped cache costs a moment's
/// background rebuild on the next look. Folders not used for `maxAge` are
/// pruned at launch.
enum MediaCache {
    static let root = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        .appendingPathComponent(bundleID, isDirectory: true)
    static let maxAge: TimeInterval = 90 * 86_400

    static func dir(for video: URL) -> URL {
        let path = video.standardizedFileURL.resolvingSymlinksInPath().path
        let hash = SHA256.hash(data: Data(path.utf8)).prefix(10).map { String(format: "%02x", $0) }.joined()
        return root.appendingPathComponent(hash, isDirectory: true)
    }

    /// A cache file's contents, nil when it is missing or unreadable.
    static func load<T: Decodable>(_ type: T.Type, from url: URL) -> T? {
        (try? Data(contentsOf: url)).flatMap { try? PropertyListDecoder().decode(type, from: $0) }
    }

    /// Encode and write one cache file in the background, making its folder if need be.
    static func save<T: Encodable & Sendable>(_ value: T, to url: URL) {
        Task.detached(priority: .utility) {
            guard let data = try? PropertyListEncoder().encode(value) else { return }
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? data.write(to: url, options: .atomic)
        }
    }

    /// Mark a video's cache folder as used now (pruning goes by its mtime),
    /// with a `source.txt` naming the video so a folder can be told apart by hand.
    static func touch(_ dir: URL, video: URL) {
        let fm = FileManager.default
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let source = dir.appendingPathComponent("source.txt")
        if !fm.fileExists(atPath: source.path) {
            try? (video.standardizedFileURL.path + "\n").write(to: source, atomically: true, encoding: .utf8)
        }
        try? fm.setAttributes([.modificationDate: Date()], ofItemAtPath: dir.path)
    }

    /// Drop the caches of videos not opened for `maxAge`.
    static func prune() {
        let fm = FileManager.default
        guard let dirs = try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: [.contentModificationDateKey]) else { return }
        let cutoff = Date().addingTimeInterval(-maxAge)
        for d in dirs {
            let m = (try? d.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            if m < cutoff { try? fm.removeItem(at: d) }
        }
    }

    /// On a disk of this Mac — internal or an attached SSD — rather than a
    /// network share (SMB / NFS / AFP, e.g. a NAS). Only local files get
    /// their caches built on open; a network file waits for a click, because
    /// every thumbnail is a read over the network.
    static func isLocal(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.volumeIsLocalKey]).volumeIsLocal) ?? false
    }
}
