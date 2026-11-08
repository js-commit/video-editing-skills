import AppKit
import AVFoundation
import SwiftUI
import os

/// Every key press and what became of it, at debug level (not kept by
/// default): `/usr/bin/log stream --level debug --predicate 'subsystem == "<bundle ID>"'`.
private let keyLog = Logger(subsystem: bundleID, category: "keys")

/// A folder being read: what the list shows while a slow one (a network
/// share) is listed.
struct ScanState {
    let folder: URL
    var files = 0
    var folders = 0
    /// The subfolder being read, "" for the folder itself.
    var current = ""
}

/// The photo on screen, decoded.
struct ShownPhoto {
    let url: URL
    let image: CGImage
}

/// The open folder, the clip on screen, the staged edits, and the keyboard.
@MainActor
final class AppModel: ObservableObject {
    let player = PlayerModel()
    let keymap = Keymap.shared
    let timeline = TimelineState()

    @Published private(set) var folder: URL?
    /// The folder's videos and photos, then each subfolder's (Library.scan).
    @Published private(set) var clips: [Clip] = [] {
        didSet {
            sections = Library.sections(clips)
            byKey = Dictionary(clips.map { ($0.key, $0) }, uniquingKeysWith: { a, _ in a })
            picked = []
        }
    }
    /// `clips` by folder, for the list's headers.
    @Published private(set) var sections: [ClipSection] = []
    private(set) var byKey: [String: Clip] = [:]
    /// Header facts per file, filled in the background after a folder opens.
    @Published private(set) var infos: [URL: VideoInfo] = [:]
    @Published private(set) var photoInfos: [URL: PhotoInfo] = [:]
    @Published private(set) var selectedID: URL?
    /// Several clips selected (⌘A, ⌘-click, ⇧-click), `selectedID` (the one
    /// on screen) among them: ⌫, rotate, ⌘C and the clears act on them all.
    /// Empty while only one is selected (a set of one empties itself).
    @Published private(set) var picked: Set<URL> = [] { didSet { if picked.count == 1 { picked = [] } } }
    /// Where a ⇧-click range starts.
    private var anchor: URL?
    /// The selected photo once decoded (PhotoStore); until then its thumbnail stands in.
    @Published private(set) var photo: ShownPhoto?
    /// What the folder's bulkcut.json says about each clip, by Clip.key (Annotations.swift).
    @Published private(set) var notes: [String: ClipNotes] = [:] { didSet { syncPlayback() } }
    /// The notes panel over the video (⌘I).
    @Published var showNotes: Bool { didSet { UserDefaults.standard.set(showNotes, forKey: "showNotes") } }
    /// A scan under way (opening, reloading); Stop shows what it has found.
    @Published private(set) var scanning: ScanState?
    private var scanProgress: ScanProgress?
    /// The open folder is on this Mac's own disks. If not (a network share),
    /// file headers are read as their rows come into view, not all up front.
    private(set) var folderIsLocal = true
    private var infoInFlight: Set<URL> = []
    private let infoGate = Gate(limit: 4)
    /// Scan subfolders too, each under its own header in the list.
    @Published var subfolders: Bool {
        didSet {
            guard subfolders != oldValue else { return }
            UserDefaults.standard.set(subfolders, forKey: "subfolders")
            reload()
        }
    }
    /// Staged edits by Clip.key. A clip with none has no entry.
    @Published private(set) var edits: [String: ClipEdit] = [:] { didSet { syncPlayback() } }
    /// Selecting a clip starts it playing. SPACE turns this off (pausing) and on (playing).
    @Published private(set) var autoplay = true
    /// Play only a clip's coloured stretches - its ranges, whoever made them,
    /// and what the library already holds - skipping the grey. A clip with
    /// none plays whole.
    @Published private(set) var sectionsOnly: Bool {
        didSet { UserDefaults.standard.set(sectionsOnly, forKey: "sectionsOnly"); syncPlayback() }
    }
    /// At the end (of the last section, or of the clip), start over.
    @Published private(set) var loop: Bool {
        didSet { UserDefaults.standard.set(loop, forKey: "loop"); syncPlayback() }
    }
    @Published private(set) var status = ""
    @Published var showApply = false
    /// The open folder's bulkcut.json, if it has one (Manifest.swift).
    private(set) var manifest: Manifest?
    /// The manifest id whose proposals this folder's session was seeded with.
    private var seeded: String?
    /// Set when the open folder is a review folder (ReviewFolder.swift):
    /// Apply becomes the manifest's send (or Done), nothing in the folder is
    /// ever trashed or cut, and every change goes to bulkcut-review.json.
    @Published private(set) var reviewFolder: ReviewFolder?
    @Published var showSend = false
    /// A review folder's focus (Focus.swift): everything, one sequence end
    /// to end, or just the picks.
    @Published private(set) var focus: Focus = .everything { didSet { syncPlayback() } }
    /// The focus's files in the order it plays them (Clip.keys); nil for
    /// everything. Fixed when the focus is chosen, so a file whose last pick
    /// goes stays in the list.
    @Published private(set) var focusKeys: [String]?
    /// Where the clip about to load starts: focused playback moving on to
    /// another file's stretch.
    private var startAt: (url: URL, time: Double)?
    /// Files the user asked to trash while they still hold ranges: the
    /// ranges win until the user confirms clearing them (ContentView's dialog).
    @Published var confirmTrash: [Clip]?
    /// ⌘S under way: Apply without the sheet. Keys and clicks wait for it.
    @Published private(set) var applying = false
    /// Bumped by each Apply: list rows fetch their thumbnails again (a file
    /// rewritten in place can keep its size and dates).
    @Published private(set) var applyCount = 0
    /// A ⌘S Apply that had problems, for the sheet to show.
    var saveResult: ApplyResult?
    @Published var showShortcuts = false
    @Published private(set) var recents: [URL] = []
    /// Row thumbnail width in points (⌘= / ⌘-).
    @Published var thumbWidth: Double { didSet { UserDefaults.standard.set(thumbWidth, forKey: "thumbWidth") } }
    static let thumbWidths: [Double] = [64, 96, 128, 160, 200, 256, 320, 400, 480]

    weak var window: NSWindow?
    private var keyMonitor: Any?
    private var scrollMonitor: Any?
    /// Where each clip was left, so going back to one resumes there.
    private var positions: [URL: Double] = [:]
    /// One undo (or redo) step: the edits it puts back, only for the clips
    /// it changed (nil: none), and the clip that was selected.
    private struct Snapshot { var edits: [String: ClipEdit?]; var selected: URL? }
    private var undoStack: [Snapshot] = []
    private var redoStack: [Snapshot] = []
    private var loadTask: Task<Void, Never>?
    private var scanTask: Task<Void, Never>?
    private var lastSelect = Date.distantPast
    private var infoTask: Task<Void, Never>?
    private var notesTask: Task<Void, Never>?
    private var saveTask: Task<Void, Never>?
    private var statusTask: Task<Void, Never>?

    init() {
        let d = UserDefaults.standard
        thumbWidth = d.object(forKey: "thumbWidth") as? Double ?? 160
        showNotes = d.object(forKey: "showNotes") as? Bool ?? true
        subfolders = d.object(forKey: "subfolders") as? Bool ?? true
        sectionsOnly = d.object(forKey: "sectionsOnly") as? Bool ?? true
        loop = d.bool(forKey: "loop")
        recents = (d.stringArray(forKey: "recentFolders") ?? []).map { URL(fileURLWithPath: $0) }
            .filter { FileManager.default.fileExists(atPath: $0.path) }
        player.onSectionEnd = { [weak self] in self?.focusSectionEnded($0) }
    }

    // MARK: derived

