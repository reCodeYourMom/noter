import SwiftUI
import AVFoundation

@main
struct NoterApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RecordingsListView()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background {
                appDelegate.keepAliveInBackground()
            }
        }
    }
}

class AppDelegate: NSObject, UIApplicationDelegate {
    private var backgroundTask: UIBackgroundTaskIdentifier = .invalid
    private var silentPlayer: AVAudioPlayer?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // Initialiser CXCallObserver dès le lancement
        _ = CallObserverService.shared
        print("[Noter] CallObserverService initialisé")

        // Configurer la session audio pour le background
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, options: [.mixWithOthers, .defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
        } catch {
            print("[Noter] AVAudioSession setup error: \(error)")
        }

        return true
    }

    /// Maintient l'app en vie en background avec un audio silencieux
    func keepAliveInBackground() {
        // Background task pour avoir du temps
        backgroundTask = UIApplication.shared.beginBackgroundTask { [weak self] in
            self?.endBackgroundTask()
        }

        // Audio silencieux pour rester éveillé grâce au background mode "audio"
        startSilentAudio()
    }

    private func startSilentAudio() {
        guard silentPlayer == nil else { return }

        // Générer 1 seconde de silence en WAV
        let sampleRate: Double = 44100
        let duration: Double = 1.0
        let numSamples = Int(sampleRate * duration)
        var header = createWAVHeader(numSamples: numSamples, sampleRate: Int(sampleRate))
        header.append(Data(count: numSamples * 2)) // 16-bit silence

        do {
            silentPlayer = try AVAudioPlayer(data: header)
            silentPlayer?.numberOfLoops = -1 // boucle infinie
            silentPlayer?.volume = 0.0
            silentPlayer?.play()
            print("[Noter] Silent audio démarré — app reste active en background")
        } catch {
            print("[Noter] Silent audio error: \(error)")
        }
    }

    private func createWAVHeader(numSamples: Int, sampleRate: Int) -> Data {
        var data = Data()
        let dataSize = numSamples * 2
        let fileSize = 36 + dataSize

        data.append("RIFF".data(using: .ascii)!)
        data.append(withUnsafeBytes(of: UInt32(fileSize).littleEndian) { Data($0) })
        data.append("WAVE".data(using: .ascii)!)
        data.append("fmt ".data(using: .ascii)!)
        data.append(withUnsafeBytes(of: UInt32(16).littleEndian) { Data($0) })
        data.append(withUnsafeBytes(of: UInt16(1).littleEndian) { Data($0) })   // PCM
        data.append(withUnsafeBytes(of: UInt16(1).littleEndian) { Data($0) })   // mono
        data.append(withUnsafeBytes(of: UInt32(sampleRate).littleEndian) { Data($0) })
        data.append(withUnsafeBytes(of: UInt32(sampleRate * 2).littleEndian) { Data($0) })
        data.append(withUnsafeBytes(of: UInt16(2).littleEndian) { Data($0) })
        data.append(withUnsafeBytes(of: UInt16(16).littleEndian) { Data($0) })
        data.append("data".data(using: .ascii)!)
        data.append(withUnsafeBytes(of: UInt32(dataSize).littleEndian) { Data($0) })

        return data
    }

    private func endBackgroundTask() {
        if backgroundTask != .invalid {
            UIApplication.shared.endBackgroundTask(backgroundTask)
            backgroundTask = .invalid
        }
    }
}
