import AppIntents

struct StopRecordingIntent: AppIntent {
    static var title: LocalizedStringResource = "Stop Noter Recording"
    static var description = IntentDescription("Arrête l'enregistrement en cours dans Noter")

    func perform() async throws -> some IntentResult {
        await AudioRecorderService.shared.stopRecording()
        return .result()
    }
}
