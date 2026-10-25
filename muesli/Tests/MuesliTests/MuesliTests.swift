import Testing
import Foundation
@testable import Muesli

@Suite struct WavWriterTests {
    @Test func headerAndPayload() throws {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("muesli-test-\(UUID().uuidString).wav")
        defer { try? FileManager.default.removeItem(at: tmp) }

        let samples: [Int16] = [0, 1000, -1000, 32767, -32768]
        try WavWriter.write(samples: samples, to: tmp)

        let data = try Data(contentsOf: tmp)
        #expect(data.count == 44 + samples.count * 2)
        #expect(String(data: data.subdata(in: 0..<4), encoding: .ascii) == "RIFF")
        #expect(String(data: data.subdata(in: 8..<12), encoding: .ascii) == "WAVE")

        let rate = data.subdata(in: 24..<28).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self) }
        #expect(UInt32(littleEndian: rate) == 16000)

        let dataSize = data.subdata(in: 40..<44).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self) }
        #expect(UInt32(littleEndian: dataSize) == UInt32(samples.count * 2))

        // Payload round-trips exactly.
        let payload = data.subdata(in: 44..<data.count).withUnsafeBytes { raw in
            Array(raw.bindMemory(to: Int16.self))
        }
        #expect(payload == samples)
    }

    @Test func streamingAppendPatchesHeader() throws {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("muesli-test-\(UUID().uuidString).wav")
        defer { try? FileManager.default.removeItem(at: tmp) }

        let writer = try WavWriter(url: tmp)
        writer.append([1, 2, 3])
        writer.append([4, 5])
        writer.finalize()

        let data = try Data(contentsOf: tmp)
        let dataSize = data.subdata(in: 40..<44).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self) }
        #expect(UInt32(littleEndian: dataSize) == 10)
    }
}

@Suite struct WhisperParsingTests {
    @Test func parsesSegmentsAndFiltersArtifacts() throws {
        let json = """
        {"transcription":[
          {"offsets":{"from":0,"to":2500},"text":" Hello there, this is a meeting."},
          {"offsets":{"from":2500,"to":4000},"text":" [BLANK_AUDIO]"},
          {"offsets":{"from":4000,"to":5000},"text":" (soft music)"},
          {"offsets":{"from":5000,"to":9000},"text":" We decided to ship on Friday."}
        ]}
        """
        let segments = try WhisperTranscriber.parse(json: Data(json.utf8))
        #expect(segments.count == 2)
        #expect(segments[0].text == "Hello there, this is a meeting.")
        #expect(segments[0].start == 0)
        #expect(segments[0].end == 2.5)
        #expect(segments[1].text == "We decided to ship on Friday.")
    }

    @Test func cleanDropsPhantoms() {
        #expect(WhisperTranscriber.clean(" Thank you. ") == "")
        #expect(WhisperTranscriber.clean("[Silence]") == "")
        #expect(WhisperTranscriber.clean(" ♪♪ ") == "")
        #expect(WhisperTranscriber.clean(" Real sentence here. ") == "Real sentence here.")
    }
}

@Suite struct TranscriptModelTests {
    @Test func coalescingGroupsBySpeakerAndGap() {
        let segments: [TranscriptSegment] = [
            .init(speaker: .me, start: 0, end: 2, text: "First."),
            .init(speaker: .me, start: 3, end: 5, text: "Second."),
            .init(speaker: .them, start: 6, end: 8, text: "Reply."),
            .init(speaker: .me, start: 30, end: 31, text: "Much later."),
        ]
        let groups = segments.coalesced()
        #expect(groups.count == 3)
        #expect(groups[0].text == "First. Second.")
        #expect(groups[0].speaker == .me)
        #expect(groups[1].speaker == .them)
        #expect(groups[2].text == "Much later.")
    }

    @Test func meetingRoundTripsThroughJSON() throws {
        // Whole-second dates: ISO8601 encoding has no sub-second precision.
        var meeting = Meeting(title: "Roundtrip", createdAt: Date(timeIntervalSince1970: 1_755_000_000), folderName: "rt")
        meeting.transcript = [.init(speaker: .them, start: 1.5, end: 3.25, text: "hi")]
        meeting.chat = [.init(role: "user", text: "question?", date: Date(timeIntervalSince1970: 1_755_000_100))]
        meeting.notesMD = "- note"
        meeting.enhancedMD = "# Done"

        let data = try JSONEncoder.muesli.encode(meeting)
        let back = try JSONDecoder.muesli.decode(Meeting.self, from: data)
        #expect(back == meeting)
    }

    @Test func clockFormatting() {
        #expect(formatClock(0) == "0:00")
        #expect(formatClock(65) == "1:05")
        #expect(formatClock(3671) == "1:01:11")
    }
}

@Suite struct AudioMathTests {
    @Test func rmsAndSilenceGate() {
        let silence = [Int16](repeating: 0, count: 16000)
        #expect(AudioMath.rms(silence) == 0)
        #expect(AudioMath.trailingQuiet(silence))

        let loud = [Int16](repeating: 8000, count: 16000)
        #expect(AudioMath.rms(loud) == 8000)
        #expect(!AudioMath.trailingQuiet(loud))
    }
}
