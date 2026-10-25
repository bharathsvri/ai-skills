import Foundation
import AVFoundation
import CoreMedia
import ScreenCaptureKit

enum SystemAudioError: LocalizedError {
    case noDisplay
    case notAuthorized

    var errorDescription: String? {
        switch self {
        case .noDisplay:
            return "No display found to capture system audio from."
        case .notAuthorized:
            return "Screen & System Audio Recording permission is required to hear the other side of a call."
        }
    }
}

/// Captures everything the Mac plays (Zoom, Meet, Teams, a browser tab…) via
/// ScreenCaptureKit's audio tap — no bot joins the meeting. Emits 16 kHz mono Int16.
///
/// Video frames are configured to the minimum SCK allows and dropped on arrival;
/// we only keep the audio.
final class SystemAudioRecorder: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private let converter = StreamConverter()
    private let audioQueue = DispatchQueue(label: "muesli.sck.audio")
    private let videoQueue = DispatchQueue(label: "muesli.sck.video")

    var onSamples: (([Int16]) -> Void)?
    var onStoppedWithError: ((Error) -> Void)?

    func start() async throws {
        guard Permissions.screenCaptureGranted else { throw SystemAudioError.notAuthorized }

        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else { throw SystemAudioError.noDisplay }

        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])

        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 16000
        config.channelCount = 1
        // Minimal video we immediately throw away.
        config.width = 16
        config.height = 16
        config.minimumFrameInterval = CMTime(value: 1, timescale: 2)
        config.showsCursor = false
        config.queueDepth = 6

        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: audioQueue)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: videoQueue)
        try await stream.startCapture()
        self.stream = stream
    }

    func stop() async {
        guard let stream else { return }
        self.stream = nil
        try? await stream.stopCapture()
    }

    // MARK: - SCStreamOutput

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, CMSampleBufferDataIsReady(sampleBuffer) else { return }
        guard let pcm = Self.pcmBuffer(from: sampleBuffer) else { return }
        let samples = converter.convert(pcm)
        if !samples.isEmpty {
            onSamples?(samples)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        onStoppedWithError?(error)
    }

    static func pcmBuffer(from sampleBuffer: CMSampleBuffer) -> AVAudioPCMBuffer? {
        guard let description = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description),
              let format = AVAudioFormat(streamDescription: asbd) else { return nil }
        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        guard frames > 0,
              let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)) else { return nil }
        pcm.frameLength = AVAudioFrameCount(frames)
        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sampleBuffer,
            at: 0,
            frameCount: Int32(frames),
            into: pcm.mutableAudioBufferList
        )
        return status == noErr ? pcm : nil
    }
}
