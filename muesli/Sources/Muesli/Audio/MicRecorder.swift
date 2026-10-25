import Foundation
import AVFoundation

enum MicError: LocalizedError {
    case invalidInputFormat

    var errorDescription: String? {
        "The input device reported an invalid audio format. Check System Settings → Sound → Input."
    }
}

/// Captures the microphone via AVAudioEngine and emits 16 kHz mono Int16 samples.
///
/// Echo cancellation uses Apple's voice-processing unit (AUVoiceIO), which keeps
/// call audio played through speakers out of the "Me" stream — but AUVoiceIO is
/// temperamental on macOS: on some systems enabling it stalls for minutes, fails
/// (kAudioUnitErr_FailedInitialization), or yields an engine that produces pure
/// silence. Toggling it also reconfigures the *shared* input device, so a
/// voice-processing attempt must never run beside a live raw engine.
///
/// Strategy — strictly sequential, deadline-bound:
///
///  1. If echo cancellation is requested, build the voice-processing engine
///     FIRST, on a throwaway thread with a hard deadline. The caller awaits
///     (a suspended task, never a blocked thread).
///  2. Deadline missed or error → `onVoiceProcessingFailed` fires (the app
///     remembers and skips the attempt on future recordings) and the raw
///     engine starts instead. Raw bring-up is fast and reliable.
///  3. A watchdog inspects the first ~2.5 s of live audio: a silent
///     voice-processed engine is swapped back to raw; a silent raw engine
///     produces a visible notice (device/level problem).
///  4. A configuration-change observer restarts capture on the raw path when
///     the input device changes mid-recording (AirPods connect, dock unplug…).
///
/// Buffer routing is guarded by generation tokens so an abandoned or stale
/// engine can never leak samples into the live stream.
final class MicRecorder {
    private var engine: AVAudioEngine?
    private var converter = StreamConverter()
    private(set) var voiceProcessingActive = false
    private var configObserver: NSObjectProtocol?

    /// Monotonic token source; `generation` holds the currently-live token.
    private let genCounter = Atomic(0)
    private let generation = Atomic(-1)
    private let restarting = Atomic(false)
    private let stopped = Atomic(false)

    // Watchdog state — only the live generation's tap thread touches it.
    private var watchdogArmed = false
    private var armedAt: Date?
    private var emittedSamples = 0
    private var maxAbs = 0

    var onSamples: (([Int16]) -> Void)?
    /// Human-readable status changes worth surfacing in the UI.
    var onNotice: ((String) -> Void)?
    /// Voice processing stalled, errored, or produced silence — the app should
    /// remember this and skip the attempt on future recordings.
    var onVoiceProcessingFailed: (() -> Void)?

    /// Brings up capture. Suspends (without blocking any thread) for at most
    /// ~5 s when a voice-processing attempt is requested; raw-only starts are
    /// effectively instant.
    func start(echoCancellation: Bool) async throws {
        stopped.value = false

        if echoCancellation {
            if let (vpEngine, gen) = await buildVoiceProcessedEngine(deadline: 5.0) {
                if stopped.value {
                    Self.discard(vpEngine, voiceProcessed: true)
                    return
                }
                adopt(vpEngine, gen: gen, voiceProcessing: true)
                return
            }
            if stopped.value { return }
            onVoiceProcessingFailed?()
            onNotice?("Echo cancellation isn't working on this Mac — recording the raw mic. Headphones avoid echo on speaker calls.")
        }

        try startRawEngine()
    }

    func stop() {
        stopped.value = true
        tearDownEngine()
    }

    // MARK: - Raw engine

