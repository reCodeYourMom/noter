import Foundation
import Combine

@MainActor
final class RecordingStore: ObservableObject {
    static let shared = RecordingStore()

    @Published var recordings: [Recording] = []

    private let indexURL: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("recordings.json")
    }()

    private init() {
        load()
    }

    func load() {
        guard FileManager.default.fileExists(atPath: indexURL.path) else { return }
        do {
            let data = try Data(contentsOf: indexURL)
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            recordings = try decoder.decode([Recording].self, from: data)
            recordings.sort { $0.date > $1.date }
        } catch {
            print("RecordingStore load error: \(error)")
        }
    }

    func save() {
        do {
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            encoder.outputFormatting = .prettyPrinted
            let data = try encoder.encode(recordings)
            try data.write(to: indexURL, options: .atomic)
        } catch {
            print("RecordingStore save error: \(error)")
        }
    }

    func add(_ recording: Recording) {
        recordings.insert(recording, at: 0)
        save()
    }

    func markSent(_ id: UUID) {
        guard let idx = recordings.firstIndex(where: { $0.id == id }) else { return }
        recordings[idx].isSent = true
        save()
    }

    func updateDuration(_ id: UUID, duration: TimeInterval) {
        guard let idx = recordings.firstIndex(where: { $0.id == id }) else { return }
        recordings[idx].duration = duration
        save()
    }

    func delete(_ id: UUID) {
        guard let idx = recordings.firstIndex(where: { $0.id == id }) else { return }
        let rec = recordings[idx]
        try? FileManager.default.removeItem(at: rec.fileURL)
        recordings.remove(at: idx)
        save()
    }
}
