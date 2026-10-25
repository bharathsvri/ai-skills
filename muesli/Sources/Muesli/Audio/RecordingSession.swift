import Foundation

/// One chunk of audio handed to the transcription pipeline.
struct TranscriptionJob {
    let meetingID: UUID
    var micURL: URL?
    var micStart: Double = 0
    var sysURL: URL?
    var sysStart: Double = 0
    var timeout: Double = 240
    /// Full-file retranscription jobs keep their source audio and replace the transcript.
    var keepFiles = false
    var replaceTranscript = false
}

/// Owns the live audio of one recording: writes full-session WAVs to the meeting
/// folder, accumulates per-stream chunks, and cuts a chunk when it's long enough
/// and hits a moment of silence (so words aren't split mid-sentence).
final class RecordingSession {
    private let queue = DispatchQueue(label: "muesli.chunker")
    private let meetingID: UUID
    private let folder: URL
    private let sampleRate = 16000
    private let minChunkSeconds: Double
    private let maxChunkSeconds: Double

    private var micChunk: [Int16] = []
    private var sysChunk: [Int16] = []
    private var micFlushedSamples = 0
    private var sysFlushedSamples = 0
    private var micTotalSamples = 0
    private var sysTotalSamples = 0
    private var chunkIndex = 0
    private var stopped = false

    private var micWriter: WavWriter?
    private var sysWriter: WavWriter?

    var onChunk: ((TranscriptionJob) -> Void)?
    var onLevels: ((Float, Float) -> Void)?

    var micFileURL: URL { folder.appendingPathComponent("mic.wav") }
    var systemFileURL: URL { folder.appendingPathComponent("system.wav") }

    init(meetingID: UUID, folder: URL, chunkSeconds: Double, captureSystem: Bool) throws {
        self.meetingID = meetingID
        self.folder = folder
        self.minChunkSeconds = max(10, chunkSeconds)
        self.maxChunkSeconds = max(10, chunkSeconds) + 15
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        micWriter = try WavWriter(url: micFileURL, sampleRate: sampleRate)
        if captureSystem {
            sysWriter = try WavWriter(url: systemFileURL, sampleRate: sampleRate)
        }
    }

    func appendMic(_ samples: [Int16]) {
        queue.async { [self] in
            guard !stopped else { return }
            micChunk.append(contentsOf: samples)
            micTotalSamples += samples.count
            micWriter?.append(samples)
            publishLevels(mic: samples)
            maybeFlush(force: false)
        }
    }

    func appendSystem(_ samples: [Int16]) {
        queue.async { [self] in
            guard !stopped else { return }
            sysChunk.append(contentsOf: samples)
            sysTotalSamples += samples.count
            sysWriter?.append(samples)
            publishLevels(sys: samples)
            maybeFlush(force: false)
        }
    }

    /// Stops the session, flushes the final chunk, finalizes the WAV headers,
    /// and returns the recorded duration in seconds.
    func finish() -> Double {
        var duration: Double = 0
        queue.sync { [self] in
            stopped = true
            flush()
            micWriter?.finalize()
            sysWriter?.finalize()
            duration = Double(max(micTotalSamples, sysTotalSamples)) / Double(sampleRate)
        }
        return duration
    }

    // MARK: - Chunking

    private func maybeFlush(force: Bool) {
        let longestSeconds = Double(max(micChunk.count, sysChunk.count)) / Double(sampleRate)
        guard longestSeconds >= minChunkSeconds || force else { return }
        if !force && longestSeconds < maxChunkSeconds {
            // Wait for a breath: both streams quiet in the trailing 300 ms.
            guard AudioMath.trailingQuiet(micChunk), AudioMath.trailingQuiet(sysChunk) else { return }
        }
        flush()
    }

    private func flush() {
        guard !micChunk.isEmpty || !sysChunk.isEmpty else { return }
        chunkIndex += 1
        var job = TranscriptionJob(meetingID: meetingID)
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("muesli-chunks", isDirectory: true)
        try? FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)

        // A stream with no real signal in this chunk is skipped entirely —
        // that avoids Whisper hallucinating text on silence.
        if micChunk.count > sampleRate, AudioMath.rms(micChunk) > 120 {
            let url = tmpDir.appendingPathComponent("\(meetingID.uuidString)-\(chunkIndex)-mic.wav")
            if (try? WavWriter.write(samples: micChunk, to: url, sampleRate: sampleRate)) != nil {
                job.micURL = url
                job.micStart = Double(micFlushedSamples) / Double(sampleRate)
            }
        }
        if sysChunk.count > sampleRate, AudioMath.rms(sysChunk) > 120 {
            let url = tmpDir.appendingPathComponent("\(meetingID.uuidString)-\(chunkIndex)-sys.wav")
            if (try? WavWriter.write(samples: sysChunk, to: url, sampleRate: sampleRate)) != nil {
                job.sysURL = url
                job.sysStart = Double(sysFlushedSamples) / Double(sampleRate)
            }
        }

        micFlushedSamples += micChunk.count
        sysFlushedSamples += sysChunk.count
        micChunk.removeAll(keepingCapacity: true)
        sysChunk.removeAll(keepingCapacity: true)

        if job.micURL != nil || job.sysURL != nil {
            onChunk?(job)
        }
    }

    private var lastLevelPublish = Date.distantPast
    private var pendingMicLevel: Float = 0
    private var pendingSysLevel: Float = 0

    private func publishLevels(mic: [Int16]? = nil, sys: [Int16]? = nil) {
        if let mic { pendingMicLevel = Float(min(1.0, AudioMath.rms(mic) / 6000)) }
        if let sys { pendingSysLevel = Float(min(1.0, AudioMath.rms(sys) / 6000)) }
        let now = Date()
        guard now.timeIntervalSince(lastLevelPublish) > 0.1 else { return }
        lastLevelPublish = now
        onLevels?(pendingMicLevel, pendingSysLevel)
    }
}
