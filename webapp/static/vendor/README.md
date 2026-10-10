# Vendored browser libraries

Served locally so the web UI works offline and without third-party CDNs.

| File | Package | Version | License |
|------|---------|---------|---------|
| `mermaid-10.9.8.min.js` | [mermaid](https://github.com/mermaid-js/mermaid) (`dist/mermaid.min.js`) | 10.9.8 | MIT |
| `tailwindcss-browser-4.3.3.js` | [@tailwindcss/browser](https://github.com/tailwindlabs/tailwindcss) (`dist/index.global.js`) | 4.3.3 | MIT (`LICENSE.tailwindcss`) |

To upgrade: `npm pack <package>@<version>`, extract, copy the file above, and
update the `<script>` tags in `../index.html`.
