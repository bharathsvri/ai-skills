import SwiftUI
import AppKit

@main
enum MuesliMain {
    static func main() {
        if MuesliCLI.runIfNeeded() { return }
        MuesliApp.main()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let controller = RecordingController.shared, controller.isRecording {
            controller.emergencyStop()
        }
        return .terminateNow
    }
}

struct MuesliApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store: MeetingStore
    @StateObject private var settings: AppSettings
    @StateObject private var recorder: RecordingController

    init() {
        let store = MeetingStore()
        let settings = AppSettings()
        _store = StateObject(wrappedValue: store)
        _settings = StateObject(wrappedValue: settings)
        _recorder = StateObject(wrappedValue: RecordingController(store: store, settings: settings))
    }

    var body: some Scene {
        WindowGroup(id: "main") {
            ContentView()
                .environmentObject(store)
                .environmentObject(settings)
                .environmentObject(recorder)
                .frame(minWidth: 960, minHeight: 620)
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Meeting & Record") {
                    Task { await RecordingController.shared?.startNewMeeting() }
                }
                .keyboardShortcut("n", modifiers: .command)

                Button("Stop Recording") {
                    Task { await RecordingController.shared?.stop() }
                }
                .keyboardShortcut(".", modifiers: .command)
            }
        }

        Settings {
            SettingsView()
                .environmentObject(settings)
        }

        MenuBarExtra {
            MenuBarContent()
                .environmentObject(store)
                .environmentObject(recorder)
        } label: {
            Image(systemName: recorder.isRecording ? "waveform.circle.fill" : "waveform")
        }
    }
}

struct MenuBarContent: View {
    @EnvironmentObject private var store: MeetingStore
    @EnvironmentObject private var recorder: RecordingController
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if case .recording(let id, let started) = recorder.state {
            Text("Recording — \(store.meeting(id)?.title ?? "meeting")")
            Text(started, style: .timer)
            Button("Stop Recording") {
                Task { await recorder.stop() }
            }
        } else {
            Button("Start New Meeting") {
                Task { await recorder.startNewMeeting() }
            }
        }
        Divider()
        Button("Open Muesli") {
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
        Divider()
        Button("Quit Muesli") {
            NSApp.terminate(nil)
        }
    }
}
