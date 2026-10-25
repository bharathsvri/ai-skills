import Foundation
import AVFoundation
import CoreGraphics
import AppKit

enum Permissions {
    // MARK: - Microphone

    static var micStatus: AVAuthorizationStatus {
        AVCaptureDevice.authorizationStatus(for: .audio)
    }

    static func ensureMicAccess() async -> Bool {
        switch micStatus {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: .audio)
        default: return false
        }
    }

    // MARK: - Screen / system audio recording

    /// System-audio capture via ScreenCaptureKit is gated behind the
    /// "Screen & System Audio Recording" privacy pane.
    static var screenCaptureGranted: Bool {
        CGPreflightScreenCaptureAccess()
    }

    @discardableResult
    static func requestScreenCapture() -> Bool {
        CGRequestScreenCaptureAccess()
    }

    static func openScreenCaptureSettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!
        NSWorkspace.shared.open(url)
    }

    static func openMicSettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")!
        NSWorkspace.shared.open(url)
    }
}
