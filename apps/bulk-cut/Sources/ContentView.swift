import AVFoundation
import AppKit
import SwiftUI

/// The video, turned and zoomed as staged once its shown size is known.
struct PlayerView: NSViewRepresentable {
    let player: AVPlayer
    /// The picture's size as shown (its own rotation and the turn applied), in pixels.
    var display: CGSize?
    var turns = 0
    var zoom: ZoomRect?

    final class View: NSView {
        let playerLayer = AVPlayerLayer()
        /// Clips the picture to the zoom area.
        let frameLayer = CALayer()
        var display: CGSize?
        var turns = 0
        var zoom: ZoomRect?

        override init(frame: NSRect) {
            super.init(frame: frame)
            frameLayer.masksToBounds = true
            playerLayer.videoGravity = .resizeAspect
            frameLayer.addSublayer(playerLayer)
            wantsLayer = true
        }

        required init?(coder: NSCoder) { fatalError("not used") }

        override var acceptsFirstResponder: Bool { false }

        override func makeBackingLayer() -> CALayer {
            let root = CALayer()
            root.backgroundColor = NSColor.black.cgColor
            root.addSublayer(frameLayer)
            return root
        }

        override func setFrameSize(_ newSize: NSSize) {
            super.setFrameSize(newSize)
            place()
        }

        override func layout() {
            super.layout()
            place()
        }

        /// The whole turned frame is sized so the zoom area fills the box
        /// (fitted, centred), then clipped to it; the picture sits at its
        /// centre, spun by the turn.
        func place() {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            defer { CATransaction.commit() }
            let v = bounds.size
            playerLayer.setAffineTransform(.identity)
            guard let d = display, d.width > 0, d.height > 0 else {
                frameLayer.frame = bounds
                playerLayer.frame = frameLayer.bounds
                return
            }
            Picture.lay(playerLayer, in: frameLayer, view: v, display: d, turns: turns, zoom: zoom)
        }
    }

    func makeNSView(context: Context) -> View {
        let v = View()
        v.playerLayer.player = player
        return v
    }

    func updateNSView(_ v: View, context: Context) {
        if v.playerLayer.player !== player { v.playerLayer.player = player }
        guard v.display != display || v.turns != turns || v.zoom != zoom else { return }
        v.display = display
        v.turns = turns
        v.zoom = zoom
        v.place()
    }
}

/// Hands the hosting NSWindow to the model, so the key monitor can tell the
/// main window's keys from Settings' and the open panel's.
struct WindowAccessor: NSViewRepresentable {
    let found: (NSWindow) -> Void

    final class Probe: NSView {
        var found: ((NSWindow) -> Void)?
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let w = window { found?(w) }
        }
    }

    func makeNSView(context: Context) -> Probe {
        let v = Probe()
        v.found = found
        return v
    }

    func updateNSView(_ v: Probe, context: Context) {
        v.found = found
        if let w = v.window { found(w) }
    }
}

struct ContentView: View {
    @ObservedObject var model: AppModel
    /// The clip list's share of the window width; drag the divider to change it.
    @AppStorage("listFraction") private var listFraction = 0.3
    @State private var dragStartWidth: CGFloat?

