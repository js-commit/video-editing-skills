import AppKit
import SwiftUI

/// The left side: one row per video or photo — poster frame, name, facts,
/// and what is staged for it — the open folder's first, then each
/// subfolder's under a header. ↑ / ↓ (or a click) selects; ⌘= / ⌘- resize
/// the thumbnails.
struct ClipList: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text(model.countLabel + (model.picked.isEmpty ? "" : " · \(model.picked.count) selected"))
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                Button { model.subfolders.toggle() } label: {
                    Image(systemName: model.subfolders ? "folder.fill.badge.plus" : "folder.badge.plus")
                }
                .buttonStyle(.borderless)
                .foregroundStyle(model.subfolders ? Color.accentColor : Color.secondary)
                .help(model.subfolders ? "Showing subfolders too; click for this folder only" : "This folder only; click to show subfolders too")
                Button { model.adjustThumbs(-1) } label: { Image(systemName: "minus.magnifyingglass") }
                    .buttonStyle(.borderless).help("Smaller thumbnails (⌘-)")
                Button { model.adjustThumbs(1) } label: { Image(systemName: "plus.magnifyingglass") }
                    .buttonStyle(.borderless).help("Bigger thumbnails (⌘=)")
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            if let s = model.scanning {
                Divider()
                ScanBanner(state: s) { model.stopScan() }
            }
            if model.focusKeys != nil {
                Divider()
                focusBanner
            }
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 2) {
                        if model.focusKeys != nil {
                            // A review focus: its files only, in the order it plays them.
                            ForEach(model.visibleClips) { row($0) }
                        } else {
                            let headers = model.sections.count > 1 || model.sections.first.map { !$0.path.isEmpty } == true
                            ForEach(model.sections) { section in
                                Section {
                                    ForEach(model.clips[section.range]) { row($0) }
                                } header: {
                                    if headers {
                                        FolderHeader(path: section.path, root: model.folder?.lastPathComponent ?? "",
                                                     clips: model.clips[section.range], edits: model.edits)
                                    }
                                }
                            }
                        }
                    }
                    .padding(6)
                    // A fresh stack per focus: rows keep their ids (clip.id, for
                    // scrollTo) across the focused and full lists, and a lazy stack
                    // reusing them across the branch switch can keep drawing the rows
                    // as they were when the focus began (the highlight stuck on
                    // the first row while playback moves on).
                    .id(model.focus)
                }
                .onChange(of: model.selectedID) { _, id in
                    if let id { proxy.scrollTo(id) }
                }
                .onChange(of: model.focus) { _, _ in
                    if let id = model.selectedID { proxy.scrollTo(id) }
                }
            }
            Divider()
            HStack {
                Text(footer).font(.system(size: 12)).foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
        }
    }

    private func row(_ clip: Clip) -> some View {
        ClipRow(clip: clip, info: model.infos[clip.url], photoInfo: model.photoInfos[clip.url],
                edit: model.edits[clip.key], notes: model.notes[clip.key],
                selected: clip.id == model.selectedID, picked: model.picked.contains(clip.id),
                thumbWidth: model.thumbWidth,
                generation: model.applyCount,
                focusNote: model.focusNote(clip), focusTint: focusTint,
                loadInfo: { await model.loadInfo(clip) })
            .id(clip.id)
            .contentShape(Rectangle())
            .onTapGesture { model.click(clip) }
            .contextMenu { menu(for: clip) }
    }

    private var focusTint: Color {
        KeepRange(start: 0, end: 1, kind: model.focus == .picks ? "pick" : "beat").tint
    }

    /// Above a focused list: what it shows, and the way back to everything.
    private var focusBanner: some View {
        let n = model.visibleClips.count
        return HStack(spacing: 8) {
            Image(systemName: "line.3.horizontal.decrease.circle.fill").foregroundStyle(focusTint)
            VStack(alignment: .leading, spacing: 1) {
                Text(model.focusTitle).font(.system(size: 12, weight: .semibold)).lineLimit(1).truncationMode(.middle)
                Text("\(n) file\(n == 1 ? "" : "s"), in the order it plays · \(model.keymap.label(.focusNext)) next focus")
                    .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 4)
            Button("Show All") { model.setFocus(.everything, from: "Show All button") }
                .controlSize(.small)
                .help("Back to every clip and every coloured range")
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(focusTint.opacity(0.1))
    }

    private var footer: String {
        let k = model.keymap
        if model.applying { return "Applying…" }
        guard model.hasChanges else {
            if model.selected?.isPhoto == true {
                return "Nothing staged · \(k.label(.toggleDelete)) delete · \(k.label(.turn)) / \(k.label(.turnLeft)) rotate · drag to crop"
            }
            return "Nothing staged · \(k.label(.toggleDelete)) delete · \(k.label(.setIn)) / \(k.label(.setOut)) crop · \(k.label(.turn)) rotate"
        }
        var parts = ["\(model.deleteCount) to Trash"]
        if model.cropCount > 0 { parts.append("\(model.cropCount) to crop") }
        if model.turnCount > 0 { parts.append("\(model.turnCount) to rotate") }
        if model.zoomCount > 0 { parts.append("\(model.zoomCount) to zoom") }
        return parts.joined(separator: " · ") + " · ⌘S apply now"
    }

    /// For the whole selection if the row is in it. The clips are looked
    /// up when an item is chosen, not each time a row is drawn.
    @ViewBuilder
    private func menu(for clip: Clip) -> some View {
        let n = model.picked.contains(clip.id) ? model.picked.count : 1
        let targets = { model.menuTargets(clip) }
        let e = model.edit(clip)
        Button(n > 1 ? "Stage / Unstage \(n) for Delete" : e.deleted ? "Keep (Unstage Delete)" : "Stage for Delete") {
            model.toggleDelete(targets())
        }
        Button(n > 1 ? "Rotate \(n) Right 90°" : "Rotate Right 90°") { model.turn(by: 1, targets()) }
        Button(n > 1 ? "Rotate \(n) Left 90°" : "Rotate Left 90°") { model.turn(by: -1, targets()) }
        if n > 1 {
            Button("Clear Crops on \(n)") { model.clearRanges(targets()) }
            Button("Clear Zoom / Crop on \(n)") { model.clearZoom(targets()) }
        } else if clip.isPhoto {
            Button("Clear Crop") { model.clearZoom([clip]) }.disabled(e.zoom == nil)
        } else {
            Button("Clear Crops") { model.clearRanges([clip]) }.disabled(e.ranges.isEmpty)
            Button("Clear Zoom") { model.clearZoom([clip]) }.disabled(e.zoom == nil)
        }
        Divider()
        Button(n > 1 ? "Copy \(n) Paths" : "Copy Path") { model.copyPaths(targets()) }
        Button(n > 1 ? "Reveal \(n) in Finder" : "Reveal in Finder") { model.reveal(targets()) }
    }
}

