import SwiftUI

/// Live recording strip: pulsing dot, elapsed time, input level meters,
/// transcription backlog, stop button.
struct RecordBar: View {
    @EnvironmentObject private var recorder: RecordingController
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 14) {
            Circle()
                .fill(.red)
                .frame(width: 10, height: 10)
                .opacity(pulse ? 0.35 : 1)
                .animation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true), value: pulse)
                .onAppear { pulse = true }

            if case .recording(_, let started) = recorder.state {
                Text(started, style: .timer)
                    .font(.title3.monospacedDigit().weight(.medium))
            }

            LevelMeter(label: "Mic", level: recorder.micLevel, tint: .oat)
            LevelMeter(label: "System", level: recorder.sysLevel, tint: .blue)

            Spacer()

            if recorder.pendingChunks > 0 {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text("\(recorder.pendingChunks) chunk\(recorder.pendingChunks == 1 ? "" : "s")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Button {
                Task { await recorder.stop() }
            } label: {
                Label("Stop", systemImage: "stop.fill")
            }
            .buttonStyle(.borderedProminent)
            .tint(.red)
            .keyboardShortcut(".", modifiers: .command)
        }
    }
}

struct LevelMeter: View {
    let label: String
    let level: Float
    let tint: Color

    var body: some View {
        HStack(spacing: 6) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.08))
                    Capsule()
                        .fill(tint)
                        .frame(width: max(3, geo.size.width * CGFloat(min(1, level))))
                        .animation(.linear(duration: 0.1), value: level)
                }
            }
            .frame(width: 70, height: 6)
        }
    }
}
