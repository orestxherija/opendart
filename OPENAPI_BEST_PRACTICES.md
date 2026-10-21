Yes. Redoc documentation can be hosted directly on GitHub Pages, completely free for a public repository, without requiring Redocly's paid hosting services.

Redocly CLI can generate a standalone HTML document from your OpenAPI specification. GitHub Pages can serve that document as an ordinary static website.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://redocly.com\&sz=32)

Redocly

+1



The workflow is straightforward:

openapi.yaml

GitHub Actions

GitHub Pages

On every push to main: validate the specification, generate Redoc HTML, and publish.

## 1. Generate the documentation locally

Assuming your specification is named `openapi.yaml`:

```
npx @redocly/cli lint openapi.yaml

npx @redocly/cli build-docs openapi.yaml \
  --output=site/index.html
```

This creates `site/index.html`, containing your rendered API documentation.

## 2. Automatically publish using GitHub Actions

Create `.github/workflows/docs.yml`:

```

name: Publish API Documentation

on:
  push:
    branches: [main]
    paths:
      - "openapi.yaml"
      - "redocly.yaml"
      - ".github/workflows/docs.yml"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest

    permissions:
      contents: read
      pages: write
      id-token: write

    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "22"

      - name: Lint OpenAPI
        run: npx --yes @redocly/cli lint openapi.yaml

      - name: Generate Redoc HTML
        run: |
          mkdir -p site
          npx --yes @redocly/cli build-docs \
            openapi.yaml \
            --output=site/index.html

      - name: Configure GitHub Pages
        uses: actions/configure-pages@v5

      - name: Upload documentation
        uses: actions/upload-pages-artifact@v4
        with:
          path: site

      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@v4

```

Then navigate to GitHub repository → Settings → Pages → Build and deployment, and choose GitHub Actions as the source.

Your documentation will be available at a URL like:

`https://your-org.github.io/your-repo/`

GitHub officially supports this artifact-based deployment approach.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.github.com\&sz=32)

GitHub Docs

+1



For production, I would pin the Redocly CLI version through `package.json` and a lockfile rather than installing the latest release on every run. You should also expand the workflow's `paths` filter if your specification uses multiple files.

## 3. Important considerations

- Private documentation: A private GitHub repository does not automatically imply a private Pages website. GitHub Enterprise Cloud organizations can restrict Pages access to authorized repository readers. Verify this before publishing internal APIs.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://docs.github.com\&sz=32)

  GitHub Enterprise Cloud Docs

- OpenAPI versions: This repository uses OpenAPI 3.2.1. Its documentation build bundles the reference with Redocly CLI 2.64.1 and embeds Redoc CE 3.0.1, which supports OpenAPI 3.2. Use the repository's `npm --prefix api_reference run build` command; this pinned CLI's `build-docs` command still embeds Redoc 2. See [the reference build instructions](api_reference/README.md#rebuild-and-validate).

  [image](https://www.google.com/s2/favicons?domain=https://redocly.com\&sz=32)

  Redocly

- Multiple APIs: You can generate a separate page for each API under paths such as `/companies/`, `/research/`, and `/transcripts/`, with a shared documentation homepage.

- No backend required: Hosting the documentation does not deploy the API itself.

My recommendation: Use GitHub Actions to publish Redoc automatically whenever the OpenAPI contract changes, with linting and compatibility checks before deployment. For internal company APIs, verify that your GitHub Enterprise configuration supports private Pages access before enabling publication.
