import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    static var pendingOpen: URL?
    static weak var controller: ReviewController?

    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first else { return }
        if let c = Self.controller { c.open(url: url) } else { Self.pendingOpen = url }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    /// Quitting with text in the field keeps it as a note.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let c = Self.controller, c.hasDraft { c.addNote() }
        return .terminateNow
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.activate(ignoringOtherApps: true)
        Task.detached(priority: .background) { MediaCache.prune() }
    }
}

@main
struct EditReviewApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var controller = ReviewController()

    var body: some Scene {
        // One window, not a WindowGroup: launching from a double-clicked video
        // could open a second, stacked exactly on the first, and the two
        // ContentViews' focus states (one shared controller) kept knocking the
        // note field out of focus — no typing, no red pulse.
        Window("Edit Review", id: "main") {
            ContentView(controller: controller)
                .onAppear {
                    AppDelegate.controller = controller
                    if let u = AppDelegate.pendingOpen { AppDelegate.pendingOpen = nil; controller.open(url: u) }
                }
        }
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open Video…") { controller.openPanel() }
                    .keyboardShortcut("o", modifiers: .command)
                Button("Open Path from Clipboard") { controller.openFromClipboard() }
                    .keyboardShortcut("o", modifiers: [.command, .shift])
                Menu("Open Recent") {
                    ForEach(controller.recents, id: \.self) { url in
                        Button(url.lastPathComponent) { controller.open(url: url) }
                            .help(url.path)
                    }
                    if controller.recents.isEmpty {
                        Text("No recent videos")
                    } else {
                        Divider()
                        Button("Clear Menu") { controller.clearRecents() }
                    }
                }
            }
            CommandGroup(replacing: .help) {
                Button("Keyboard Shortcuts") { controller.showShortcuts.toggle() }
                    .keyboardShortcut("/", modifiers: .command)
            }
            CommandGroup(before: .toolbar) {     // into the standard View menu
                Button("Bigger Text") { controller.adjustFontSize(by: 2) }
                    .keyboardShortcut("=", modifiers: .command)
                Button("Smaller Text") { controller.adjustFontSize(by: -2) }
                    .keyboardShortcut("-", modifiers: .command)
                Button("Default Text Size") { controller.panelFontSize = 16 }
                    .keyboardShortcut("0", modifiers: .command)
                Picker("Text Size", selection: $controller.panelFontSize) {
                    ForEach(ReviewController.fontSizes, id: \.self) { Text("\(Int($0)) pt").tag($0) }
                }
                Divider()
            }
            CommandMenu("Review") {
                Button("Play / Pause") { controller.togglePlay() }
                Button("Add Note at Playhead") { controller.addNote() }.disabled(!controller.hasDraft)
                Button("Clear Note Field") { controller.clearDraft() }.disabled(controller.draftText.isEmpty)
                Divider()
                Button("Cycle Speed 1× → 1.5× → 1.7× → 2× → 2.5× → 3×") { controller.cycleSpeed() }
                Divider()
                Button("Previous Cut (\(Shortcuts.label(.previousCut)))") { controller.jumpCut(-1) }.disabled(controller.cuts == nil)
                Button("Next Cut (\(Shortcuts.label(.nextCut)))") { controller.jumpCut(1) }.disabled(controller.cuts == nil)
                Button("Previous Change (\(Shortcuts.label(.previousChange)))") { controller.jumpChange(-1) }.disabled(controller.changes == nil)
                Button("Next Change (\(Shortcuts.label(.nextChange)))") { controller.jumpChange(1) }.disabled(controller.changes == nil)
                Button("Forget Which Changes Were Seen") { controller.resetSeenChanges() }.disabled(controller.changes == nil)
                Button(controller.pullingCuts ? "Getting Cuts from Resolve…"
                       : controller.cuts == nil ? "Get Cuts from Resolve" : "Get Cuts from Resolve Again") {
                    controller.pullCutsFromResolve()
                }.disabled(controller.store == nil || controller.pullingCuts)
                Divider()
                Button("Select All Notes (\(Shortcuts.label(.selectAllNotes)) with an empty field)") { controller.selectAllNotes() }
                    .disabled(controller.store?.notes.isEmpty ?? true)
                Button("Archive Selected Notes (\(Shortcuts.label(.archiveNotes)))") { controller.archiveSelected() }.disabled(controller.selection.isEmpty)
                Button("Delete Selected Notes (\(Shortcuts.label(.deleteNote)))") { controller.deleteSelected() }.disabled(controller.selection.isEmpty)
                Button("Undo Last Delete / Note / Archive") { controller.undo() }
                Divider()
                Button("Copy Notes as JSON") { controller.copyNotesJSON() }
                    .keyboardShortcut("c", modifiers: [.command, .shift])
                    .disabled(controller.store?.notes.isEmpty ?? true)
                Divider()
                Button(controller.transcript?.stale == true ? "Transcribe Again (video length changed)"
                       : controller.transcript?.changed == true ? "Transcribe Again (file re-exported)"
                       : "Transcribe") {
                    controller.transcribe()
                }.disabled(!controller.canTranscribe)
                Toggle("Transcribe When a Video Opens", isOn: $controller.autoTranscribe)
                Button("Set Skills Repo Folder…") { controller.pickRepo() }
                Button("Find in Transcript (\(Shortcuts.label(.find)))") { controller.openFind() }.disabled(controller.store == nil)
                Button("Find Next (\(Shortcuts.label(.findNext)))") { controller.findNext(1) }.disabled(controller.found.matches.isEmpty)
                Button("Find Previous (\(Shortcuts.label(.findPrevious)))") { controller.findNext(-1) }.disabled(controller.found.matches.isEmpty)
                Button("Reveal Transcript in Finder") {
                    if let u = controller.sidecarURL { NSWorkspace.shared.activateFileViewerSelecting([u]) }
                }.disabled(controller.transcript == nil)
                Divider()
                Button("Reveal Review Folder in Finder") {
                    if let d = controller.store?.reviewDir { NSWorkspace.shared.activateFileViewerSelecting([d]) }
                }.disabled(controller.store?.reviewDirExists != true)
            }
        }
    }
}
