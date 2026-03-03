import Foundation

struct Recording: Identifiable, Codable, Equatable {
    let id: UUID
    var title: String
    let date: Date
    var duration: TimeInterval
    let filename: String
    var isSent: Bool

    var displayTitle: String {
        if !title.isEmpty { return title }
        let fmt = DateFormatter()
        fmt.dateFormat = "dd/MM HH:mm"
        return "Appel du \(fmt.string(from: date))"
    }

    var durationText: String {
        let m = Int(duration) / 60
        let s = Int(duration) % 60
        return String(format: "%d:%02d", m, s)
    }

    var fileURL: URL {
        Self.recordingsDirectory.appendingPathComponent(filename)
    }

    static var recordingsDirectory: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = docs.appendingPathComponent("recordings")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
}