/// A folder being read: how far it has got, and Stop to work with what it
/// has found (a network share can take a while).
struct ScanBanner: View {
    let state: ScanState
    let stop: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            VStack(alignment: .leading, spacing: 1) {
                Text("Reading \(state.folder.lastPathComponent)…").font(.system(size: 12, weight: .semibold)).lineLimit(1)
                Text("\(state.files) videos and photos"
                     + (state.folders > 1 ? " · \(state.folders) folders" : "")
                     + (state.current.isEmpty ? "" : " · " + state.current.split(separator: "/").joined(separator: " › ")))
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.head)
                    .monospacedDigit()
            }
            Spacer(minLength: 4)
            Button("Stop", action: stop)
                .controlSize(.small)
                .help("Stop reading and show what has been found so far (⌘R reads it all again)")
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
    }
}

/// Where the list moves into another folder: its path under the open
/// folder, how many files, and how many are staged for the Trash.
struct FolderHeader: View {
    /// "" for the open folder itself.
    let path: String
    let root: String
    let clips: ArraySlice<Clip>
    let edits: [String: ClipEdit]

    var body: some View {
        let videos = clips.count { !$0.isPhoto }, photos = clips.count - videos
        let trash = clips.count { edits[$0.key]?.deleted == true }
        HStack(spacing: 6) {
            Image(systemName: path.isEmpty ? "folder" : "arrow.turn.down.right")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Color.accentColor)
            Text(path.isEmpty ? root : path.split(separator: "/").joined(separator: " › "))
                .font(.system(size: 12, weight: .semibold))
                .lineLimit(1).truncationMode(.head)
            Text([videos > 0 ? "\(videos) video\(videos == 1 ? "" : "s")" : nil,
                  photos > 0 ? "\(photos) photo\(photos == 1 ? "" : "s")" : nil].compactMap { $0 }.joined(separator: " · "))
                .font(.system(size: 11)).foregroundStyle(.secondary)
                .lineLimit(1)
            Spacer(minLength: 4)
            if trash > 0 {
                Label("\(trash)", systemImage: "trash").font(.system(size: 11, weight: .semibold)).foregroundStyle(.red)
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
        .padding(.top, path.isEmpty ? 0 : 10)
        .padding(.bottom, 2)
        .help(path.isEmpty ? root : path)
    }
}

struct ClipRow: View {
    let clip: Clip
    let info: VideoInfo?
    let photoInfo: PhotoInfo?
    let edit: ClipEdit?
    let notes: ClipNotes?
    let selected: Bool
    /// One of several selected (AppModel.picked).
    let picked: Bool
    let thumbWidth: Double
    /// AppModel.applyCount.
    let generation: Int
    /// In a review focus: which of its beats (or how many picks) the file holds.
    let focusNote: String?
    let focusTint: Color
    /// Reads the file's header when it is on a network share (AppModel.loadInfo).
    let loadInfo: () async -> Void
    @State private var image: CGImage?

