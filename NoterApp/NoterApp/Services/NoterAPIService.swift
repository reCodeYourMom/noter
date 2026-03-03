import Foundation

final class NoterAPIService {
    static let shared = NoterAPIService()

    @MainActor var serverURL: URL {
        let ip = UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.1.1"
        let port = UserDefaults.standard.integer(forKey: "serverPort")
        let actualPort = port > 0 ? port : 9876
        return URL(string: "http://\(ip):\(actualPort)")!
    }

    private init() {}

    func checkHealth() async throws -> Bool {
        let url = await serverURL.appendingPathComponent("health")
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            return false
        }
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let status = json["status"] as? String {
            return status == "ok"
        }
        return false
    }

    func uploadRecording(_ recording: Recording) async throws -> UploadResponse {
        let url = await serverURL.appendingPathComponent("upload")
        let boundary = UUID().uuidString

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 300

        var body = Data()

        // Title field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"title\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(recording.displayTitle)\r\n".data(using: .utf8)!)

        // Audio file
        let audioData = try Data(contentsOf: recording.fileURL)
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"\(recording.filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/mp4\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n".data(using: .utf8)!)

        // End boundary
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)

        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw NoterAPIError.uploadFailed
        }

        return try JSONDecoder().decode(UploadResponse.self, from: data)
    }
}

struct UploadResponse: Codable {
    let status: String
    let recording_id: String
    let duration_s: Double?
    let message: String?
}

enum NoterAPIError: LocalizedError {
    case uploadFailed

    var errorDescription: String? {
        switch self {
        case .uploadFailed: return "Échec de l'envoi au serveur Mac"
        }
    }
}
