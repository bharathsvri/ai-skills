import Foundation
import SwiftUI

struct WhisperModelInfo: Identifiable, Equatable {
    let id: String        // file name
    let label: String
    let sizeMB: Int
    let englishOnly: Bool

    var downloadURL: URL {
        URL(string: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/\(id)")!
    }

    static let catalog: [WhisperModelInfo] = [
        .init(id: "ggml-tiny.en.bin", label: "Tiny (English) — fastest", sizeMB: 75, englishOnly: true),
        .init(id: "ggml-base.en.bin", label: "Base (English) — recommended", sizeMB: 142, englishOnly: true),
        .init(id: "ggml-small.en.bin", label: "Small (English) — more accurate", sizeMB: 466, englishOnly: true),
        .init(id: "ggml-large-v3-turbo.bin", label: "Large v3 Turbo — best, all languages", sizeMB: 1536, englishOnly: false),
    ]
}

/// Downloads ggml models into ~/Library/Application Support/Muesli/models with progress.
@MainActor
final class ModelDownloader: NSObject, ObservableObject {
    @Published var downloading: String?   // model id in flight
    @Published var progress: Double = 0
    @Published var error: String?

    private var task: URLSessionDownloadTask?
    private nonisolated let destination = Atomic<URL?>(nil)

    func download(_ model: WhisperModelInfo, to dir: URL) {
        guard downloading == nil else { return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        downloading = model.id
        progress = 0
        error = nil
        destination.value = dir.appendingPathComponent(model.id)
        let session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        let task = session.downloadTask(with: model.downloadURL)
        self.task = task
        task.resume()
    }

    func cancel() {
        task?.cancel()
        task = nil
        downloading = nil
        progress = 0
    }

    static func isDownloaded(_ model: WhisperModelInfo, in dir: URL) -> Bool {
        FileManager.default.fileExists(atPath: dir.appendingPathComponent(model.id).path)
    }
}

extension ModelDownloader: URLSessionDownloadDelegate {
    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
                                totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let p = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
        Task { @MainActor in self.progress = p }
    }

    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                didFinishDownloadingTo location: URL) {
        // Move synchronously — `location` is deleted when this method returns.
        let moved: Result<Void, Error>
        if let dest = destination.value {
            do {
                try? FileManager.default.removeItem(at: dest)
                try FileManager.default.moveItem(at: location, to: dest)
                moved = .success(())
            } catch {
                moved = .failure(error)
            }
        } else {
            moved = .failure(CocoaError(.fileNoSuchFile))
        }
        Task { @MainActor in
            if case .failure(let err) = moved { self.error = err.localizedDescription }
            self.downloading = nil
            self.progress = 0
            self.task = nil
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error, (error as NSError).code != NSURLErrorCancelled else { return }
        Task { @MainActor in
            self.error = error.localizedDescription
            self.downloading = nil
            self.progress = 0
        }
    }

}
