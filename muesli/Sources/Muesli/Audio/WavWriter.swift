import Foundation

/// Streaming 16-bit PCM mono WAV writer. Writes a placeholder header up front,
/// appends samples as they arrive, and patches the sizes on finalize.
final class WavWriter {
    let url: URL
    private let sampleRate: Int
    private var handle: FileHandle?
    private var dataBytes: UInt32 = 0
    private(set) var finalized = false

    init(url: URL, sampleRate: Int = 16000) throws {
        self.url = url
        self.sampleRate = sampleRate
        FileManager.default.createFile(atPath: url.path, contents: nil)
        let h = try FileHandle(forWritingTo: url)
        h.write(WavWriter.header(sampleRate: sampleRate, dataBytes: 0))
        self.handle = h
    }

    func append(_ samples: [Int16]) {
        guard let handle, !samples.isEmpty else { return }
        let data = samples.withUnsafeBufferPointer { Data(buffer: $0) }
        handle.write(data)
        dataBytes += UInt32(data.count)
    }

    func finalize() {
        guard let handle, !finalized else { return }
        finalized = true
        let header = WavWriter.header(sampleRate: sampleRate, dataBytes: dataBytes)
        try? handle.seek(toOffset: 0)
        handle.write(header)
        try? handle.close()
        self.handle = nil
    }

    deinit { finalize() }

    /// One-shot convenience: write a whole buffer of samples to a WAV file.
    static func write(samples: [Int16], to url: URL, sampleRate: Int = 16000) throws {
        let writer = try WavWriter(url: url, sampleRate: sampleRate)
        writer.append(samples)
        writer.finalize()
    }

    static func header(sampleRate: Int, dataBytes: UInt32) -> Data {
        var d = Data()
        func put(_ s: String) { d.append(contentsOf: s.utf8) }
        func put32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func put16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }

        let byteRate = UInt32(sampleRate * 2)
        put("RIFF"); put32(36 + dataBytes); put("WAVE")
        put("fmt "); put32(16)
        put16(1)                    // PCM
        put16(1)                    // mono
        put32(UInt32(sampleRate))
        put32(byteRate)
        put16(2)                    // block align
        put16(16)                   // bits per sample
        put("data"); put32(dataBytes)
        return d
    }
}

enum AudioMath {
    /// Root-mean-square level of a chunk of Int16 samples (0...32767 scale).
    static func rms(_ samples: ArraySlice<Int16>) -> Double {
        guard !samples.isEmpty else { return 0 }
        var acc: Double = 0
        for s in samples {
            let v = Double(s)
            acc += v * v
        }
        return (acc / Double(samples.count)).squareRoot()
    }

    static func rms(_ samples: [Int16]) -> Double { rms(samples[...]) }

    /// Is the trailing `seconds` of audio quiet enough to cut a chunk here?
    static func trailingQuiet(_ samples: [Int16], sampleRate: Int = 16000, seconds: Double = 0.3, threshold: Double = 250) -> Bool {
        let n = Int(seconds * Double(sampleRate))
        guard samples.count >= n else { return true }
        return rms(samples.suffix(n)) < threshold
    }
}
