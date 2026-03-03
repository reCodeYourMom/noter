import SwiftUI

struct SettingsView: View {
    @AppStorage("serverIP") private var serverIP = "192.168.1.1"
    @AppStorage("serverPort") private var serverPort = 9876
    @AppStorage("autoRecord") private var autoRecord = true
    @State private var isChecking = false
    @State private var connectionStatus: ConnectionStatus?

    enum ConnectionStatus {
        case success, failure(String)
    }

    var body: some View {
        Form {
            Section("Serveur Mac") {
                HStack {
                    Text("IP")
                        .foregroundStyle(.secondary)
                    TextField("192.168.1.x", text: $serverIP)
                        .multilineTextAlignment(.trailing)
                        #if os(iOS)
                        .keyboardType(.decimalPad)
                        #endif
                }
                HStack {
                    Text("Port")
                        .foregroundStyle(.secondary)
                    TextField("9876", value: $serverPort, format: .number)
                        .multilineTextAlignment(.trailing)
                        #if os(iOS)
                        .keyboardType(.numberPad)
                        #endif
                }
                Button {
                    Task { await testConnection() }
                } label: {
                    HStack {
                        if isChecking {
                            ProgressView()
                                .padding(.trailing, 4)
                        }
                        Text("Tester la connexion")
                    }
                }
                .disabled(isChecking)

                if let status = connectionStatus {
                    switch status {
                    case .success:
                        Label("Connecté", systemImage: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    case .failure(let msg):
                        Label(msg, systemImage: "xmark.circle.fill")
                            .foregroundColor(.red)
                            .font(.caption)
                    }
                }
            }

            Section("Enregistrement") {
                Toggle("Auto-record pendant les appels", isOn: $autoRecord)
                    .onChange(of: autoRecord) { _, newValue in
                        CallObserverService.shared.autoRecord = newValue
                    }
                Text("Démarre automatiquement l'enregistrement quand un appel est connecté.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("À propos") {
                LabeledContent("Version") {
                    Text("1.0.0")
                }
                LabeledContent("Serveur") {
                    Text("http://\(serverIP):\(serverPort)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("Réglages")
    }

    private func testConnection() async {
        isChecking = true
        connectionStatus = nil
        do {
            let ok = try await NoterAPIService.shared.checkHealth()
            connectionStatus = ok ? .success : .failure("Serveur non disponible")
        } catch {
            connectionStatus = .failure(error.localizedDescription)
        }
        isChecking = false
    }
}
