import SwiftUI

extension Color {
    /// Toasted-oat brand accent.
    static let oat = Color(red: 0.83, green: 0.52, blue: 0.24)
}

struct ContentView: View {
    @EnvironmentObject private var store: MeetingStore
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var recorder: RecordingController

    @State private var selectedID: UUID?
    @State private var showSetup = false

    var body: some View {
        NavigationSplitView {
            SidebarView(selectedID: $selectedID, showSetup: $showSetup)
                .navigationSplitViewColumnWidth(min: 240, ideal: 280, max: 360)
        } detail: {
            if let meeting = store.meeting(selectedID) {
                MeetingDetailView(meetingID: meeting.id)
                    .id(meeting.id)
            } else {
                EmptyDetailView()
            }
        }
        .onAppear {
            selectedID = store.meetings.first?.id
            if SetupStatus.current(settings: settings).hasBlockers {
                showSetup = true
            }
        }
        .onChange(of: recorder.recordingMeetingID) { _, newValue in
            if let newValue { selectedID = newValue }
        }
        .sheet(isPresented: $showSetup) {
            SetupSheet()
                .environmentObject(settings)
        }
        .alert("Muesli", isPresented: Binding(
            get: { recorder.lastError != nil },
            set: { if !$0 { recorder.lastError = nil } }
        )) {
            Button("OK") { recorder.lastError = nil }
        } message: {
            Text(recorder.lastError ?? "")
        }
    }
}

struct EmptyDetailView: View {
    @EnvironmentObject private var recorder: RecordingController

    var body: some View {
        VStack(spacing: 14) {
            Text("🥣")
                .font(.system(size: 56))
            Text("Muesli")
                .font(.largeTitle.weight(.semibold))
            Text("The open-source meeting notepad.\nRecord a call, type rough notes, get polished ones.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button {
                Task { await recorder.startNewMeeting() }
            } label: {
                Label("Start a meeting", systemImage: "record.circle")
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
            }
            .buttonStyle(.borderedProminent)
            .tint(.oat)
            .keyboardShortcut(.defaultAction)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