    var body: some View {
        Group {
            if model.folder == nil {
                emptyState
            } else {
                GeometryReader { geo in
                    let total = geo.size.width
                    let listWidth = min(max(total * listFraction, 260), max(260, total - 560))
                    HStack(spacing: 0) {
                        ClipList(model: model)
                            .frame(width: listWidth)
                        SplitHandle { dx in
                            let start = dragStartWidth ?? listWidth
                            if dragStartWidth == nil { dragStartWidth = listWidth }
                            listFraction = min(max(Double((start + dx) / max(total, 1)), 0.12), 0.7)
                        } ended: {
                            dragStartWidth = nil
                        }
                        PlayerPane(model: model)
                    }
                }
            }
        }
        .frame(minWidth: 1000, minHeight: 620)
        .background(WindowAccessor { model.window = $0 })
        .onDrop(of: [.fileURL], isTargeted: nil) { model.handleDrop($0) }
        .onAppear {
            model.installMonitors()
            model.openFromArguments()
        }
        .sheet(isPresented: $model.showApply) { ApplySheet(model: model) }
        .sheet(isPresented: $model.showSend) { SendSheet(model: model) }
        .confirmationDialog(trashQuestion, isPresented: Binding(get: { model.confirmTrash != nil },
                                                                set: { if !$0 { model.confirmTrash = nil } }),
                            titleVisibility: .visible) {
            Button("Clear the ranges and " + (model.reviewFolder != nil ? "keep nothing" : "trash it"), role: .destructive) {
                if let list = model.confirmTrash { model.trashClearingRanges(list) }
                model.confirmTrash = nil
            }
            Button("Keep the ranges", role: .cancel) { model.confirmTrash = nil }
        } message: {
            Text("Ranges always win over the Trash. To drop this, its ranges have to go first.")
        }
        .sheet(isPresented: $model.showShortcuts) { ShortcutsView(keymap: model.keymap) }
        .navigationTitle(model.folder?.lastPathComponent ?? "Bulk Cut")
        .navigationSubtitle(model.folder.map { $0.deletingLastPathComponent().path } ?? "")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                if let review = model.reviewFolder {
                    Button { model.openSend() } label: {
                        Label((review.send?.label ?? "Done") + "…", systemImage: "tray.and.arrow.up.fill")
                            .labelStyle(.titleAndIcon)
                    }
                    .help("Finish the review (⌘⏎): it is saved to \(Manifest.reviewFileName) after every change. "
                          + "Nothing in this folder is deleted.")
                } else {
                Button { model.openApply() } label: {
                    if model.applying {
                        Label { Text("Applying…") } icon: { ProgressView().controlSize(.small) }
                            .labelStyle(.titleAndIcon)
                    } else {
                        Label(applyLabel, systemImage: "checkmark.circle")
                            .labelStyle(.titleAndIcon)
                    }
                }
                .disabled(!model.hasChanges || model.applying)
                .help("Review, then trash, crop, rotate and zoom everything staged (⌘⏎). ⌘S applies it at once.")
                }
            }
        }
    }

    private var trashQuestion: String {
        let list = model.confirmTrash ?? []
        let what = list.count == 1 ? list[0].name : "\(list.count) clips"
        return "\(what) still has ranges to keep"
    }

    private var applyLabel: String {
        var parts: [String] = []
        if model.deleteCount > 0 { parts.append("\(model.deleteCount) to Trash") }
        if model.cropCount > 0 { parts.append("\(model.cropCount) to crop") }
        if model.turnCount > 0 { parts.append("\(model.turnCount) to rotate") }
        if model.zoomCount > 0 { parts.append("\(model.zoomCount) to zoom") }
        return parts.isEmpty ? "Apply…" : "Apply: " + parts.joined(separator: ", ") + "…"
    }

    @ViewBuilder
    private var emptyState: some View {
        if let s = model.scanning {
            ScanBanner(state: s) { model.stopScan() }
                .frame(width: 420)
                .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 8))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            openPrompt
        }
    }

    private var openPrompt: some View {
        VStack(spacing: 14) {
            Image(systemName: "photo.stack").font(.system(size: 54)).foregroundStyle(.secondary)
            Text("Open a folder of videos and photos").font(.title2.weight(.semibold))
            Text("⌘O, or drop a folder (or a file in it) here").foregroundStyle(.secondary)
            Button("Open Folder…") { model.openPanel() }.controlSize(.large)
            if !model.recents.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    ForEach(model.recents.prefix(5), id: \.self) { u in
                        Button(u.path) { model.open(url: u) }
                            .buttonStyle(.link)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
                .padding(.top, 10)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// The divider between the list and the player: a hairline with a wider grab area.
struct SplitHandle: View {
    let changed: (CGFloat) -> Void
    let ended: () -> Void

    var body: some View {
        Rectangle()
            .fill(Color(nsColor: .separatorColor))
            .frame(width: 1)
            .padding(.horizontal, 3)
            .contentShape(Rectangle())
            .onHover { inside in
                if inside { NSCursor.resizeLeftRight.push() } else { NSCursor.pop() }
            }
            .gesture(
                DragGesture(minimumDistance: 1, coordinateSpace: .global)
                    .onChanged { changed($0.translation.width) }
                    .onEnded { _ in ended() }
            )
    }
}

/// The right side: the clip's name and facts, the video, the timeline, the
/// transport; for a photo, the photo and a status line.
struct PlayerPane: View {
    @ObservedObject var model: AppModel

    var body: some View {
        let clip = model.selected
        let isPhoto = clip?.isPhoto == true
        VStack(spacing: 0) {
            header
            if !isPhoto, let c = clip, let s = model.reviewFolder {
                Divider()
                DescriptionBox(model: model, player: model.player, clip: c, review: s)
            }
            if !isPhoto, model.showNotes, let c = clip, let n = model.notes[c.key] {
                Divider()
                NotesPanel(notes: n, player: model.player,
                           libraryLabel: model.reviewFolder?.legend.library.capitalizedFirst ?? "In library")
                    .id(c.id)
                Divider()
            }
            ZStack(alignment: .top) {
                let edit = model.selectedEdit
                if let c = clip, isPhoto {
                    PhotoView(image: model.selectedPhoto ?? Thumbnails.shared.cached(c), display: model.selectedDisplay,
                              turns: edit.turns, crop: edit.zoom)
                    if let display = model.selectedDisplay, model.photoInfos[c.url]?.editable == true {
                        ZoomOverlay(display: display, zoom: edit.zoom, evenSizes: false) { model.setZoom($0) }
                    }
                } else {
                    let display = model.selectedLoaded ? model.selectedDisplay : nil
                    PlayerView(player: model.player.player, display: display, turns: edit.turns,
                               zoom: display != nil ? edit.zoom : nil)
                    if let display {
                        ZoomOverlay(display: display, zoom: edit.zoom) { model.setZoom($0) }
                    }
                }
                if model.selectedEdit.deleted, model.reviewFolder != nil {
                    Label("Not kept", systemImage: "minus.circle")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.white.opacity(0.9))
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(.ultraThinMaterial, in: Capsule())
                        .help("Nothing from this file is kept in the review. Nothing is deleted. "
                              + "Set a range to keep part of it.")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                } else if model.selectedEdit.deleted {
                    Label("Staged for delete — \(model.keymap.label(.toggleDelete)) to keep", systemImage: "trash.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(Color.red.opacity(0.85), in: Capsule())
                        .padding(.top, 12)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            if isPhoto {
                PhotoBar(model: model)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
            } else {
                VStack(spacing: 8) {
                    if let review = model.reviewFolder {
                        ReviewLegend(legend: review.legend, focus: model.focus == .everything ? nil : model.focusTitle,
                                     key: model.keymap.label(.focusNext), sendLabel: review.send?.label)
                    }
                    ClipTimeline(model: model)
                    TransportBar(model: model, player: model.player)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            if let c = model.selected {
                if !c.folderPath.isEmpty {
                    Text(c.folderPath.split(separator: "/").joined(separator: " › ") + " ›")
                        .font(.system(size: 13)).foregroundStyle(.secondary)
                        .lineLimit(1).truncationMode(.head)
                        .layoutPriority(-1)
                }
                Text(c.name).font(.system(size: 14, weight: .semibold)).lineLimit(1).truncationMode(.middle)
                if let i = model.infos[c.url] {
                    Text("\(i.width)×\(i.height) · \(i.fpsLabel) fps · \(i.codec) · \(Format.bytes(c.size))")
                        .font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
                } else if let i = model.photoInfos[c.url] {
                    Text("\(i.width)×\(i.height) · \(i.frames > 1 ? "animated " : "")\(i.format) · \(Format.bytes(c.size))")
                        .font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
                }
                if let s = model.notes[c.key]?.speed { SpeedChip(speed: s) }
                Spacer()
                turnControls(c)
                if c.isPhoto { photoControls(c) } else { pictureControls }
                if let n = model.visibleIndex {
                    Text("\(n + 1) / \(model.visibleClips.count)").font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                }
            } else {
                Text(model.clips.isEmpty ? "No videos or photos in this folder" : "Nothing selected").foregroundStyle(.secondary)
                Spacer()
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
    }

    /// Rotate left / right a quarter turn.
    @ViewBuilder
    private func turnControls(_ c: Clip) -> some View {
        let e = model.selectedEdit
        let k = model.keymap
        let editable = !c.isPhoto || model.photoInfos[c.url]?.editable != false
        let lossless = c.isPhoto ? "A JPEG, HEIC or TIFF only has its orientation tag changed on Apply."
                                 : "Lossless: only the video's track header changes on Apply."
        Button { model.perform(.turnLeft, from: "Rotate Left button") } label: {
            Image(systemName: "rotate.left")
        }
        .buttonStyle(.borderless)
        .foregroundStyle(Color.secondary)
        .help("Rotate 90° left (\(k.label(.turnLeft))). \(lossless)")
        .disabled(!editable)
        Button { model.perform(.turn, from: "Rotate Right button") } label: {
            Label(e.turns == 0 ? "Rotate" : "Rotated \(AppModel.turnLabel(e.turns))", systemImage: "rotate.right")
        }
        .buttonStyle(.borderless)
        .foregroundStyle(e.turns != 0 ? Color.orange : Color.secondary)
        .help("Rotate 90° right (\(k.label(.turn))). \(lossless)")
        .disabled(!editable)
    }

    /// The crop: a hint while there is none, its size and a clear button once there is.
    @ViewBuilder
    private func photoControls(_ c: Clip) -> some View {
        let e = model.selectedEdit
        let k = model.keymap
        let editable = model.photoInfos[c.url]?.editable != false
        if let z = e.zoom {
            Button { model.perform(.clearZoom, from: "Clear Crop button") } label: {
                Label("Crop " + (model.selectedDisplay.map { z.label(in: $0, even: false) } ?? ""), systemImage: "xmark.circle.fill")
            }
            .buttonStyle(.borderless)
            .foregroundStyle(Color.orange)
            .help("Click to clear the crop (\(k.label(.clearZoom))). Drag on the photo to crop in further.")
        } else {
            Button { model.flash(ZoomOverlay.photoHint) } label: {
                Label("Crop", systemImage: "crop")
            }
            .buttonStyle(.borderless)
            .foregroundStyle(Color.secondary)
            .help(ZoomOverlay.photoHint)
            .disabled(!editable)
        }
    }

    /// The zoom: a hint while there is none, its size and a clear button once there is.
    @ViewBuilder
    private var pictureControls: some View {
        let e = model.selectedEdit
        let k = model.keymap
        if let z = e.zoom {
            Button { model.perform(.clearZoom, from: "Clear Zoom button") } label: {
                Label("Zoom " + (model.selectedDisplay.map { z.label(in: $0) } ?? ""), systemImage: "xmark.circle.fill")
            }
            .buttonStyle(.borderless)
            .foregroundStyle(Color.orange)
            .help("Click to clear the zoom (\(k.label(.clearZoom))). Drag on the video to zoom in further.")
        } else {
            Button { model.flash(ZoomOverlay.hint) } label: {
                Label("Zoom", systemImage: "plus.viewfinder")
            }
            .buttonStyle(.borderless)
            .foregroundStyle(Color.secondary)
            .help(ZoomOverlay.hint)
        }
    }
}

/// Under a photo: what is staged for it, the keys, and the status line.
struct PhotoBar: View {
    @ObservedObject var model: AppModel

    var body: some View {
        let e = model.selectedEdit
        let k = model.keymap
        HStack(spacing: 12) {
            if e.deleted {
                chip("To Trash", color: .red)
            } else {
                if e.turns != 0 { chip("Rotate \(AppModel.turnLabel(e.turns))", color: .orange) }
                if let z = e.zoom, let d = model.selectedDisplay { chip("Crop to \(z.label(in: d, even: false))", color: .orange) }
            }
            Text("\(k.label(.toggleDelete)) delete · \(k.label(.turn)) / \(k.label(.turnLeft)) rotate · drag to crop · ⌘S apply")
                .font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
            Spacer(minLength: 8)
            Text(model.status)
                .font(.system(size: 12)).foregroundStyle(.secondary)
                .lineLimit(1).truncationMode(.tail)
        }
        .frame(height: 22)
    }

    private func chip(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(color.opacity(0.22), in: Capsule())
            .foregroundStyle(color)
    }
}

struct TransportBar: View {
    @ObservedObject var model: AppModel
    @ObservedObject var player: PlayerModel

    var body: some View {
        HStack(spacing: 12) {
            Button { model.togglePlay() } label: {
                Image(systemName: player.isPlaying ? "pause.fill" : "play.fill").frame(width: 18)
            }
            .buttonStyle(.borderless)
            .help("Play / pause; pausing turns autoplay off (\(model.keymap.label(.playPause)))")

            Text(player.timecode(player.currentSeconds))
                .font(.system(size: 20, weight: .semibold, design: .monospaced))
            Text("/ " + player.timecode(player.duration))
                .font(.system(size: 13, design: .monospaced)).foregroundStyle(.secondary)

            if player.speed != 1 { chip(player.speedLabel, color: .blue) }
            chip(model.autoplay ? "Autoplay" : "Autoplay off", color: model.autoplay ? .green : .gray)
                .help("Selecting a clip plays it while autoplay is on; SPACE pauses (off) and plays (on)")
            Button { model.toggleSectionsOnly() } label: {
                chip(sectionsLabel, color: model.sectionsOnly && !player.sections.isEmpty ? .indigo : .gray)
            }
            .buttonStyle(.plain)
            .help("Sections only: play just the coloured ranges (and what the library holds), jumping over the grey; "
                  + "a clip with none plays whole. A playhead you put in the grey plays the grey. "
                  + "(\(model.keymap.label(.sectionsOnly)))")
            Button { model.toggleLoop() } label: {
                chip(model.loop ? "Loop" : "Loop off", color: model.loop ? .mint : .gray)
            }
            .buttonStyle(.plain)
            .help("Loop: at the end, start over (from the first section when sections only is on; "
                  + "with a sequence in focus, from its first beat). (\(model.keymap.label(.loop)))")
            FocusMenu(model: model)

            if let summary = cropSummary { chip(summary, color: .orange) }

            Spacer(minLength: 8)
            Text(model.status)
                .font(.system(size: 12)).foregroundStyle(.secondary)
                .lineLimit(1).truncationMode(.tail)
        }
    }

    private var sectionsLabel: String {
        guard model.sectionsOnly else { return "Whole clip" }
        let n = player.sections.count
        return n == 0 ? "Whole clip (no ranges)" : "Sections only · \(n)"
    }

    private var cropSummary: String? {
        let r = RangeOps.settle(model.selectedEdit.ranges)
        guard !r.isEmpty, player.duration > 0 else { return nil }
        let kept = r.reduce(0) { $0 + $1.length }
        let what = r.count == 1 ? "crop" : "\(r.count) pieces"
        return "✂ \(what) · keeps \(Format.duration(kept)) of \(Format.duration(player.duration))"
    }

    private func chip(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(color.opacity(0.22), in: Capsule())
            .foregroundStyle(color == .gray ? Color.secondary : color)
    }
}
