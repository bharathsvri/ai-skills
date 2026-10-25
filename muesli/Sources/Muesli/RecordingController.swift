import Foundation
import SwiftUI

/// Orchestrates a recording: permissions → mic + system audio capture →
/// chunker → transcription pipeline → store. One recording at a time.
@MainActor
final class RecordingController: ObservableObject {
    enum State: Equatable {
        case idle
        case recording(meetingID: UUID, started: Date)
    }

    @Published private(set) var state: State = .idle
    @Published var micLevel: Float = 0
    @Published var sysLevel: Float = 0
    @Published var pendingChunks: Int = 0
    @Published var lastError: String?
    /// Set when system audio couldn't start but the mic is still recording.
    @Published var systemAudioWarning: String?
    /// Mic status worth showing (echo-cancel fallback, silent input device).
    @Published var micWarning: String?

    let store: MeetingStore
    let settings: AppSettings
    private(set) var pipeline: TranscriptionPipeline!

    private var session: RecordingSession?
    private var mic: MicRecorder?
    private var system: SystemAudioRecorder?

    static private(set) weak var shared: RecordingController?

    var isRecording: Bool {
        if case .recording = state { return true }
        return false
    }

    var recordingMeetingID: UUID? {
        if case .recording(let id, _) = state { return id }
        return nil
    }

    init(store: MeetingStore, settings: AppSettings) {
        self.store = store
        self.settings = settings
        RecordingController.shared = self

        pipeline = TranscriptionPipeline(
            settings: settings,
            onSegments: { meetingID, segments, replace in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    if replace { self.store.clearTranscript(meetingID) }
                    self.store.appendSegments(meetingID, segments: segments)
                }
            },
            onPending: { count in
                Task { @MainActor [weak self] in self?.pendingChunks = count }
            },
            onError: { message in
                Task { @MainActor [weak self] in self?.lastError = message }
            }
        )
    }

    // MARK: - Start / stop

    /// Creates a meeting and starts recording into it.
    func startNewMeeting(captureSystemAudio: Bool? = nil) async {
        guard !isRecording else { return }
        let meeting = store.createMeeting()
        await start(meetingID: meeting.id, captureSystemAudio: captureSystemAudio)
    }

    func start(meetingID: UUID, captureSystemAudio: Bool? = nil) async {
        guard !isRecording, let meeting = store.meeting(meetingID) else { return }
        lastError = nil
        systemAudioWarning = nil
        micWarning = nil

        guard await Permissions.ensureMicAccess() else {
            lastError = "Microphone access is required to record. Enable it in System Settings → Privacy & Security → Microphone."
            return
        }

        let wantSystem = captureSystemAudio ?? settings.captureSystemAudio
        let folder = store.folder(for: meeting)

        do {
            let session = try RecordingSession(
                meetingID: meeting.id,
                folder: folder,
                chunkSeconds: settings.chunkSeconds,
                captureSystem: wantSystem
            )
            session.onChunk = { [pipeline] job in
                Task { await pipeline?.enqueue(job) }
            }
            session.onLevels = { [weak self] micLevel, sysLevel in
                Task { @MainActor in
                    self?.micLevel = micLevel
                    self?.sysLevel = sysLevel
                }
            }
            self.session = session

            // Mic first: a voice-processing attempt may take a few seconds once,
            // and toggling it reconfigures the input device — get the mic settled
            // before system audio starts so the two stream timelines stay aligned.
            let mic = MicRecorder()
            mic.onSamples = { [weak session] in session?.appendMic($0) }
            mic.onNotice = { [weak self] message in
                Task { @MainActor in self?.micWarning = message }
            }
            mic.onVoiceProcessingFailed = { [weak self] in
                Task { @MainActor in self?.settings.vpKnownBad = true }
            }
            try await mic.start(echoCancellation: settings.echoCancellation && !settings.vpKnownBad)
            self.mic = mic

            if wantSystem {
                let sys = SystemAudioRecorder()
                sys.onSamples = { [weak session] in session?.appendSystem($0) }
                sys.onStoppedWithError = { [weak self] error in
                    Task { @MainActor in
                        self?.systemAudioWarning = "System audio stopped: \(error.localizedDescription)"
                    }
                }
                do {
                    try await sys.start()
                    self.system = sys
                } catch {
                    systemAudioWarning = (error as? SystemAudioError)?.errorDescription
                        ?? "System audio unavailable (\(error.localizedDescription)) — recording your mic only."
                }
            }

            state = .recording(meetingID: meeting.id, started: Date())
        } catch {
            await teardownCapture()
            lastError = "Couldn't start recording: \(error.localizedDescription)"
        }
    }

    func stop() async {
        guard case .recording(let meetingID, let started) = state else { return }
        mic?.stop()
        await system?.stop()
        let duration = session?.finish() ?? Date().timeIntervalSince(started)
        store.setDuration(meetingID, seconds: max(duration, Date().timeIntervalSince(started)))
        await teardownCapture()
        state = .idle
        micLevel = 0
        sysLevel = 0
    }

    /// Synchronous best-effort stop for app termination: finalizes WAV headers.
    nonisolated func emergencyStop() {
        Task { @MainActor in
            await self.stop()
        }
        // Give the file finalization a beat before the process exits.
        Thread.sleep(forTimeInterval: 0.4)
    }

    private func teardownCapture() async {
        mic = nil
        system = nil
        session = nil
    }

    // MARK: - Retranscribe

    func retranscribe(meetingID: UUID) {
        guard let meeting = store.meeting(meetingID), !isRecording else { return }
        let folder = store.folder(for: meeting)
        Task { await pipeline.retranscribe(meetingID: meetingID, folder: folder) }
    }
}