    var selectedIndex: Int? { clips.firstIndex { $0.id == selectedID } }
    /// The list as shown: the focus's files, or every clip.
    var visibleClips: [Clip] { focusKeys.map { $0.compactMap { byKey[$0] } } ?? clips }
    var visibleIndex: Int? { visibleClips.firstIndex { $0.id == selectedID } }
    var selected: Clip? { selectedIndex.map { clips[$0] } }
    /// What the selection keys act on: the picked clips in list order, or the selected one.
    var selection: [Clip] { picked.isEmpty ? (selected.map { [$0] } ?? []) : clips.filter { picked.contains($0.id) } }
    func edit(_ clip: Clip) -> ClipEdit { edits[clip.key] ?? ClipEdit() }
    var selectedEdit: ClipEdit { selected.map(edit) ?? ClipEdit() }
    /// The selected clip is the one in the player (crop keys need its frames).
    var selectedLoaded: Bool { selected != nil && player.loadedURL == selected?.url }
    var videoCount: Int { clips.count { !$0.isPhoto } }
    var photoCount: Int { clips.count { $0.isPhoto } }
    private func isPhoto(_ key: String) -> Bool { byKey[key]?.isPhoto == true }
    var deleteCount: Int { edits.values.filter(\.deleted).count }
    /// Videos cut down in time, and photos cropped.
    var cropCount: Int { edits.count { k, e in !e.deleted && (!e.ranges.isEmpty || (e.zoom != nil && isPhoto(k))) } }
    var turnCount: Int { edits.values.filter { !$0.deleted && $0.turns != 0 }.count }
    var zoomCount: Int { edits.count { k, e in !e.deleted && e.zoom != nil && !isPhoto(k) } }
    var hasChanges: Bool { deleteCount + cropCount + turnCount + zoomCount > 0 }
    /// The selected clip's picture as shown, in pixels: a video's own
    /// rotation applied, a photo's orientation, and staged turns. The frame
    /// a zoom or crop is drawn in.
    var selectedDisplay: CGSize? {
        guard let c = selected else { return nil }
        let t = edit(c).turns
        guard let s = c.isPhoto ? photoInfos[c.url]?.size(turns: t) : infos[c.url]?.size(turns: t),
              s.width > 0, s.height > 0 else { return nil }
        return s
    }
    /// The selected photo's decoded picture, once it is.
    var selectedPhoto: CGImage? {
        guard let c = selected, c.isPhoto else { return nil }
        return photo?.url == c.url ? photo?.image : nil
    }
    var canUndo: Bool { !undoStack.isEmpty }
    var canRedo: Bool { !redoStack.isEmpty }

    // MARK: status line

