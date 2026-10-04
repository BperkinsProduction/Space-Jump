#if DEBUG
import WebKit
import os

/// Debug builds only: forwards the game's console errors/warnings and uncaught exceptions to the
/// system log (subsystem com.perkinsproduction.cloudhopper), so they show up in Xcode's console.
final class ConsoleBridge: NSObject, WKScriptMessageHandler {
    private static let logger = Logger(subsystem: "com.perkinsproduction.cloudhopper", category: "web")

    static func install(in controller: WKUserContentController) {
        let js = """
        (() => {
          const send = (level, args) => {
            try {
              const text = Array.from(args).map(a => a instanceof Error ? (a.stack || a.message) : (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' ');
              window.webkit.messageHandlers.console.postMessage({ level, text });
            } catch (e) {}
          };
          for (const level of ['log', 'warn', 'error']) {
            const orig = console[level].bind(console);
            console[level] = (...args) => { send(level, args); orig(...args); };
          }
          addEventListener('error', e => send('error', [e.message + ' @ ' + (e.filename || '') + ':' + (e.lineno || '')]), true);
          addEventListener('unhandledrejection', e => send('error', ['Unhandled rejection: ' + (e.reason && (e.reason.stack || e.reason))]));
        })();
        """
        controller.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        controller.add(ConsoleBridge(), name: "console")
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let text = body["text"] as? String else { return }
        let level = body["level"] as? String ?? "log"
        Self.logger.log("[js \(level, privacy: .public)] \(text, privacy: .public)")
    }
}
#endif
