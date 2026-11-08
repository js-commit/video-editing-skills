import AppKit
import Foundation

/// Where the skills repo is, and how to run its Python scripts.
///
/// The app calls two of the repo's scripts: `tools/transcribe.py` (the
/// transcript pane) and `apps/edit-review/scripts/export_cuts.py`
/// (Review › Get Cuts from Resolve). It finds the repo, first match wins:
///
/// 1. `EDIT_REVIEW_REPO` in the environment (testing),
/// 2. the folder picked with Review › Set Skills Repo Folder… (remembered),
/// 3. the repo the app was built in (build.sh writes it into Info.plist),
/// 4. the bundle's own place: `<repo>/apps/edit-review/prebuilt/EditReview.app`
///    (or `build/`, the same depth).
enum RepoTools {
    static let repoDefaultsKey = "repoPath"

    static func candidates() -> [URL] {
        var out: [URL] = []
        if let env = ProcessInfo.processInfo.environment["EDIT_REVIEW_REPO"], !env.isEmpty {
            out.append(URL(fileURLWithPath: (env as NSString).expandingTildeInPath))
        }
        if let picked = UserDefaults.standard.string(forKey: repoDefaultsKey), !picked.isEmpty {
            out.append(URL(fileURLWithPath: picked))
        }
        if let built = Bundle.main.object(forInfoDictionaryKey: "EditReviewRepo") as? String, !built.isEmpty {
            out.append(URL(fileURLWithPath: built))
        }
        // <repo>/apps/edit-review/{prebuilt,build}/EditReview.app → <repo>
        var u = Bundle.main.bundleURL
        for _ in 0..<4 { u = u.deletingLastPathComponent() }
        out.append(u)
        return out
    }

    /// The repo folder: the first candidate that has `tools/` in it.
    static func repo() -> URL? {
        candidates().first { FileManager.default.fileExists(atPath: $0.appendingPathComponent("tools").path) }
    }

    /// `relative` inside the repo, if both exist.
    static func script(_ relative: String) -> URL? {
        guard let r = repo() else { return nil }
        let u = r.appendingPathComponent(relative)
        return FileManager.default.fileExists(atPath: u.path) ? u : nil
    }

    /// `python3 script args…` through a login shell, so `python3` is the one
    /// the user's terminal finds (Finder launches apps without the shell's
    /// PATH). The working directory is the repo.
    static func pythonProcess(script: URL, arguments: [String]) -> Process {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = ["-lc", "exec python3 \"$0\" \"$@\"", script.path] + arguments
        if let r = repo() { p.currentDirectoryURL = r }
        return p
    }

    /// Review › Set Skills Repo Folder…: pick the folder by hand.
    @MainActor
    static func pickRepo() -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Choose the video-editing skills repo folder (the one with tools/ and apps/ in it)"
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        guard FileManager.default.fileExists(atPath: url.appendingPathComponent("tools").path) else {
            NSSound.beep()
            return nil
        }
        UserDefaults.standard.set(url.path, forKey: repoDefaultsKey)
        return url
    }
}