    func flash(_ text: String) {
        status = text
        statusTask?.cancel()
        statusTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled else { return }
            self?.status = ""
        }
    }

    // MARK: opening

    func openPanel() {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = true
        p.allowsMultipleSelection = false
        p.allowedContentTypes = [.folder, .movie, .image]
        p.prompt = "Open"
        p.message = "Choose a folder of videos and photos (or one file, to open its folder)"
        if p.runModal() == .OK, let u = p.url { open(url: u) }
    }

    /// A folder opens as is; a video or photo opens its folder with it selected.
    func open(url: URL) {
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir) else {
            flash("Not found: \(url.path)")
            return
        }
        if isDir.boolValue { openFolder(url, selecting: nil) }
        else { openFolder(url.deletingLastPathComponent(), selecting: url) }
    }

    /// `BulkCut <folder>`; AppKit may also have passed it on as an open request.
    func openFromArguments() {
        if folder == nil, let p = CommandLine.arguments.dropFirst().first(where: { !$0.hasPrefix("-") }) {
            open(url: URL(fileURLWithPath: p))
        }
    }

    func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let p = providers.first else { return false }
        _ = p.loadObject(ofClass: URL.self) { [weak self] url, _ in
            guard let url else { return }
            Task { @MainActor in self?.open(url: url) }
        }
        return true
    }

    /// Read `dir` off the main thread, publishing progress to `scanning` as
    /// it goes. nil when cancelled (another folder opened). `stopped`: Stop
    /// was pressed and `list` is what had been found.
    private func scanWithProgress(_ dir: URL) async -> (result: Result<[Clip], Error>, stopped: Bool)? {
        scanProgress?.stop()
        let progress = ScanProgress()
        scanProgress = progress
        scanning = ScanState(folder: dir)
        let ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(250))
                guard let self, self.scanProgress === progress else { return }
                let p = progress.snapshot
                self.scanning = ScanState(folder: dir, files: p.files, folders: p.folders, current: p.current)
            }
        }
        let sub = subfolders
        let work = Task.detached(priority: .userInitiated) {
            Result { try Library.scan(dir, subfolders: sub, followLinks: Manifest.isReview(dir), progress: progress) }
        }
        let result = await withTaskCancellationHandler { await work.value } onCancel: { progress.stop() }
        ticker.cancel()
        let stopped = progress.stopped
        if scanProgress === progress {
            scanProgress = nil
            scanning = nil
        }
        return Task.isCancelled ? nil : (result, stopped)
    }

    /// Stop reading the folder and show what has been found so far.
    func stopScan() {
        scanProgress?.stop()
    }

    func openFolder(_ dir: URL, selecting: URL?) {
        guard !applying else { return }
        saveNow()
        scanTask?.cancel()
        scanTask = Task { [weak self] in
            guard let self, let (result, stopped) = await self.scanWithProgress(dir) else { return }
            switch result {
            case .failure(let error):
                self.flash("Can't read \(dir.lastPathComponent): \(error.localizedDescription)")
            case .success(let list):
                self.show(dir, list, selecting: selecting, stopped: stopped)
            }
        }
    }

    private func show(_ dir: URL, _ list: [Clip], selecting: URL?, stopped: Bool) {
        player.unload()
        folder = dir
        manifest = Manifest.load(dir)
        reviewFolder = ReviewFolder(manifest, folder: dir)
        focus = .everything
        focusKeys = nil
        startAt = nil
        folderIsLocal = MediaCache.isLocal(dir)
        clips = list
        infos = [:]
        photoInfos = [:]
        infoInFlight = []
        photo = nil
        positions = [:]
        undoStack = []
        redoStack = []
        edits = restoredEdits(dir, list)
        DebugLog.write("Open \(dir.path)\(subfolders ? " and subfolders" : "")\(folderIsLocal ? "" : " (network)")\(stopped ? ", stopped early" : ""): \(list.count) files in \(sections.count) folders, staged edits restored:\n\(DebugLog.staged(edits))")
        noteRecent(dir)
        loadInfos()
        loadNotes()
        let want = selecting?.standardizedFileURL
        let first = want.flatMap { w in list.first { $0.url.standardizedFileURL == w } } ?? list.first
        selectedID = nil
        select(first?.id)
        let restored = edits.isEmpty ? "" : " · \(edits.count) staged edits restored"
        let folders = sections.count > 1 ? " in \(sections.count) folders" : ""
        if stopped {
            flash("Stopped reading: \(countLabel) found so far\(folders) · ⌘R reads it all")
        } else {
            flash(list.isEmpty ? "No videos or photos in \(dir.lastPathComponent)\(subfolders ? " or its subfolders" : "")"
                               : "\(countLabel)\(folders)\(restored)")
        }
    }

    /// The folder's saved session; the first time a manifest id is seen, its
    /// proposals replace the staged edits of the files it lists (saved at once,
    /// so a review folder's bulkcut-review.json exists from the first open).
    /// In a review folder, ranges as the review file reports them: shrunk ones
    /// gone, touching ones joined.
    private func restoredEdits(_ dir: URL, _ list: [Clip]) -> [String: ClipEdit] {
        let saved = SessionStore.load(folder: dir, clips: list)
        var e = saved.edits
        seeded = saved.seeded
        if let m = manifest, m.id != saved.seeded {
            for c in list where m.entry(c) != nil { e[c.key] = m.proposedEdit(c) }
            seeded = m.id
            DebugLog.write("Staged the proposals of \(Manifest.fileName) (id \(m.id))")
            SessionStore.save(folder: dir, clips: list, edits: e, seeded: seeded)
            if m.isReview { ReviewWriter.write(folder: dir, manifest: m, clips: list, edits: e) }
        }
        guard reviewFolder != nil else { return e }
        return e.compactMapValues { x in
            var x = x
            x.ranges = RangeOps.tidyDrag(x.ranges)
            return x.isEmpty ? nil : x
        }
    }

    /// "12 videos · 40 photos".
    var countLabel: String {
        let v = videoCount, p = photoCount
        var parts: [String] = []
        if v > 0 || p == 0 { parts.append("\(v) video" + (v == 1 ? "" : "s")) }
        if p > 0 { parts.append("\(p) photo" + (p == 1 ? "" : "s")) }
        return parts.joined(separator: " · ")
    }

    /// Re-read the folder (new files, files changed elsewhere), keeping edits
    /// of files that did not change.
    func reload() {
        guard let dir = folder, !applying else { return }
        let keep = selectedID
        saveNow()
        scanTask?.cancel()
        scanTask = Task { [weak self] in
            guard let self, let (result, stopped) = await self.scanWithProgress(dir), case .success(let list) = result,
                  self.folder == dir else { return }
            self.player.unload()
            self.clips = list
            self.manifest = Manifest.load(dir)
            self.reviewFolder = ReviewFolder(self.manifest, folder: dir)
            self.edits = self.restoredEdits(dir, list)
            self.refreshFocus()
            self.photo = nil
            // Headers again: a file may have changed.
            self.infos = [:]
            self.photoInfos = [:]
            self.infoInFlight = []
            DebugLog.write("Reload \(dir.path)\(self.subfolders ? " and subfolders" : "")\(stopped ? ", stopped early" : ""): \(list.count) files, staged:\n\(DebugLog.staged(self.edits))")
            self.loadInfos()
            self.loadNotes()
            self.selectedID = nil
            self.select(list.first { $0.id == keep }?.id ?? list.first?.id)
            self.flash((stopped ? "Stopped reading: " : "") + self.countLabel
                       + (self.sections.count > 1 ? " in \(self.sections.count) folders" : "") + (stopped ? " found so far" : ""))
        }
    }

    private func noteRecent(_ dir: URL) {
        recents.removeAll { $0.standardizedFileURL == dir.standardizedFileURL }
        recents.insert(dir, at: 0)
        if recents.count > 10 { recents.removeLast(recents.count - 10) }
        UserDefaults.standard.set(recents.map(\.path), forKey: "recentFolders")
    }

    func clearRecents() {
        recents = []
        UserDefaults.standard.removeObject(forKey: "recentFolders")
    }

    /// Header facts for every file not yet read, eight at a time, published
    /// in batches. Not on a network share: there each file costs a few round
    /// trips, so rows ask for theirs as they come into view (loadInfo).
    private func loadInfos() {
        infoTask?.cancel()
        guard folderIsLocal else { return }
        let list = clips.filter { infos[$0.url] == nil && photoInfos[$0.url] == nil }
        infoTask = Task { [weak self] in
            for start in stride(from: 0, to: list.count, by: 8) {
                let chunk = list[start..<min(start + 8, list.count)]
                let got = await withTaskGroup(of: (URL, VideoInfo?, PhotoInfo?).self) { g in
                    for c in chunk {
                        g.addTask {
                            c.isPhoto ? (c.url, nil, Photos.probe(c.url)) : (c.url, try? await PlayerModel.probe(c.url), nil)
                        }
                    }
                    var videos: [URL: VideoInfo] = [:], photos: [URL: PhotoInfo] = [:]
                    for await (u, v, p) in g { videos[u] = v; photos[u] = p }
                    return (videos, photos)
                }
                guard !Task.isCancelled, let self else { return }
                if !got.0.isEmpty { self.infos.merge(got.0) { old, _ in old } }
                if !got.1.isEmpty { self.photoInfos.merge(got.1) { _, new in new } }
            }
        }
    }

    /// A row came into view: read its file's header, if the folder is on
    /// a network share and it hasn't been. Dropped if the row scrolls away
    /// before its turn.
    func loadInfo(_ clip: Clip) async {
        guard !folderIsLocal, infos[clip.url] == nil, photoInfos[clip.url] == nil,
              infoInFlight.insert(clip.url).inserted else { return }
        defer { infoInFlight.remove(clip.url) }
        guard await infoGate.enter() else { return }
        guard !Task.isCancelled else { await infoGate.leave(); return }
        let url = clip.url, isPhoto = clip.isPhoto
        let got: (VideoInfo?, PhotoInfo?) = await Task.detached(priority: .utility) {
            isPhoto ? (nil, Photos.probe(url)) : (try? await PlayerModel.probe(url), nil)
        }.value
        await infoGate.leave()
        guard byKey[clip.key]?.url == url else { return }
        if let v = got.0 { infos[url] = v }
        if let p = got.1 { photoInfos[url] = p }
    }

    /// The manifest's notes on the videos (nothing to read for a folder without one).
    private func loadNotes() {
        notes = Annotations.notes(manifest, clips: clips.filter { !$0.isPhoto })
    }

    // MARK: selection and playback

    func select(_ id: URL?) {
        guard id != selectedID else { return }
        if let cur = selected { leave(cur) }
        if let s = startAt, s.url != id { startAt = nil }
        selectedID = id
        player.pause()          // the old clip stops now; the new one loads next
        // A photo already decoded (a neighbour, fetched ahead) shows at once.
        if let c = selected, c.isPhoto, photo?.url != c.url, let img = PhotoStore.shared.cached(c.url) {
            photo = ShownPhoto(url: c.url, image: img)
        }
        scheduleLoad()
    }

    /// A click in the list: selects that clip alone; ⌘ adds or takes it
    /// away, ⇧ selects everything from the last plain click to it.
    func click(_ clip: Clip) {
        guard !applying else { return }
        let mods = NSEvent.modifierFlags
        if mods.contains(.command) {
            var p = picked.isEmpty ? Set([selectedID].compactMap { $0 }) : picked
            if p.remove(clip.id) == nil {
                p.insert(clip.id)
                select(clip.id)
            } else if clip.id == selectedID, let next = clips.first(where: { p.contains($0.id) }) {
                select(next.id)
            }
            picked = p
            anchor = clip.id
        } else if mods.contains(.shift), let from = visibleClips.firstIndex(where: { $0.id == anchor ?? selectedID }),
                  let to = visibleClips.firstIndex(of: clip) {
            picked = Set(visibleClips[min(from, to)...max(from, to)].map(\.id))
            select(clip.id)
        } else {
            picked = []
            anchor = clip.id
            select(clip.id)
        }
        if focus != .everything { DebugLog.write("Focus \(focusTitle): click → \(clip.key)") }
        if !picked.isEmpty { flash("\(picked.count) selected") }
    }

    func selectAll() {
        let list = visibleClips
        guard list.count > 1 else { return }
        picked = Set(list.map(\.id))
        if selectedID == nil { select(list.first?.id) }
        flash("All \(list.count) selected · \(keymap.label(.toggleDelete)) stages them for delete · a click selects one again")
    }

    /// ↑ / ↓: through the list as shown (a focus's files, in the order it plays them).
    func moveSelection(_ delta: Int) {
        let list = visibleClips
        guard !list.isEmpty else { return }
        let i = min(max((visibleIndex ?? (delta > 0 ? -1 : list.count)) + delta, 0), list.count - 1)
        picked = []
        anchor = list[i].id
        select(list[i].id)
        if focus != .everything { DebugLog.write("Focus \(focusTitle): \(delta > 0 ? "↓" : "↑") → \(list[i].key)") }
    }

    private func leave(_ clip: Clip) {
        // Stopped at the end of its sections: next time it starts at the first.
        if player.loadedURL == clip.url { positions[clip.url] = player.atSectionsEnd ? nil : player.currentSeconds }
        // An open range is settled when its clip is left.
        if let e = edits[clip.key], e.ranges.contains(where: { $0.open != nil }) {
            edits[clip.key]?.ranges = RangeOps.settle(e.ranges)
            scheduleSave()
        }
    }

    /// The first selection loads at once; one inside a burst (↓ held down)
    /// waits until the burst pauses, so a run through the list does not open
    /// every file on the way.
    private func scheduleLoad() {
        loadTask?.cancel()
        let burst = Date().timeIntervalSince(lastSelect) < 0.15
        lastSelect = Date()
        loadTask = Task { [weak self] in
            if burst { try? await Task.sleep(for: .milliseconds(120)) }
            guard !Task.isCancelled else { return }
            await self?.loadSelected()
        }
    }

    private func loadSelected() async {
        guard let clip = selected else { player.unload(); return }
        if clip.isPhoto { await loadPhoto(clip); return }
        do {
            let info = try await player.load(url: clip.url)
            guard selectedID == clip.id else { return }
            infos[clip.url] = info
            timeline.reset()
            syncPlayback()
            // Where focused playback goes on in it; else where it was left, if
            // that is in a section; else the first section.
            let secs = player.sections
            let start = startAt?.url == clip.url ? startAt?.time : nil
            startAt = nil
            if let start {
                player.seek(to: start)
            } else if let p = positions[clip.url], p > 0, p < info.duration - 0.1, secs.isEmpty || secs.contains(where: { $0.contains(p) }) {
                player.seek(to: p)
            } else if let first = secs.first {
                player.seek(to: first.lowerBound)
            }
            if autoplay { player.play() }
        } catch is CancellationError {
        } catch {
            guard selectedID == clip.id else { return }
            flash("Can't play \(clip.name): \(error.localizedDescription)")
        }
    }

    private func loadPhoto(_ clip: Clip) async {
        player.unload()
        // Its header first, if the background pass has not got to it: R and the crop need it.
        if photoInfos[clip.url] == nil {
            let url = clip.url
            if let i = await Task.detached(priority: .userInitiated, operation: { Photos.probe(url) }).value {
                photoInfos[url] = i
            }
        }
        if photo?.url != clip.url {
            guard let img = await PhotoStore.shared.image(for: clip.url) else {
                if selectedID == clip.id { flash("Can't read \(clip.name)") }
                return
            }
            guard selectedID == clip.id else { return }
            photo = ShownPhoto(url: clip.url, image: img)
        }
        // The next two photos down and the one above, for ↓ / ↑.
        guard let i = selectedIndex else { return }
        let around = [i + 1, i + 2, i - 1].filter { clips.indices.contains($0) }.map { clips[$0] }.filter(\.isPhoto)
        PhotoStore.shared.prefetch(around.map(\.url))
    }

    func togglePlay() {
        if selected?.isPhoto == true {
            autoplay.toggle()
            flash(autoplay ? "Autoplay on (videos play when selected)" : "Autoplay off")
            return
        }
        if player.isPlaying {
            player.pause()
            autoplay = false
            flash("Paused · autoplay off")
        } else {
            autoplay = true
            // Stopped after the focus's last stretch: again from its first, in whichever file.
            if focus != .everything, sectionsOnly, player.atSectionsEnd, let first = focusPlan.first {
                play(from: first)
                flash("Playing \(focusTitle) from the top · autoplay on")
                return
            }
            player.play()
            flash("Playing · autoplay on")
        }
    }

    /// The stretches sections-only playback plays: every range (any colour)
    /// and every stretch the library holds, merged; a gap under 0.1 s is not
    /// worth a jump.
    func sections(_ clip: Clip) -> [ClosedRange<Double>] {
        let e = edit(clip)
        let spans = (e.deleted ? [] : RangeOps.tidy(e.ranges).map { ($0.start, $0.end) })
            + (notes[clip.key]?.taken ?? []).map { ($0.start, $0.end) }
        var out: [ClosedRange<Double>] = []
        for (a, b) in spans.sorted(by: { $0.0 < $1.0 }) where b - a >= RangeOps.minLength {
            if let last = out.last, a <= last.upperBound + 0.1 {
                out[out.count - 1] = last.lowerBound...max(last.upperBound, b)
            } else {
                out.append(a...b)
            }
        }
        return out
    }

    /// Hand the player the selected clip's sections (none when sections-only
    /// is off) and the loop setting.
    /// With a focus, its stretches of the clip in the order they play, and the
    /// end of each handed to focusSectionEnded.
    private func syncPlayback() {
        guard let c = selected, !c.isPhoto, selectedLoaded else { return }
        if sectionsOnly, focus != .everything {
            player.setPlayback(sections: focusPlan.filter { $0.key == c.key }.map(\.range), loop: loop, ordered: true)
        } else {
            player.setPlayback(sections: sectionsOnly ? sections(c) : [], loop: loop)
        }
    }

    func toggleSectionsOnly() {
        sectionsOnly.toggle()
        let focused = focus != .everything
        let none = selected.map { c in !c.isPhoto && (focused ? !focusPlan.contains { $0.key == c.key } : sections(c).isEmpty) } ?? false
        flash(sectionsOnly ? (focused ? "Sections only: plays \(focusTitle) in order and skips the rest"
                                      : "Sections only: plays the coloured ranges and skips the grey")
                             + (none ? " (this clip has none: it plays whole)" : "")
                           : "Whole clips: the grey plays too")
    }

    func toggleLoop() {
        loop.toggle()
        flash(loop ? "Loop on: at the end it starts over" + (sectionsOnly ? " from the first section" : "")
                   : "Loop off: it stops at the end")
    }

    // MARK: focus (review folders)

    /// The folder's videos as the focus reads them.
    private var focusFiles: [FocusFile] {
        clips.filter { !$0.isPhoto }.map { c in
            let e = edit(c)
            return FocusFile(key: c.key, name: c.name, ranges: e.deleted ? [] : e.ranges)
        }
    }

    /// What focused sections-only playback plays, in order; empty for everything.
    var focusPlan: [FocusStep] { reviewFolder?.plan(focus, files: focusFiles) ?? [] }

    var focusTitle: String { reviewFolder?.title(focus) ?? "Everything" }

    /// Is this range of `clip` in the focus? With none, every range is.
    func inFocus(_ r: KeepRange, _ clip: Clip) -> Bool { reviewFolder?.contains(focus, r, file: clip.name) ?? true }

    /// "beats 1–3, 9 · 1 removed", for the clip's row in a focused list.
    func focusNote(_ clip: Clip) -> String? {
        guard let reviewFolder, focus != .everything, !clip.isPhoto else { return nil }
        let e = edit(clip)
        return reviewFolder.note(focus, FocusFile(key: clip.key, name: clip.name, ranges: e.deleted ? [] : e.ranges))
    }

    /// Show and play only `f`: the list narrows to its files, in the order
    /// it plays them, and it starts at its first stretch.
    func setFocus(_ f: Focus, from source: String = "Focus menu") {
        guard let reviewFolder else { flash("Focus is for review folders: one sequence, or the picks, at a time"); return }
        guard reviewFolder.focuses.contains(f), !applying else { return }
        focus = f
        picked = []
        focusKeys = f == .everything ? nil : reviewFolder.files(f, focusFiles)
        let plan = focusPlan
        let files = focusKeys?.count ?? 0
        DebugLog.write("\(source) → focus \(reviewFolder.title(f))" + (f == .everything ? "" : ", \(files) files, in play order: "
            + plan.map { "\($0.key) \(String(format: "%.3f–%.3f", $0.range.lowerBound, $0.range.upperBound))" }.joined(separator: ", ")))
        if let first = plan.first {
            play(from: first)
        } else if let keys = focusKeys, selected.map({ !keys.contains($0.key) }) ?? true, let k = keys.first {
            select(byKey[k]?.id)
        }
        let next = "\(keymap.label(.focusNext)) next focus"
        switch f {
        case .everything:
            flash("Everything: every clip and every coloured range · \(next)")
        case .sequence:
            flash("\(reviewFolder.title(f)): " + (plan.isEmpty ? "no clips left" : "\(plan.count) stretch\(plan.count == 1 ? "" : "es") in \(files) file\(files == 1 ? "" : "s"), in beat order")
                  + (sectionsOnly ? "" : " · sections only is off (\(keymap.label(.sectionsOnly)))") + " · \(next)")
        case .picks:
            flash("Picks only: " + (plan.isEmpty ? "no picks left" : "\(plan.count) in \(files) file\(files == 1 ? "" : "s")") + " · \(next)")
        }
    }

    /// F / ⇧F: Everything, each sequence, Picks only, round again.
    func cycleFocus(_ step: Int, from source: String = "Clip menu") {
        guard let reviewFolder else { flash("Focus is for review folders: one sequence, or the picks, at a time"); return }
        let all = reviewFolder.focuses
        let i = all.firstIndex(of: focus) ?? 0
        setFocus(all[((i + step) % all.count + all.count) % all.count], from: source)
    }

    /// After the list was read again: the focus's files again, or everything
    /// if its sequence (or the review folder) is gone.
    private func refreshFocus() {
        guard let reviewFolder, focus != .everything, reviewFolder.focuses.contains(focus) else {
            if focus != .everything { focus = .everything }
            focusKeys = nil
            return
        }
        focusKeys = reviewFolder.files(focus, focusFiles)
    }

    /// Start at the focus's `step`: in the clip on screen, or once its own
    /// clip loads. It plays if autoplay is on (it is, while playing).
    private func play(from step: FocusStep) {
        guard let clip = byKey[step.key] else { return }
        if clip.id == selectedID, selectedLoaded {
            player.seek(to: step.range.lowerBound)
            if autoplay { player.play() }
            return
        }
        let from = selected
        startAt = (clip.url, step.range.lowerBound)
        picked = []
        anchor = clip.id
        select(clip.id)
        if let from, from.id != clip.id { positions[from.url] = nil }     // ↑ / ↓ back to it: its first stretch
    }

    /// Focused playback reached the end of `ended`, a stretch of the clip on
    /// screen: on to the plan's next one, in this file or the next; after the
    /// last, back to the first with loop on, else stop on its last frame.
    private func focusSectionEnded(_ ended: ClosedRange<Double>) {
        guard let c = selected else { return }
        let plan = focusPlan
        guard let i = plan.firstIndex(where: { $0.key == c.key && $0.range == ended }) else { return }
        let at = { (t: Double) in String(format: "%.2f s", t) }
        if i + 1 < plan.count {
            let next = plan[i + 1]
            if next.key != c.key {
                DebugLog.write("Focus \(focusTitle): \(c.key) done at \(at(ended.upperBound)), on to \(next.key) at \(at(next.range.lowerBound))")
            }
            play(from: next)
        } else if loop, let first = plan.first {
            DebugLog.write("Focus \(focusTitle): last stretch done (\(c.key) at \(at(ended.upperBound))), loop: back to \(first.key) at \(at(first.range.lowerBound))")
            play(from: first)
        } else {
            DebugLog.write("Focus \(focusTitle): last stretch done (\(c.key) at \(at(ended.upperBound))), stopped")
            player.stop(atEndOf: ended)
            flash("End of \(focusTitle) · \(keymap.label(.playPause)) plays it again from the top")
        }
    }

    // MARK: edits

    /// Change clips' edits as one undo step.
    private func mutate(_ list: [Clip], _ change: (inout ClipEdit) -> Void) {
        guard !applying, !list.isEmpty else { return }
        var after: [String: ClipEdit?] = [:]
        for clip in list {
            var e = edit(clip)
            change(&e)
            if e != edit(clip) { after.updateValue(e.isEmpty ? nil : e, forKey: clip.key) }
        }
        guard !after.isEmpty else { DebugLog.write("  \(subject(list)): no change"); return }
        pushUndo(after.keys)
        DebugLog.write(Self.changes(from: undoStack.last?.edits ?? [:], to: after))
        set(after)
        scheduleSave()
    }

    /// Give these clips these edits (nil: none), as one change to `edits`.
    private func set(_ change: [String: ClipEdit?]) {
        var e = edits
        for (k, v) in change { e[k] = v }
        edits = e
    }

    /// These clips' edits as they are now.
    private func current(_ keys: some Sequence<String>) -> [String: ClipEdit?] {
        Dictionary(uniqueKeysWithValues: keys.map { ($0, edits[$0]) })
    }

    private static func changes(from a: [String: ClipEdit?], to b: [String: ClipEdit?]) -> String {
        DebugLog.changes(from: a.compactMapValues { $0 }, to: b.compactMapValues { $0 })
    }

    private func mutate(_ clip: Clip, _ change: (inout ClipEdit) -> Void) { mutate([clip], change) }

    /// "IMG_1.mov", or "12 clips": what a status line says was changed.
    private func subject(_ list: [Clip]) -> String { list.count == 1 ? list[0].name : "\(list.count) clips" }

    /// Remember these clips' edits before they change.
    private func pushUndo(_ keys: some Sequence<String>) {
        undoStack.append(Snapshot(edits: current(keys), selected: selectedID))
        if undoStack.count > 300 { undoStack.removeFirst() }
        redoStack = []
    }

    func undo() {
        guard let s = undoStack.popLast() else { flash("Nothing to undo"); return }
        let now = current(s.edits.keys)
        redoStack.append(Snapshot(edits: now, selected: selectedID))
        DebugLog.write("Undo:\n\(Self.changes(from: now, to: s.edits))")
        restore(s)
        flash("Undone")
    }

    func redo() {
        guard let s = redoStack.popLast() else { flash("Nothing to redo"); return }
        let now = current(s.edits.keys)
        undoStack.append(Snapshot(edits: now, selected: selectedID))
        DebugLog.write("Redo:\n\(Self.changes(from: now, to: s.edits))")
        restore(s)
        flash("Redone")
    }

    private func restore(_ s: Snapshot) {
        set(s.edits)
        if s.selected != selectedID, let id = s.selected, clips.contains(where: { $0.id == id }) {
            // Straight to it, without leave()'s settling, which would edit the restored state.
            if let cur = selected, player.loadedURL == cur.url { positions[cur.url] = player.currentSeconds }
            selectedID = id
            player.pause()
            scheduleLoad()
        }
        scheduleSave()
    }

    /// Stage the selection (or `targets`) for the Trash, or keep it all if it all was.
    func toggleDelete(_ targets: [Clip]? = nil) {
        let list = targets ?? selection
        guard !list.isEmpty else { return }
        let on = list.contains { !edit($0).deleted }
        if targets != nil { DebugLog.write("List menu → \(on ? "Stage for Delete" : "Keep (Unstage Delete)")") }
        // Ranges beat the Trash: a file with keep ranges is only trashed once
        // the user confirms clearing them.
        if on, list.contains(where: { !RangeOps.settle(edit($0).ranges).isEmpty }) {
            player.pause()
            confirmTrash = list
            return
        }
        mutate(list) { $0.deleted = on }
        flash(on ? deleteMessage(list) : "\(subject(list)) kept")
    }

    /// Trash after clearing the ranges (the confirmed half of toggleDelete).
    func trashClearingRanges(_ list: [Clip]) {
        DebugLog.write("Cleared the ranges of \(subject(list)) and staged it for delete")
        mutate(list) { $0.ranges = []; $0.deleted = true }
        flash(deleteMessage(list))
    }

    private func deleteMessage(_ list: [Clip]) -> String {
        reviewFolder != nil ? "Nothing kept from \(subject(list)) (a copy: nothing is deleted)"
                       : "\(subject(list)) will go to the Trash on Apply"
    }

    /// What a row's menu acts on: the whole selection if the row is in it, else the row.
    func menuTargets(_ clip: Clip) -> [Clip] { picked.contains(clip.id) ? selection : [clip] }

    /// Crop key work needs the selected clip in the player.
    private func cropTarget() -> Clip? {
        guard let clip = selected else { return nil }
        if clip.isPhoto {
            flash("A photo has no timeline: drag on it to crop, \(keymap.label(.turn)) / \(keymap.label(.turnLeft)) rotate")
            return nil
        }
        guard selectedLoaded else { DebugLog.write("  \(clip.name): still loading, nothing done"); flash("Still loading \(clip.name)"); return nil }
        return clip
    }

    func setIn() {
        guard let clip = cropTarget() else { return }
        let t = player.frameStart(player.currentSeconds)
        let d = player.duration
        let wasDeleted = edit(clip).deleted
        mutate(clip) { $0.ranges = RangeOps.setIn($0.ranges, at: t, duration: d); $0.deleted = false }
        flash("Keep from \(player.timecode(t))" + (wasDeleted ? " · no longer staged for delete" : ""))
    }

    func setOut() {
        guard let clip = cropTarget() else { return }
        let t = player.frameEnd(player.currentSeconds)
        let d = player.duration
        let wasDeleted = edit(clip).deleted
        mutate(clip) { $0.ranges = RangeOps.setOut($0.ranges, at: t, duration: d); $0.deleted = false }
        flash("Keep up to \(player.timecode(player.currentSeconds))" + (wasDeleted ? " · no longer staged for delete" : ""))
    }

    func removeRange() {
        guard let clip = cropTarget() else { return }
        guard let r = RangeOps.remove(edit(clip).ranges, at: player.currentSeconds) else {
            flash("No kept range under the playhead")
            return
        }
        mutate(clip) { $0.ranges = r }
        flash(r.isEmpty ? "No crops left on \(clip.name)" : "Range removed")
    }

    func clearRanges(_ targets: [Clip]? = nil) {
        let all = targets ?? selection
        let list = all.filter { !edit($0).ranges.isEmpty }
        guard !list.isEmpty else { if !all.isEmpty { flash("No crops on \(subject(all))") }; return }
        if targets != nil { DebugLog.write("List menu → Clear Crops") }
        mutate(list) { $0.ranges = [] }
        flash("Crops cleared on \(subject(list))")
    }

    /// A photo that can be turned and cropped (its header read, a format
    /// BulkCut can write), or the video in the player.
    private func pictureTarget(_ target: Clip? = nil) -> Clip? {
        guard let clip = target ?? selected else { return nil }
        guard clip.isPhoto else { return target ?? cropTarget() }
        guard let info = photoInfos[clip.url] else { flash("Still reading \(clip.name)"); return nil }
        guard info.editable else { flash("Can't rotate or crop \(clip.name): it is \(info.notEditable)"); return nil }
        return clip
    }

    /// Turn the selection (or `targets`) `k` quarter turns clockwise
    /// (negative: anticlockwise). A zoom or crop keeps its part of the picture.
    func turn(by k: Int, _ targets: [Clip]? = nil) {
        let all = targets ?? selection
        guard !all.isEmpty else { return }
        if targets != nil { DebugLog.write("List menu → Rotate \(k > 0 ? "Right" : "Left") 90°") }
        // A photo needs its header read and a format BulkCut can write.
        let list = all.count == 1 ? [pictureTarget(all[0])].compactMap { $0 }
                                  : all.filter { !$0.isPhoto || photoInfos[$0.url]?.editable == true }
        guard !list.isEmpty else {
            if all.count > 1 { flash("None of the \(all.count) selected can be rotated") }
            return
        }
        let wasDeleted = list.contains { edit($0).deleted }
        mutate(list) { $0.turn(by: k); $0.deleted = false }
        var what: String
        if list.count == 1 {
            let c = list[0], t = edit(c).turns
            what = t == 0 ? "\(c.name) back upright" : "\(c.name) will be turned \(Self.turnLabel(t)) on Apply"
        } else {
            what = "\(subject(list)) turned 90° \(k > 0 ? "right" : "left")" + (list.count < all.count ? " · \(all.count - list.count) can't be" : "")
        }
        flash(what + (wasDeleted ? " · no longer staged for delete" : ""))
    }

    /// "90° right", "180°", "90° left".
    static func turnLabel(_ turns: Int) -> String {
        switch turns { case 1: "90° right"; case 2: "180°"; case 3: "90° left"; default: "0°" }
    }

    /// Zoom into (a video) or crop to (a photo) an area drawn on the picture.
    func setZoom(_ z: ZoomRect) {
        guard let clip = pictureTarget() else { return }
        DebugLog.write("\(clip.isPhoto ? "Crop" : "Zoom") drawn on the picture → \(clip.key)")
        let wasDeleted = edit(clip).deleted
        mutate(clip) { $0.zoom = z; $0.deleted = false }
        let size = selectedDisplay.map { " to \(z.label(in: $0, even: !clip.isPhoto))" } ?? ""
        flash("\(clip.isPhoto ? "Crop" : "Zoom")\(size) · \(keymap.label(.clearZoom)) clears" + (wasDeleted ? " · no longer staged for delete" : ""))
    }

    func clearZoom(_ targets: [Clip]? = nil) {
        let all = targets ?? selection
        let list = all.filter { edit($0).zoom != nil }
        // A photo's is a crop, a video's a zoom.
        let what = all.allSatisfy(\.isPhoto) ? "crop" : all.contains(where: \.isPhoto) ? "zoom / crop" : "zoom"
        guard !list.isEmpty else { if !all.isEmpty { flash("No \(what) on \(subject(all))") }; return }
        if targets != nil { DebugLog.write("List menu → Clear \(what.capitalized)") }
        mutate(list) { $0.zoom = nil }
        flash("\(what.capitalized) cleared on \(subject(list))")
    }

    func jumpEdge(_ dir: Int) {
        guard selectedLoaded else { return }
        let edges = RangeOps.edges(selectedEdit.ranges)
        let t = player.currentSeconds
        // An end edge is shown as the last kept frame (just before it).
        let target = dir < 0 ? edges.last { $0 < player.frameStart(t) - 1e-4 }
                             : edges.first { $0 > player.frameEnd(t) - 1e-4 }
        guard let e = target else { flash(edges.isEmpty ? "No crops on this clip" : "No more edges that way"); return }
        player.pause()
        let isEnd = (edges.firstIndex(of: e) ?? 0) % 2 == 1
        player.seek(to: e + (isEnd ? -0.5 : 0.5) / max(player.fps, 1))
    }

    // Dragging a range edge on the timeline: one undo step per drag.
    private var dragging: (clip: Clip, index: Int, edge: Edge)?

    func beginEdgeDrag(index: Int, edge: Edge) {
        guard let clip = cropTarget() else { return }
        pushUndo([clip.key])
        edits[clip.key]?.ranges = RangeOps.settle(edit(clip).ranges)
        dragging = (clip, index, edge)
        player.pause()
    }

    func dragEdge(to t: Double) {
        guard let d = dragging, selected?.id == d.clip.id else { return }
        let b = player.nearestBoundary(t)
        let r = RangeOps.moveEdge(edit(d.clip).ranges, index: d.index, edge: d.edge, to: b, duration: player.duration)
        edits[d.clip.key]?.ranges = r
        if r.indices.contains(d.index) {
            player.show(boundary: d.edge == .start ? r[d.index].start : r[d.index].end, before: d.edge == .end)
        }
    }

    func endEdgeDrag() {
        guard let d = dragging else { return }
        // An edge pulled onto the other one deletes the range (left at the
        // 0.01 s minimum it would be invisible, and still a "clip" for any
        // tool reading the review); one pulled onto the next range joins them.
        if let r = edits[d.clip.key]?.ranges {
            let t = RangeOps.tidyDrag(r)
            if t.count < r.count {
                let shrunk = r.count { $0.length < RangeOps.shrunk }
                edits[d.clip.key]?.ranges = t
                if edits[d.clip.key]?.isEmpty == true { edits[d.clip.key] = nil }
                flash((shrunk > 0 ? "Range removed: dragged down to nothing" : "Joined into one range") + " (⌘Z undoes it)")
            }
        }
        // beginEdgeDrag pushed the clip's edit from before the drag.
        let before = undoStack.last?.edits ?? [:]
        DebugLog.write("Timeline edge drag:\n\(Self.changes(from: before, to: current(before.keys)))")
        dragging = nil
        player.endScrub(at: player.currentSeconds)
        scheduleSave()
    }

    /// The description box's Return: `note` on the range of `clip` that
    /// overlaps `span` most (the one it was typed against, even if the
    /// playhead has moved on); nil puts the agent's description back. One
    /// undo step.
    func setNote(_ note: String?, clip: Clip, span: ClosedRange<Double>) {
        DebugLog.write("Description box: \(note == nil ? "the agent's description back" : "typed") on \(clip.name) "
                       + "\(Format.clock(span.lowerBound))–\(Format.clock(span.upperBound))")
        mutate(clip) { e in
            let o = { (r: KeepRange) in min(r.end, span.upperBound) - max(r.start, span.lowerBound) }
            guard let i = e.ranges.indices.max(by: { o(e.ranges[$0]) < o(e.ranges[$1]) }), o(e.ranges[i]) > 0 else { return }
            e.ranges[i].note = note
        }
    }

    // MARK: saving

    private func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled else { return }
            self?.saveNow()
        }
    }

    func saveNow() {
        saveTask?.cancel()
        guard let folder else { return }
        SessionStore.save(folder: folder, clips: clips, edits: edits, seeded: seeded)
        if reviewFolder != nil, let m = manifest {
            ReviewWriter.write(folder: folder, manifest: m, clips: clips, edits: edits)
        }
    }

    // MARK: apply

    func openApply() {
        guard !applying else { return }
        if reviewFolder != nil { return openSend() }
        guard hasChanges else {
            flash("Nothing staged: \(keymap.label(.toggleDelete)) stages a delete, \(keymap.label(.setIn)) / \(keymap.label(.setOut)) crop, "
                  + "\(keymap.label(.turn)) rotates, a drag on the picture zooms or crops")
            return
        }
        settleOpenRanges()
        DebugLog.write("Apply sheet opened, staged:\n\(DebugLog.staged(edits))")
        player.pause()
        showApply = true
    }

    /// A review folder's Apply: save, then the send sheet.
    func openSend() {
        settleOpenRanges()
        saveNow()
        player.pause()
        DebugLog.write("Review sheet opened, staged:\n\(DebugLog.staged(edits))")
        showSend = true
    }

    /// What a send would file: ranges by kind, and the files that keep nothing.
    var sendSummary: (beats: Int, picks: Int, mine: Int, seconds: Double, nothing: Int) {
        var s = (beats: 0, picks: 0, mine: 0, seconds: 0.0, nothing: 0)
        for c in clips where !c.isPhoto {
            let e = edit(c)
            let r = e.deleted ? [] : RangeOps.settle(e.ranges)
            if r.isEmpty { s.nothing += 1; continue }
            for x in r {
                switch x.kind {
                case "beat": s.beats += 1
                case "pick": s.picks += 1
                default: s.mine += 1
                }
                s.seconds += x.length
            }
        }
        return s
    }

    /// Per sequence, what the review keeps: its beats still covered by a teal
    /// range (the one overlapping each beat most), those the user removed,
    /// and how long the kept clips run.
    var sendSequences: [(title: String, clips: Int, removed: Int, seconds: Double)] {
        guard let reviewFolder else { return [] }
        let byName = Dictionary(clips.map { ($0.name, $0) }, uniquingKeysWith: { a, _ in a })
        return reviewFolder.sequences.map { seq in
            var used = Set<String>()
            var clips = 0, removed = 0, seconds = 0.0
            for b in seq.beats {
                let e = byName[b.file].map(edit) ?? ClipEdit()
                let teal = e.deleted ? [] : RangeOps.settle(e.ranges).filter { $0.kind == "beat" }
                let overlap = { (r: KeepRange) in min(r.end, b.end) - max(r.start, b.start) }
                guard let i = teal.indices.max(by: { overlap(teal[$0]) < overlap(teal[$1]) }), overlap(teal[i]) > 0 else {
                    removed += 1
                    continue
                }
                if used.insert("\(b.file)#\(i)").inserted {     // two beats joined: one clip
                    clips += 1
                    seconds += teal[i].length
                }
            }
            return (seq.title, clips, removed, seconds)
        }
    }

    private func settleOpenRanges() {
        for (k, e) in edits where e.ranges.contains(where: { $0.open != nil }) {
            edits[k]?.ranges = RangeOps.settle(e.ranges)
        }
    }

    /// ⌘S: Apply everything staged now, as a save would, without the sheet;
    /// "Overwrite originals" is whatever the sheet last had. Progress goes
    /// to the status line. Only problems bring up the sheet, to list them.
    func applyNow() {
        guard folder != nil, !applying, !showApply else { return }
        if reviewFolder != nil { return openSend() }
        guard hasChanges else { flash("Nothing staged to apply"); return }
        settleOpenRanges()
        let overwrite = UserDefaults.standard.bool(forKey: "overwriteOriginals")
        let p = plan(overwrite: overwrite)
        guard !p.isEmpty else { flash("Nothing to do: the crops left cover their whole clips"); return }
        guard confirmPermanent(p) else { DebugLog.write("⌘S Apply Now: cancelled at the no-Trash warning"); flash("Nothing applied"); return }
        DebugLog.write("⌘S Apply Now, staged:\n\(DebugLog.staged(edits))")
        applying = true
        player.pause()
        Task {
            let r = await apply(p, progress: { [weak self] text, i, n in
                self?.statusTask?.cancel()
                self?.status = n > 1 && i < n ? "Applying \(i + 1) of \(n): \(text)" : "Applying: \(text)"
            }, fraction: { _ in })
            applying = false
            var parts: [String] = []
            if !r.trashed.isEmpty { parts.append("\(r.trashed.count) to the Trash") }
            if !r.deleted.isEmpty { parts.append("\(r.deleted.count) deleted") }
            if !r.written.isEmpty { parts.append("\(r.written.count) written" + (overwrite ? "" : " beside the originals")) }
            if r.failures.isEmpty {
                flash("Applied: " + (parts.isEmpty ? "nothing to do" : parts.joined(separator: ", ")))
            } else {
                flash("Applied with \(r.failures.count) problem\(r.failures.count == 1 ? "" : "s")")
                saveResult = r
                showApply = true
            }
        }
    }

    /// ⌘S skips the sheet, which would list them: deleting or replacing
    /// files where there is no Trash asks first, until "Don't ask again".
    private func confirmPermanent(_ p: ApplyPlan) -> Bool {
        let gone = p.permanentDeletes.count, replaced = p.permanentReplaces
        guard gone + replaced > 0, !UserDefaults.standard.bool(forKey: "skipNoTrashWarning") else { return true }
        let files = { (n: Int) in n == 1 ? "1 file" : "\(n) files" }
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = gone > 0 && replaced > 0 ? "Delete \(files(gone)) and replace \(replaced == 1 ? "1 original" : "\(replaced) originals") permanently?"
            : gone > 0 ? "Delete \(files(gone)) permanently?"
            : "Replace \(replaced == 1 ? "1 original" : "\(replaced) originals") permanently?"
        a.informativeText = "\(p.noTrashVolumes.joined(separator: ", ")) has no Trash (a network share), so this can't be undone."
        a.addButton(withTitle: gone > 0 ? "Delete" : "Replace").hasDestructiveAction = true
        a.addButton(withTitle: "Cancel")
        a.showsSuppressionButton = true
        a.suppressionButton?.title = "Don't ask again"
        let ok = a.runModal() == .alertFirstButtonReturn
        if ok, a.suppressionButton?.state == .on { UserDefaults.standard.set(true, forKey: "skipNoTrashWarning") }
        return ok
    }

    func plan(overwrite: Bool) -> ApplyPlan {
        Exporter.plan(clips: clips, edits: edits, infos: infos, photoInfos: photoInfos, overwrite: overwrite)
    }

    func apply(_ plan: ApplyPlan, progress: @MainActor (String, Int, Int) -> Void,
               fraction: @escaping @MainActor (Double) -> Void) async -> ApplyResult {
        let index = selectedIndex ?? 0
        player.unload()                     // the file on screen may be about to go
        // Built in typed pieces: as one expression, the type checker can give up on it.
        let header: String = "Apply (overwrite originals: \(plan.overwrite ? "yes" : "no")"
            + (plan.noTrash.isEmpty ? "" : "; no Trash on \(plan.noTrashVolumes.joined(separator: ", "))") + "):\n"
        let trashLines: [String] = plan.trash.map { "  \(plan.noTrash.contains($0.url) ? "delete" : "trash") \($0.key)" }
        let cropLines: [String] = plan.crops.map { j in
            let ranges: String = zip(j.ranges, j.outputs).map { (r, out) -> String in
                String(format: "%.3f–%.3f", r.start, r.end) + " → \(out.lastPathComponent)" }.joined(separator: ", ")
            let turned: String = j.turns != 0 ? ", turned \(Self.turnLabel(j.turns))" : ""
            let zoomed: String = j.zoomSize.map { ", zoomed to \(Int($0.width))×\(Int($0.height)) (re-encoded)" } ?? ""
            return "  crop \(j.clip.key): " + ranges + turned + zoomed
        }
        let photoLines: [String] = plan.photos.map { j in
            let turned: String = j.turns != 0 ? ", turned \(Self.turnLabel(j.turns))" : ""
            let cropped: String = j.cropSize.map { ", cropped to \(Int($0.width))×\(Int($0.height))" } ?? ""
            return "  photo \(j.clip.key) → \(j.output.lastPathComponent)" + turned + cropped
                + (j.lossless ? " (orientation tag only)" : " (re-encoded)")
        }
        DebugLog.write(header + (trashLines + cropLines + photoLines).joined(separator: "\n"))
        let res = await Exporter.run(plan, progress: { text, i, n in
            DebugLog.write("  [\(i)/\(n)] \(text)")
            progress(text, i, n)
        }, fraction: fraction)
        DebugLog.write("Apply finished: \(res.trashed.count) trashed, \(res.deleted.count) deleted, \(res.written.count) written, \(res.failures.count) failed"
            + res.failures.map { "\n  FAILED \($0.name): \($0.why)" }.joined())
        for key in res.done { edits[key] = nil }
        for job in plan.crops { Thumbnails.shared.drop(job.clip.url) }
        for job in plan.photos {
            Thumbnails.shared.drop(job.output)
            PhotoStore.shared.drop(job.output)
        }
        photo = nil
        applyCount += 1
        undoStack = []
        redoStack = []
        // The list updated in place, not re-read (a network folder can take
        // minutes): files gone are dropped, rewritten ones read again, new
        // ones go in after the file they came from.
        // Each look is a round trip on a network share, so off the main thread.
        let touched = Set(plan.trash.map(\.url) + plan.crops.map(\.clip.url) + plan.photos.map(\.clip.url))
        let gone = Set(plan.trash.filter { res.done.contains($0.key) }.map(\.url))
        let before = clips, outputs = res.outputs
        let list = await Task.detached(priority: .userInitiated) { () -> [Clip] in
            var list: [Clip] = []
            for c in before {
                guard touched.contains(c.url) else { list.append(c); continue }
                guard !gone.contains(c.url) else { continue }
                if let now = Library.clip(at: c.url, key: c.key) { list.append(now) }
                let folderKey = c.folderPath.isEmpty ? "" : c.folderPath + "/"
                for out in outputs[c.url] ?? [] where out != c.url {
                    if let n = Library.clip(at: out, key: folderKey + out.lastPathComponent) { list.append(n) }
                }
            }
            return list
        }.value
        clips = list
        for u in touched { infos[u] = nil; photoInfos[u] = nil }
        let keys = Set(list.map(\.key))
        edits = edits.filter { keys.contains($0.key) }
        refreshFocus()
        saveNow()
        DebugLog.write("After Apply: \(list.count) files, still staged:\n\(DebugLog.staged(edits))")
        loadInfos()
        loadNotes()
        selectedID = nil
        if !clips.isEmpty { select(clips[min(index, clips.count - 1)].id) }
        return res
    }

    // MARK: view sizes

    func adjustThumbs(_ step: Int) {
        let w = Self.thumbWidths
        let i = w.firstIndex { $0 >= thumbWidth } ?? w.count - 1
        thumbWidth = w[min(max(i + step, 0), w.count - 1)]
    }

    // MARK: keyboard

    func installMonitors() {
        guard keyMonitor == nil else { return }
        // Not `self?.handle(e) ?? e`: optional chaining flattens, so handle's
        // nil ("swallow it") looked like "self is gone" and the event was
        // returned every time — AppKit then sent it on to the window, where
        // nothing handles key presses, and noResponderFor: beeped for every
        // bound key (and the menu key equivalents fired a second time).
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            guard let self else { return e }
            return self.handle(e)
        }
        scrollMonitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] e in
            guard let self, self.player.duration > 0 else { return e }
            return self.timeline.scroll(e, duration: self.player.duration, playhead: self.player.currentSeconds) ? nil : e
        }
    }

    /// Returns nil to swallow the event.
    func handle(_ e: NSEvent) -> NSEvent? {
        if keymap.recording != nil { return keymap.capture(e) }
        let a = keymap.action(for: e)
        // Only the main window, with no sheet over it; Settings and panels keep
        // their keys. Text that can be typed into keeps them too, but not the
        // notes panel's selectable text.
        let why: String?
        if let w = e.window, window == nil, isMainCandidate(w) { window = w }     // accessor missed it
        if e.window == nil { why = "no window" }
        else if e.window !== window { why = window == nil ? "main window unknown" : "other window (\(e.window?.title ?? ""))" }
        else if e.window?.attachedSheet != nil { why = "sheet open" }
        else if (e.window?.firstResponder as? NSText)?.isEditable == true { why = "editable text focused" }
        else if KeyCombo.isTextEditing(e), ((e.window?.firstResponder as? NSText)?.selectedRange.length ?? 0) > 0 { why = "text selected" }
        else if a == nil { why = "no action bound" }
        else { why = nil }
        if !e.isARepeat {
            let responder = e.window?.firstResponder.map { String(describing: type(of: $0)) } ?? "nil"
            keyLog.debug("key \(e.keyCode, privacy: .public) mods \(e.modifierFlags.intersection(KeyCombo.mask).rawValue, privacy: .public) → \(a?.rawValue ?? "-", privacy: .public): \(why ?? "handled", privacy: .public) [responder \(responder, privacy: .public)]")
        }
        if let a, a.changesEdits, let why, !e.isARepeat {
            DebugLog.write("Key \(keymap.label(a)) → \(a.title): IGNORED, \(why)")
        }
        guard why == nil, let a else { return e }
        if applying { return nil }          // ⌘S is under way; its progress is on the status line
        if e.isARepeat, !a.repeats { return nil }
        perform(a, from: "Key \(keymap.label(a))")
        return nil
    }

    /// The app's own window, not Settings, a panel or a sheet.
    private func isMainCandidate(_ w: NSWindow) -> Bool {
        !(w is NSPanel) && w.sheetParent == nil && w.identifier?.rawValue.contains("Settings") != true
            && w.title != "Settings" && w.contentView != nil && w.canBecomeMain
    }

    func perform(_ a: Action, from source: String = "Clip menu") {
        guard folder != nil, !applying else { return }
        if a.changesEdits {
            DebugLog.write("\(source) → \(a.title) on \(!picked.isEmpty ? "\(picked.count) selected" : selected?.key ?? "no clip selected")")
        }
        // A photo has no playhead or timeline.
        if selected?.isPhoto == true, ![.playPause, .sectionsOnly, .loop].contains(a), a.group == .playback || a.group == .timeline { return }
        switch a {
        case .prevClip: moveSelection(-1)
        case .nextClip: moveSelection(1)
        case .selectAll: selectAll()
        case .toggleDelete: toggleDelete()
        case .copyPath: copyPaths()
        case .focusNext: cycleFocus(1, from: source)
        case .focusPrev: cycleFocus(-1, from: source)
        case .playPause: togglePlay()
        case .seekBack: player.seek(by: -keymap.seekStep)
        case .seekForward: player.seek(by: keymap.seekStep)
        case .stepBack: player.step(frames: -1)
        case .stepForward: player.step(frames: 1)
        case .jumpBack: player.seek(by: -keymap.jumpStep)
        case .jumpForward: player.seek(by: keymap.jumpStep)
        case .goStart: player.seek(to: 0)
        case .goEnd: player.seek(to: player.duration)
        case .speedDown: player.cycleSpeed(-1); flash("Speed \(player.speedLabel)")
        case .speedUp: player.cycleSpeed(1); flash("Speed \(player.speedLabel)")
        case .sectionsOnly: toggleSectionsOnly()
        case .loop: toggleLoop()
        case .setIn: setIn()
        case .setOut: setOut()
        case .prevEdge: jumpEdge(-1)
        case .nextEdge: jumpEdge(1)
        case .removeRange: removeRange()
        case .clearRanges: clearRanges()
        case .turn: turn(by: 1)
        case .turnLeft: turn(by: -1)
        case .clearZoom: clearZoom()
        case .zoomIn: flash(timeline.zoomIn(around: player.currentSeconds, duration: player.duration))
        case .zoomOut: flash(timeline.zoomOut(around: player.currentSeconds, duration: player.duration))
        }
    }

    func showDebugLog() {
        let u = DebugLog.url
        if FileManager.default.fileExists(atPath: u.path) { NSWorkspace.shared.open(u) }
        else { flash("Nothing logged yet today (\(DebugLog.dir.path))") }
    }

    func reveal(_ list: [Clip]? = nil) {
        let list = list ?? selection
        if !list.isEmpty { NSWorkspace.shared.activateFileViewerSelecting(list.map(\.url)) }
    }

    /// Several selected: one path a line.
    func copyPaths(_ list: [Clip]? = nil) {
        let list = list ?? selection
        guard !list.isEmpty else { return }
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(list.map(\.url.path).joined(separator: "\n"), forType: .string)
        flash(list.count == 1 ? "Copied \(list[0].url.path)" : "Copied \(list.count) paths")
    }
}
