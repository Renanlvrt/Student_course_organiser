// Built-in PDF reader (PDF.js viewer, vendor/pdfjs/web/viewer.html?src=<pdf url>[&clip=1]).
// Loaded by viewer.html before the viewer's own modules, so the options below apply before it starts.
(() => {
  // ?src=<encoded url> from Alt+L, or ?DNR:<raw url> from the redirect rules in capture.js
  const params = new URLSearchParams(location.search);
  const src = location.search.startsWith("?DNR:") ? location.search.slice(5) + location.hash : params.get("src");

  document.addEventListener("webviewerloaded", () => {
    const options = window.PDFViewerApplicationOptions;
    options.set("defaultUrl", "");                 // no sample document
    options.set("disablePreferences", true);
    options.set("enableScripting", false);
    const app = window.PDFViewerApplication;
    app.initializedPromise.then(() => {
      if (!src) return;
      if (src.startsWith("file:")) openLocal(app, src.split("#")[0]);
      else app.open({ url: src, originalUrl: src, withCredentials: true, isEvalSupported: false });
      if (params.get("clip") === "1") {
        app.eventBus.on("pagerendered", function once() {
          app.eventBus.off("pagerendered", once);
          globalThis.altoClip && globalThis.altoClip.start();
        });
      }
    });
  }, { once: true });

  // fetch() never reads file: URLs, even with file access granted; XMLHttpRequest does (as in Mozilla's
  // PDF.js extension). The bytes are then handed to the viewer.
  function openLocal(app, url) {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", url);
    xhr.responseType = "arraybuffer";
    xhr.onload = () => {
      if (!xhr.response || !xhr.response.byteLength) return xhr.onerror();
      const filename = decodeURIComponent(url.slice(url.lastIndexOf("/") + 1));
      app.open({ data: new Uint8Array(xhr.response), filename, isEvalSupported: false })
        .then(() => { document.title = filename; });
    };
    xhr.onerror = () => {
      chrome.extension.isAllowedFileSchemeAccess((allowed) => {
        alert(allowed ? "Couldn't read this PDF from your computer:\n" + decodeURI(url)
                      : "To open PDFs from your computer here, turn on \"Allow access to file URLs\" for the " +
                        "Alt+O Blackboard Helper extension in chrome://extensions.");
      });
    };
    xhr.send();
  }

  // Alt+L in this tab: the service worker cannot inject into extension pages, so it asks us.
  let myTabId = null;
  chrome.tabs.getCurrent((tab) => { myTabId = tab ? tab.id : null; });
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "clip-start" && msg.tabId === myTabId && globalThis.altoClip) globalThis.altoClip.start();
    return false;
  });
})();
