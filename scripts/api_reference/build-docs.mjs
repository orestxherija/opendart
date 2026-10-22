// Redocly CLI 2.x still renders Redoc 2. Bundle with the CLI, then embed Redoc 3.
import { execFileSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const toolingDirectory = dirname(fileURLToPath(import.meta.url));
const toolingRequire = createRequire(import.meta.url);
const outputDirectory = resolve(toolingDirectory, "../../site");
const temporaryDirectory = await mkdtemp(join(tmpdir(), "opendart-reference-"));

try {
  const specificationPath = join(temporaryDirectory, "openapi.json");
  const cliDirectory = dirname(toolingRequire.resolve("@redocly/cli/package.json"));
  execFileSync(process.execPath, [
    join(cliDirectory, "bin/cli.js"),
    "bundle", "opendart",
    "--config", "redocly.yaml",
    "--output", specificationPath,
  ], { cwd: toolingDirectory, stdio: "inherit" });

  const specification = JSON.parse(await readFile(specificationPath, "utf8"));
  // Escape HTML delimiters so descriptions cannot terminate the JSON script tag.
  const embeddedSpecification = JSON.stringify(specification).replaceAll("<", "\\u003c");
  const rendererPath = toolingRequire.resolve("redoc/bundles/redoc.standalone.js");
  // A data URL keeps the ES module and all its dependencies inside index.html.
  const renderer = (await readFile(rendererPath)).toString("base64");
  const title = specification.info.title.replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

  const html = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${title}</title>
    <style>body { margin: 0; padding: 0; }</style>
  </head>
  <body>
    <noscript>Enable JavaScript to view the API reference.</noscript>
    <div id="redoc-container"></div>
    <script id="openapi-spec" type="application/json">${embeddedSpecification}</script>
    <script type="module">
      import { init } from "data:text/javascript;base64,${renderer}";
      await init(
        JSON.parse(document.getElementById("openapi-spec").textContent),
        { layout: "three-panel", router: "hash", disableTelemetry: true },
        document.getElementById("redoc-container"),
      );
    </script>
  </body>
</html>
`;
  await mkdir(outputDirectory, { recursive: true });
  await writeFile(join(outputDirectory, "index.html"), html);
  console.log(`Built Redoc 3 reference: ${join(outputDirectory, "index.html")}`);
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