    init(clip: Clip, info: VideoInfo?, photoInfo: PhotoInfo?, edit: ClipEdit?, notes: ClipNotes?, selected: Bool,
         picked: Bool, thumbWidth: Double, generation: Int, focusNote: String? = nil, focusTint: Color = .teal,
         loadInfo: @escaping () async -> Void) {
        self.generation = generation
        self.focusNote = focusNote
        self.focusTint = focusTint
        self.loadInfo = loadInfo
        self.clip = clip
        self.info = info
        self.photoInfo = photoInfo
        self.edit = edit
        self.notes = notes
        self.selected = selected
        self.picked = picked
        self.thumbWidth = thumbWidth
        _image = State(initialValue: Thumbnails.shared.cached(clip))
    }

    var body: some View {
        let deleted = edit?.deleted == true
        let pieces = edit.map { RangeOps.settle($0.ranges) } ?? []
        let tw = CGFloat(thumbWidth), th = tw * 9 / 16
        let turns = edit?.turns ?? 0
        HStack(alignment: .top, spacing: 10) {
            ZStack(alignment: .bottomTrailing) {
                Rectangle().fill(Color.black)
                if let picture {
                    // Fitted to the box turned with it, then turned: a quarter
                    // turn fits the picture's other side to the box.
                    Image(decorative: picture, scale: 1).resizable().aspectRatio(contentMode: .fit)
                        .frame(width: turns % 2 == 1 ? th : tw, height: turns % 2 == 1 ? tw : th)
                        .rotationEffect(.degrees(Double(turns) * 90))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                if let d = info?.duration {
                    Text(Format.duration(d))
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 4).padding(.vertical, 1)
                        .background(Color.black.opacity(0.65), in: RoundedRectangle(cornerRadius: 3))
                        .padding(3)
                        .padding(.bottom, pieces.isEmpty ? 0 : 4)
                }
                if deleted {
                    ZStack {
                        Color.red.opacity(0.28)
                        Image(systemName: "trash.fill").font(.system(size: max(14, tw / 6))).foregroundStyle(.white)
                    }
                }
                if !pieces.isEmpty, let d = info?.duration, d > 0 {
                    RangeStrip(ranges: pieces, duration: d).frame(height: 4)
                }
            }
            .frame(width: tw, height: th)
            .overlay(alignment: .topLeading) {
                if let s = notes?.speed { SpeedChip(speed: s, onVideo: true).padding(3) }
            }
            .clipShape(RoundedRectangle(cornerRadius: 5))

            VStack(alignment: .leading, spacing: 3) {
                Text(clip.name)
                    .font(.system(size: 13, weight: .semibold))
                    .strikethrough(deleted)
                    .lineLimit(1).truncationMode(.middle)
                Text(details)
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .lineLimit(2)
                if let f = focusNote {
                    Label(f, systemImage: "line.3.horizontal.decrease")
                        .font(.system(size: 11, weight: .semibold)).foregroundStyle(focusTint)
                        .lineLimit(1)
                }
                if let n = notes {
                    if let h = n.headline {
                        // As many lines as sit beside the thumbnail.
                        Text(h)
                            .font(.system(size: 11.5)).foregroundStyle(Color.primary.opacity(0.8))
                            .lineLimit(max(1, Int((tw * 9 / 16 - 36) / 14)))
                            .help(h)
                    }
                    if let p = n.privacy {
                        Label("Privacy", systemImage: "exclamationmark.triangle.fill")
                            .font(.system(size: 11, weight: .semibold)).foregroundStyle(.orange)
                            .help(p)
                    }
                }
                if deleted {
                    Label("To Trash", systemImage: "trash").font(.system(size: 11, weight: .semibold)).foregroundStyle(.red)
                } else {
                    if !pieces.isEmpty {
                        Label(cropText(pieces), systemImage: "scissors")
                            .font(.system(size: 11, weight: .semibold)).foregroundStyle(.orange)
                    }
                    if let p = pictureText {
                        Label(p, systemImage: edit?.zoom != nil ? (clip.isPhoto ? "crop" : "plus.viewfinder")
                                                                : turns == 3 ? "rotate.left" : "rotate.right")
                            .font(.system(size: 11, weight: .semibold)).foregroundStyle(.orange)
                    }
                }
            }
            .padding(.top, 2)
            Spacer(minLength: 0)
        }
        .padding(6)
        .background(RoundedRectangle(cornerRadius: 7).fill(selected || picked ? Color.accentColor.opacity(selected ? 0.25 : 0.16) : Color.clear))
        .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(selected ? Color.accentColor : picked ? Color.accentColor.opacity(0.45) : .clear,
                                                               lineWidth: 1.5))
        .opacity(deleted ? 0.5 : 1)
        .task(id: [AnyHashable(clip), AnyHashable(generation)]) { await loadInfo() }
        .task(id: [AnyHashable(clip), AnyHashable(generation)]) {
            // Instant when cached; `clip` changes identity when the file changes,
            // `generation` after an Apply (which drops the files it rewrote).
            image = await Thumbnails.shared.image(for: clip)
        }
    }

