PDF.js 6.4.299 generic viewer (https://github.com/mozilla/pdf.js, Apache-2.0, see `LICENSE`), from
`pdfjs-6.4.299-dist.zip`. Source maps, the sample PDF and the debugger were removed.

One local change, in `web/viewer.html`: it loads `../../../reader.js` and `../../../clip.js` before the viewer,
and its CSP allows inline styles (`style-src 'self' 'unsafe-inline'`) and local files (`connect-src ... file:`).
