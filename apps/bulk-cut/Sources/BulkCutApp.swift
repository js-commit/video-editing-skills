import AppKit
import SwiftUI

/// Info.plist's CFBundleIdentifier: it names the log subsystem and the app's
/// Application Support and Caches folders, so a fork changes it in one place.
let bundleID = Bundle.main.bundleIdentifier ?? "bulkcut"

final class AppDelegate: NSObject, NSApplicationDelegate {
    static var pendingOpen: URL?
    static weak var model: AppModel?

    /// A folder, video or photo dropped on the Dock icon, or "Open With".
    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first else { return }
        if let m = Self.model { m.open(url: url) } else { Self.pendingOpen = url }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        Self.model?.saveNow()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.activate(ignoringOtherApps: true)
        Task.detached(priority: .background) { MediaCache.prune() }
        // Launched with a path argument (`BulkCut.app/Contents/MacOS/BulkCut
        // <folder>`), AppKit hands the path over as a document to open and
        // SwiftUI then skips the main window; open it from its Window menu item.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            guard Self.model?.window == nil,
                  !NSApp.windows.contains(where: { $0.isVisible && $0.canBecomeMain }),
                  let item = NSApp.windowsMenu?.items.first(where: { $0.title == "BulkCut" }),
                  let action = item.action else { return }
            NSApp.sendAction(action, to: item.target, from: item)
        }
    }
}

@main
struct BulkCutApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        Window("BulkCut", id: "main") {
            ContentView(model: model)
                .onAppear {
                    AppDelegate.model = model
                    if let u = AppDelegate.pendingOpen { AppDelegate.pendingOpen = nil; model.open(url: u) }
                }
        }
        .defaultSize(width: 1600, height: 1000)
        .windowResizability(.contentMinSize)
        .commands { AppCommands(model: model, keymap: Keymap.shared) }

        Settings {
            SettingsView(keymap: Keymap.shared)
        }
    }
}

struct AppCommands: Commands {
    @ObservedObject var model: AppModel
    @ObservedObject var keymap: Keymap

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("Open Folder…") { model.openPanel() }
                .keyboardShortcut("o", modifiers: .command)
            Menu("Open Recent") {
                ForEach(model.recents, id: \.self) { url in
                    Button(url.lastPathComponent) { model.open(url: url) }
                }
                if model.recents.isEmpty {
                    Text("No recent folders")
                } else {
                    Divider()
                    Button("Clear Menu") { model.clearRecents() }
                }
            }
            Divider()
            Button("Reload Folder") { model.reload() }
                .keyboardShortcut("r", modifiers: .command)
                .disabled(model.folder == nil)
            Button("Reveal in Finder") { model.reveal() }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                .disabled(model.selected == nil)
        }
        CommandGroup(replacing: .saveItem) {
            Button(model.applying ? "Applying…" : "Apply Now") { model.applyNow() }
                .keyboardShortcut("s", modifiers: .command)
                .disabled(!model.hasChanges || model.applying)
        }
        CommandGroup(replacing: .undoRedo) {
            Button("Undo") { model.undo() }.keyboardShortcut("z", modifiers: .command)
            Button("Redo") { model.redo() }.keyboardShortcut("z", modifiers: [.command, .shift])
        }
        CommandGroup(before: .toolbar) {
            Button("Bigger Thumbnails") { model.adjustThumbs(1) }.keyboardShortcut("=", modifiers: .command)
            Button("Smaller Thumbnails") { model.adjustThumbs(-1) }.keyboardShortcut("-", modifiers: .command)
            Toggle("Show Notes", isOn: $model.showNotes).keyboardShortcut("i", modifiers: .command)
            Toggle("Include Subfolders", isOn: $model.subfolders)
            Divider()
        }
        // Every action, its current key in the title. Not as a key equivalent:
        // the key monitor handles (and swallows) the keys, so an equivalent
        // would only show in the menu, never fire.
        CommandMenu("Clip") {
            ForEach(Action.Group.allCases, id: \.self) { g in
                ForEach(Action.allCases.filter { $0.group == g }) { a in
                    Button(keymap.bindings[a].map { "\(a.title)  (\($0.label))" } ?? a.title) { model.perform(a) }
                }
                Divider()
            }
            Button("Apply Changes…") { model.openApply() }
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!model.hasChanges || model.applying)
        }
        CommandGroup(replacing: .help) {
            Button("Keyboard Shortcuts") { model.showShortcuts.toggle() }
                .keyboardShortcut("/", modifiers: .command)
            Button("Show Debug Log") { model.showDebugLog() }
        }
    }
}