    /// The poster as it will come out: cropped to the zoom (the poster is
    /// not turned yet, so neither is the area); the view turns it.
    private var picture: CGImage? {
        guard let image, let z = edit?.zoom else { return image }
        let a = z.rotated(-(edit?.turns ?? 0))
        let w = CGFloat(image.width), h = CGFloat(image.height)
        return image.cropping(to: CGRect(x: a.x * w, y: a.y * h, width: a.w * w, height: a.h * h).integral) ?? image
    }

    private var pictureText: String? {
        guard let e = edit else { return nil }
        var parts: [String] = []
        if e.turns != 0 { parts.append("Rotate \(AppModel.turnLabel(e.turns))") }
        if let z = e.zoom {
            let size = clip.isPhoto ? photoInfo?.size(turns: e.turns) : info?.size(turns: e.turns)
            parts.append((clip.isPhoto ? "Crop" : "Zoom") + (size.map { " to " + z.label(in: $0, even: !clip.isPhoto) } ?? ""))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private var details: String {
        var parts: [String] = []
        if let i = photoInfo { parts += ["\(i.width)×\(i.height)", i.frames > 1 ? "animated \(i.format)" : i.format] }
        if let i = info { parts += ["\(i.width)×\(i.height)", "\(i.fpsLabel) fps", i.codec] }
        parts.append(Format.bytes(clip.size))
        return parts.joined(separator: " · ")
    }

    private func cropText(_ r: [KeepRange]) -> String {
        let kept = Format.duration(r.reduce(0) { $0 + $1.length })
        return r.count == 1 ? "Crop to \(kept)" : "\(r.count) pieces · \(kept)"
    }
}

/// The kept ranges along the bottom edge of a thumbnail.
struct RangeStrip: View {
    let ranges: [KeepRange]
    let duration: Double

    var body: some View {
        Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.black.opacity(0.7)))
            for r in ranges {
                let x0 = CGFloat(r.start / duration) * size.width
                let x1 = CGFloat(r.end / duration) * size.width
                ctx.fill(Path(CGRect(x: x0, y: 0, width: max(1, x1 - x0), height: size.height)),
                         with: .color(Color(red: 1, green: 0.8, blue: 0.1)))
            }
        }
    }
}
