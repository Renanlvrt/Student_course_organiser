// Pure helpers (no chrome.* APIs) so they can be tested in a plain page.
// Finds downloadable files in the HTML body of a Blackboard Ultra document, e.g.
//   <li>Lecture 3: Designing architectures (<a href="…/dl-lecture3.pdf">slides</a>, <a href="…">encoder</a>)</li>
(function (root) {
  const FILE_RX = /\.(pdf|pptx?|docx?|ipynb|py|zip|txt|md|csv|c|h)(?:$|[?#])/i;
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 400);   // full citations

  // Turn a link into something chrome.downloads can fetch, or null if it is a web page.
  function toDownloadable(href, origin) {
    let u;
    try { u = new URL(href, origin); } catch (e) { return null; }
    if (!/^https?:$/.test(u.protocol)) return null;
    if (/bbcswebdav|\/attachments\/.+\/download/.test(u.pathname)) return u.href;
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
      try { name = JSON.parse(bb).linkName || ""; } catch (e) { /* ignore */ }
    }
    if (!name) {
      try { name = decodeURIComponent(new URL(url).pathname.split("/").pop() || ""); } catch (e) { name = ""; }
    }
    return clean(name);
  }

  function bodyLinks(html, origin) {
    const doc = new DOMParser().parseFromString(html || "", "text/html");
    const files = [];
    const skipped = [];
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

  root.BBParse = { bodyLinks, toDownloadable, lineOf };
})(typeof window !== "undefined" ? window : globalThis);
