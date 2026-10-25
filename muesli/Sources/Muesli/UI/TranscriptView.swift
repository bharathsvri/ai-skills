import SwiftUI

struct TranscriptView: View {
    @EnvironmentObject private var store: MeetingStore
    @EnvironmentObject private var recorder: RecordingController
    let meetingID: UUID

    @State private var autoScroll = true

    private var meeting: Meeting? { store.meeting(meetingID) }
    private var isLive: Bool { recorder.recordingMeetingID == meetingID }

    var body: some View {
        if let meeting, meeting.hasTranscript {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 14) {
                            ForEach(meeting.transcript.coalesced(), id: \.id) { group in
                                TranscriptGroupView(group: group)
                                    .id(group.id)
                            }
                            if isLive {
                                HStack(spacing: 8) {
                                    ProgressView().controlSize(.small)
                                    Text(recorder.pendingChunks > 0
                                         ? "Transcribing \(recorder.pendingChunks) chunk\(recorder.pendingChunks == 1 ? "" : "s")…"
                                         : "Listening…")
                                        .font(.callout)
                                        .foregroundStyle(.secondary)
                                }
                                .id("live-tail")
                            }
                        }
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .onChange(of: meeting.transcript.count) { _, _ in
                        guard autoScroll, isLive else { return }
                        withAnimation {
                            proxy.scrollTo("live-tail", anchor: .bottom)
                        }
                    }
                }
                if isLive {
                    Divider()
                    Toggle("Auto-scroll", isOn: $autoScroll)
                        .toggleStyle(.checkbox)
                        .font(.caption)
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                }
            }
        } else {
            VStack(spacing: 10) {
                Image(systemName: isLive ? "waveform" : "text.quote")
                    .font(.system(size: 34))
                    .foregroundStyle(.tertiary)
                    .symbolEffect(.variableColor.iterative, isActive: isLive)
                Text(isLive
                     ? (recorder.pendingChunks > 0 ? "Transcribing the first chunk…" : "Listening — the transcript appears in ~20-second chunks.")
                     : "No transcript yet. Record this meeting, or use ⋯ → Re-transcribe if audio files exist.")
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding()
        }
    }
}

struct TranscriptGroupView: View {
    let group: (id: UUID, speaker: Speaker, start: Double, text: String)

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(group.speaker.label)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(group.speaker == .me ? Color.oat : Color.blue)
                Text(formatClock(group.start))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.tertiary)
            }
            Text(group.text)
                .font(.system(size: 13.5))
                .lineSpacing(3)
                .textSelection(.enabled)
        }
    }
}
