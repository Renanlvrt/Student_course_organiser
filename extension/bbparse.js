// Pure helpers (no chrome.* APIs) so they can be tested in a plain page.
// Finds downloadable files in the HTML body of a Blackboard Ultra document, e.g.
//   <li>Lecture 3: Designing architectures (<a href="…/dl-lecture3.pdf">slides</a>, <a href="…">encoder</a>)</li>
(function (root) {
  const FILE_RX = /\.(pdf|pptx?|docx?|ipynb|py|zip|txt|md|csv|c|h)(?:$|[?#])/i;
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 400);   // full citations

  // Turn a link into something chrome.downloads can fetch, or null if it is a web page.
  // Ultra stores embedded files as "@X@EmbeddedFile.requestUrlStub@X@bbcswebdav/xid-123_1".
  function resolve(href, origin) {
    return (href || "").replace(/@X@EmbeddedFile\.(requestUrlStub|location)@X@/g, origin.replace(/\/$/, "") + "/");
  }

  // Share links that are really files: SharePoint / OneDrive, Google Drive, Dropbox -> their direct download.
  function shareDownload(u) {
    if (/(^|\.)sharepoint\.com$|(^|\.)1drv\.ms$|onedrive\.live\.com$/.test(u.hostname) && /\/:[bwpxt]:\//.test(u.pathname)) {
      const d = new URL(u.href); d.searchParams.set("download", "1"); return d.href;
    }
    let m = u.href.match(/^https:\/\/drive\.google\.com\/file\/d\/([^/]+)/) || u.href.match(/^https:\/\/drive\.google\.com\/open\?id=([^&]+)/);
    if (m) return `https://drive.google.com/uc?export=download&id=${m[1]}`;
    m = u.href.match(/^https:\/\/docs\.google\.com\/(document|presentation|spreadsheets)\/d\/([^/]+)/);
    if (m) return `https://docs.google.com/${m[1]}/d/${m[2]}/export?format=${m[1] === "spreadsheets" ? "xlsx" : m[1] === "presentation" ? "pptx" : "docx"}`;
    if (/(^|\.)dropbox\.com$/.test(u.hostname)) { const d = new URL(u.href); d.searchParams.set("dl", "1"); return d.href; }
    return null;
  }

  function toDownloadable(href, origin) {
    let u;
    try { u = new URL(resolve(href, origin), origin); } catch (e) { return null; }
    if (!/^https?:$/.test(u.protocol)) return null;
    if (/bbcswebdav|\/attachments\/.+\/download/.test(u.pathname)) return u.href;
    const shared = shareDownload(u);
    if (shared) return shared;
    // Colab pages are web apps, not files: use the notebook behind them (gist / GitHub), else skip.
    let m = u.href.match(/^https:\/\/colab\.research\.google\.com\/gist\/([^/]+)\/([0-9a-f]+)\/([^?#]+\.ipynb)/);
    if (m) return `https://gist.githubusercontent.com/${m[1]}/${m[2]}/raw/${m[3]}`;
    if (/^colab\.research\.google\.com$/.test(u.hostname) && !/\/github\//.test(u.pathname)) return null;
    m = u.href.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)\/(?:blob|raw)\/(.+?)(?:[?#].*)?$/);
    if (m && FILE_RX.test(m[3])) return `https://raw.githubusercontent.com/${m[1]}/${m[2]}/${m[3]}`;
    m = u.href.match(/^https:\/\/colab\.research\.google\.com\/github\/([^/]+)\/([^/]+)\/blob\/(.+?)(?:[?#].*)?$/);
    if (m) return `https://raw.githubusercontent.com/${m[1]}/${m[2]}/${m[3]}`;
    if (FILE_RX.test(u.pathname)) return u.href;
    return null;
  }

  // Text of the line a link sits in, minus the "(slides, encoder, …)" link list.
  function lineOf(a) {
    const block = a.closest("li, p, tr, h1, h2, h3, h4, h5, dd, dt") || a.parentElement;
    let t = clean(block ? block.textContent : "");
    // Drop a trailing "(slides, K(x), proof)" link list, but keep "(pp. 770-778)" in a citation.
    const texts = [...(block ? block.querySelectorAll("a") : [])].map((x) => clean(x.textContent)).filter(Boolean);
    if (t.endsWith(")")) {
      let depth = 0;
      for (let i = t.length - 1; i >= 0; i--) {
        if (t[i] === ")") depth++;
        else if (t[i] === "(" && --depth === 0) {
          const group = t.slice(i);
          if (texts.some((x) => x.length < group.length && group.includes(x))) t = t.slice(0, i);
          break;
        }
      }
    }
    return t.replace(/[:\-–\s]+$/, "");
  }

  function fileNameFor(a, url) {
    let name = "";
    const bb = a.getAttribute("data-bbfile");
    if (bb) {
      try { const j = JSON.parse(bb); name = j.linkName || j.displayName || j.fileName || ""; } catch (e) { /* ignore */ }
    }
    if (!name) name = a.getAttribute("download") || "";
    if (!name) {
      try { name = decodeURIComponent(new URL(url).pathname.split("/").pop() || ""); } catch (e) { name = ""; }
    }
    return clean(name);
  }

  function bodyLinks(html, origin) {
    const doc = new DOMParser().parseFromString(html || "", "text/html");
    const files = [];
    const skipped = [];
    // files shown inside the page (images, embedded viewers, videos) count too
    for (const el of doc.querySelectorAll("img[src], embed[src], iframe[src], source[src], video[src], object[data]")) {
      const src = el.getAttribute("src") || el.getAttribute("data");
      const url = /bbcswebdav/.test(src || "") ? toDownloadable(src, origin) : null;
      if (url) files.push({ url, fileName: fileNameFor(el, url), line: lineOf(el), linkText: clean(el.getAttribute("alt") || el.getAttribute("title") || "") });
    }
    for (const a of doc.querySelectorAll("a[href]")) {
      const href = a.getAttribute("href");
      const linkText = clean(a.textContent);
      const url = toDownloadable(href, origin);
      if (!url) {
        if (!/^(mailto:|#|javascript:)/i.test(href)) skipped.push({ text: linkText || href, href, line: lineOf(a) });
        continue;
      }
      files.push({ url, fileName: fileNameFor(a, url), line: lineOf(a), linkText });
    }
    return { files, skipped };
  }

  root.BBParse = { bodyLinks, toDownloadable, lineOf, resolve };
})(typeof window !== "undefined" ? window : globalThis);
