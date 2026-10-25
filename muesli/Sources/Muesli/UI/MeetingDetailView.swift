import SwiftUI

enum DetailTab: String, CaseIterable {
    case notes = "Notes"
    case transcript = "Transcript"
    case enhanced = "Enhanced"
    case ask = "Ask"

    var icon: String {
        switch self {
        case .notes: return "square.and.pencil"
        case .transcript: return "text.quote"
        case .enhanced: return "sparkles"
        case .ask: return "bubble.left.and.text.bubble.right"
        }
    }
}

struct MeetingDetailView: View {
    @EnvironmentObject private var store: MeetingStore
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var recorder: RecordingController

    let meetingID: UUID
    @State private var tab: DetailTab = .notes
    @State private var titleDraft = ""
    @State private var enhancing = false
    @State private var enhanceError: String?

    private var meeting: Meeting? { store.meeting(meetingID) }
    private var isLive: Bool { recorder.recordingMeetingID == meetingID }

    var body: some View {
        if let meeting {
            VStack(spacing: 0) {
                header(meeting)
                Divider()
                if isLive {
                    RecordBar()
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                    Divider()
                }
                content(meeting)
            }
            .toolbar { toolbarContent(meeting) }
            .onAppear {
                titleDraft = meeting.title
                if isLive { tab = .notes }
            }
            .onChange(of: meeting.title) { _, new in titleDraft = new }
            .alert("Enhance failed", isPresented: Binding(
                get: { enhanceError != nil },
                set: { if !$0 { enhanceError = nil } }
            )) {
                Button("OK") { enhanceError = nil }
            } message: {
                Text(enhanceError ?? "")
            }
        } else {
            EmptyDetailView()
        }
    }

    // MARK: - Header

    private func header(_ meeting: Meeting) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            TextField("Meeting title", text: $titleDraft)
                .textFieldStyle(.plain)
                .font(.title.weight(.semibold))
                .onSubmit { store.updateTitle(meetingID, title: titleDraft) }

            HStack(spacing: 8) {
                Text(meeting.createdAt, format: .dateTime.weekday(.wide).month().day().hour().minute())
                if meeting.durationSeconds > 0 {
                    Text("·")
                    Text(formatClock(meeting.durationSeconds))
                }
                Text("·")
                Menu {
                    ForEach(NoteTemplate.all) { t in
                        Button {
                            store.updateTemplate(meetingID, templateID: t.id)
                        } label: {
                            Label(t.name, systemImage: t.icon)
                        }
                    }
                } label: {
                    Label(NoteTemplate.byID(meeting.templateID).name, systemImage: NoteTemplate.byID(meeting.templateID).icon)
                        .font(.caption)
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                if let warning = recorder.systemAudioWarning, isLive {
                    Label(warning, systemImage: "speaker.slash")
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .lineLimit(1)
                        .help(warning)
                }
                if let warning = recorder.micWarning, isLive {
                    Label(warning, systemImage: "mic.slash")
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .lineLimit(1)
                        .help(warning)
                }
                Spacer()
            }
            .font(.callout)
            .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 10)
    }

    // MARK: - Tabs

    @ViewBuilder
    private func content(_ meeting: Meeting) -> some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                ForEach(DetailTab.allCases, id: \.self) { t in
                    Label(t.rawValue, systemImage: t.icon).tag(t)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 16)
            .padding(.vertical, 8)

            Divider()

            switch tab {
            case .notes:
                NotesEditor(meetingID: meetingID)
            case .transcript:
                TranscriptView(meetingID: meetingID)
            case .enhanced:
                EnhancedNotesView(meetingID: meetingID, enhancing: enhancing, onEnhance: { enhance() })
            case .ask:
                AskView(meetingID: meetingID)
            }
        }
    }

    // MARK: - Toolbar

    @ToolbarContentBuilder
    private func toolbarContent(_ meeting: Meeting) -> some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            if isLive {
                Button {
                    Task { await recorder.stop() }
                } label: {
                    Label("Stop", systemImage: "stop.circle.fill")
                        .foregroundStyle(.red)
                }
                .help("Stop recording (⌘.)")
            } else {
                Button {
                    Task { await recorder.start(meetingID: meetingID) }
                } label: {
                    Label("Record", systemImage: "record.circle")
                }
                .help("Record into this meeting")
                .disabled(recorder.isRecording)
            }

            Button {
                enhance()
            } label: {
                if enhancing {
                    ProgressView().controlSize(.small)
                } else {
                    Label("Enhance", systemImage: "sparkles")
                }
            }
            .help("Blend your rough notes with the transcript into polished notes")
            .disabled(enhancing || isLive || (!meeting.hasTranscript && meeting.notesMD.isEmpty))

            Menu {
                Button("Copy enhanced notes") { copy(meeting.enhancedMD ?? "") }
                    .disabled(meeting.enhancedMD == nil)
                Button("Copy transcript") { copy(MeetingStore.transcriptMarkdown(meeting)) }
                    .disabled(!meeting.hasTranscript)
                Button("Copy rough notes") { copy(meeting.notesMD) }
                    .disabled(meeting.notesMD.isEmpty)
                Divider()
                Button("Reveal files in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting([store.folder(for: meeting)])
                }
                Divider()
                Button("Re-transcribe from audio") {
                    recorder.retranscribe(meetingID: meetingID)
                }
                .disabled(isLive)
            } label: {
                Label("More", systemImage: "ellipsis.circle")
            }
        }
    }

    // MARK: - Actions

    private func enhance() {
        guard let meeting, !enhancing else { return }
        enhancing = true
        Task {
            defer { enhancing = false }
            do {
                let md = try await Enhancer(settings: settings).enhance(meeting: meeting)
                store.setEnhanced(meetingID, markdown: md)
                tab = .enhanced
            } catch {
                enhanceError = error.localizedDescription
            }
        }
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}