    private func startRawEngine() throws {
        tearDownEngine()

        let gen = genCounter.next()
        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw MicError.invalidInputFormat
        }
        converter = StreamConverter()
        armWatchdog()
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            self?.handle(buffer, gen: gen)
        }
        engine.prepare()
        try engine.start()

        self.engine = engine
        voiceProcessingActive = false
        generation.value = gen
        wireConfigObserver(for: engine)
    }

    // MARK: - Voice-processing bring-up (deadline-bound)

    /// Builds a complete, running voice-processing engine on a throwaway thread.
    /// Returns nil if it errors or misses the deadline; an engine that finishes
    /// late is torn down by its own thread.
    private func buildVoiceProcessedEngine(deadline: Double) async -> (AVAudioEngine, Int)? {
        final class ProbeBox {
            let lock = NSLock()
            var abandoned = false
            var engine: AVAudioEngine?
        }

        let box = ProbeBox()
        let sem = DispatchSemaphore(value: 0)
        let gen = genCounter.next() // live only once adopted

        let thread = Thread { [weak self] in
            let engine = AVAudioEngine()
            do {
                let input = engine.inputNode
                try input.setVoiceProcessingEnabled(true) // ← the call that stalls/fails on broken systems
                if #available(macOS 14.0, *) {
                    input.voiceProcessingOtherAudioDuckingConfiguration =
                        AVAudioVoiceProcessingOtherAudioDuckingConfiguration(
                            enableAdvancedDucking: false,
                            duckingLevel: .min
                        )
                }
                // AUVoiceIO is full-duplex; keep its render side alive (muted).
                engine.mainMixerNode.outputVolume = 0
                let format = input.outputFormat(forBus: 0)
                guard format.sampleRate > 0, format.channelCount > 0 else {
                    throw MicError.invalidInputFormat
                }
                input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
                    self?.handle(buffer, gen: gen)
                }
                engine.prepare()
                try engine.start()

                box.lock.lock()
                if box.abandoned {
                    box.lock.unlock()
                    Self.discard(engine, voiceProcessed: true)
                    return
                }
                box.engine = engine
                box.lock.unlock()
                sem.signal()
            } catch {
                NSLog("Muesli: voice-processing bring-up failed: \(error.localizedDescription)")
                box.lock.lock()
                let abandoned = box.abandoned
                box.lock.unlock()
                engine.stop()
                if !abandoned { sem.signal() }
            }
        }
        thread.name = "muesli.vp.bringup"
        thread.start()

        return await withCheckedContinuation { cont in
            DispatchQueue.global(qos: .userInitiated).async {
                if sem.wait(timeout: .now() + deadline) == .timedOut {
                    box.lock.lock()
                    box.abandoned = true
                    box.lock.unlock()
                    cont.resume(returning: nil)
                    return
                }
                box.lock.lock()
                let engine = box.engine
                box.lock.unlock()
                cont.resume(returning: engine.map { ($0, gen) })
            }
        }
    }

    private func adopt(_ newEngine: AVAudioEngine, gen: Int, voiceProcessing: Bool) {
        tearDownEngine()
        engine = newEngine
        voiceProcessingActive = voiceProcessing
        converter = StreamConverter()
        armWatchdog()
        generation.value = gen
        wireConfigObserver(for: newEngine)
    }

    // MARK: - Teardown

    private func tearDownEngine() {
        generation.value = genCounter.next() // orphan token: silences any stale tap
        if let configObserver {
            NotificationCenter.default.removeObserver(configObserver)
            self.configObserver = nil
        }
        guard let engine else { return }
        Self.discard(engine, voiceProcessed: voiceProcessingActive)
        voiceProcessingActive = false
        self.engine = nil
    }

    private static func discard(_ engine: AVAudioEngine, voiceProcessed: Bool) {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        if voiceProcessed {
            try? engine.inputNode.setVoiceProcessingEnabled(false)
        }
    }

    // MARK: - Device configuration changes

    private func wireConfigObserver(for engine: AVAudioEngine) {
        configObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine,
            queue: nil
        ) { [weak self] _ in
            guard let self, !self.stopped.value else { return }
            self.restartRaw(reason: "Audio input changed — continuing on the raw mic.", delay: 0.3)
        }
    }

    // MARK: - Buffer handling + watchdog

    private func armWatchdog() {
        watchdogArmed = true
        armedAt = Date()
        emittedSamples = 0
        maxAbs = 0
    }

    private func handle(_ buffer: AVAudioPCMBuffer, gen: Int) {
        guard gen == generation.value, !stopped.value else { return }

        let samples = converter.convert(buffer)
        if !samples.isEmpty {
            if watchdogArmed {
                emittedSamples += samples.count
                for v in samples {
                    let magnitude = Int(v.magnitude)
                    if magnitude > maxAbs { maxAbs = magnitude }
                }
            }
            onSamples?(samples)
        }

        guard watchdogArmed, !restarting.value, let armedAt,
              Date().timeIntervalSince(armedAt) > 2.5 else { return }
        watchdogArmed = false

        if emittedSamples == 0 || maxAbs < 8 {
            if voiceProcessingActive {
                onVoiceProcessingFailed?()
                restartRaw(reason: "Echo cancellation went silent — switched back to the raw mic.")
            } else {
                onNotice?("The mic looks silent — check the input device and its level in System Settings → Sound → Input.")
            }
        }
    }

    private func restartRaw(reason: String, delay: Double = 0) {
        guard !restarting.value else { return }
        restarting.value = true
        onNotice?(reason)
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self else { return }
            defer { self.restarting.value = false }
            guard !self.stopped.value else { return }
            do {
                try self.startRawEngine()
            } catch {
                self.onNotice?("Mic restart failed: \(error.localizedDescription)")
            }
        }
    }
}
