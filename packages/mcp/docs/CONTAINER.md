# OpenDART MCP container

How to build, run, label, and publish the MCP server's container image. The [MCP README](../README.md) covers
the server itself.

## Docker

Local image builds require Docker with BuildKit and Compose v2 or newer, plus a
Docker account to pull the Python base images from `dhi.io`.
[DHI Community images require registry authentication](https://docs.docker.com/dhi/how-to/use/).

1. [Create a Docker account](https://app.docker.com/signup) if needed and verify
   your email address. Use your Docker ID as the registry username.
2. In [Docker Home](https://app.docker.com), open **Account settings → Personal
   access tokens → Generate new token**. Give the token read access to public
   repositories and save it in your password manager. An existing Docker PAT
   with this permission also works. See the
   [Docker PAT guide](https://docs.docker.com/security/access-tokens/personal-access-tokens/).
3. Start Docker and authenticate to the DHI registry:

   ```sh
   docker login dhi.io --username YOUR_DOCKER_ID
   ```

   Paste the Docker PAT at the password prompt. Docker stores the credentials
   through its configured credential store. Keep the PAT out of the repository,
   Dockerfile, build arguments, and application `.env` files.

Lint the Dockerfile with the pinned Hadolint image (Docker required). The hook also
runs before pushes that change the Dockerfile:

```sh
uv run prek run hadolint-docker --all-files --stage pre-push
```

From the repository root, validate the Compose configuration, build
`opendart-mcp:dev`, then start the HTTP service:

```sh
docker compose -f packages/mcp/docker-compose.yml config --quiet
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
```

Test the running container through its localhost HTTP endpoint:

```sh
uv run --no-sync python scripts/check_mcp.py --url http://127.0.0.1:8000/mcp
```

Compose publishes `127.0.0.1:8000:8000`, making the service reachable only from
the local machine. Inside the container it binds to `0.0.0.0:8000` so Docker can
forward requests. Localhost Host and Origin checks stay enabled with either bind.
Set `OPENDART_MCP_HTTP__PORT=9000` in your shell to publish `127.0.0.1:9000`
instead; the container's internal port stays `8000`. The native server uses the
same environment variable for its listener port.

The image's health check tests TCP listener readiness; the smoke test additionally
checks the MCP protocol. Compose waits for readiness with `up --wait`, restarts
the service unless explicitly stopped, and leaves it running between client
connections. Manage the service with:

```sh
docker compose -f packages/mcp/docker-compose.yml logs --tail 100 mcp
docker compose -f packages/mcp/docker-compose.yml down
```

Tools need an OpenDART API key. Store only its value in a file outside the source
tree or in the ignored root `.secrets/` directory. Set `OPENDART_API_KEY_FILE` to
that file's absolute host path and add the secrets overlay:

```sh
export OPENDART_API_KEY_FILE=/absolute/path/to/opendart-api-key
docker compose -f packages/mcp/docker-compose.yml -f packages/mcp/compose.secrets.yml up --detach --wait mcp
```

Compose mounts the file read-only at `/run/secrets/OPENDART_API__API_KEY`; its
contents are absent from container environment variables and image layers.
The SDK's nested settings source reads and validates it when the server starts.
The base Compose file runs without the overlay or a key file; the server then
lists every component and its tools explain how to configure a key.

File-backed Compose secrets retain the host file's ownership and permissions.
Ensure UID/GID `10001:10001` can read it: on a Linux host, give the file group
`10001` and mode `0440`. Keep its host directory accessible only to its owner.
The source file remains plaintext on the host; Compose does not encrypt it.
See [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

Native execution still accepts `OPENDART_API__API_KEY`. Compose's explicit
`--env-file` option can load non-secret settings such as the published port or
the secret file path. The build context excludes `.env` variants, secret files,
local virtual environments, and files outside the build allowlist.

The image uses matching Docker Hardened Images for Python 3.14 on Alpine: the
`dhi.io/python` `-dev` variant for the builder and the plain variant for the runtime.
The Dockerfile pins both base images and the uv binary by version and digest.
The builder uses DHI's `/usr/bin/python3.14`, so the copied virtual environment
resolves the same interpreter in the runtime.
See the [DHI Python guide](https://hub.docker.com/hardened-images/catalog/dhi/python/guides).
Dependencies are locked,
installed without development groups, and compiled to bytecode for faster startup.
The builder installs dependencies before copying package source, so source-only
edits reuse the dependency layer. BuildKit caches uv downloads; CI also caches
build layers between runs. See [uv's Docker guidance](https://docs.astral.sh/uv/guides/integration/docker/).

Only the installed runtime environment is copied from the builder. Package code
stays owned by root, and the runtime does not contain uv, the build cache, or the
source checkout. The runtime uses numeric UID/GID `10001:10001` directly because
the DHI runtime has no shell for user-management commands. It retains the packages
provided by the DHI runtime; the Dockerfile does not uninstall pip or delete
bundled libraries. When the Dockerfile changes, CI verifies both DHI bases' signed
SBOM and provenance with Docker's public key before building. CI scans every built
image for secrets, and scans for vulnerabilities when the base images or locked
dependencies change. It blocks fixable high or critical vulnerabilities and detected
secrets, and retains a full vulnerability report including unfixed findings for 30
days. Publishing always runs every check on the exact candidate.

Renovate keeps both base-image digests current in its weekly updates; a pinned
digest must change to receive base-image fixes. Both DHI references update in the
same pull request. Repository maintainers must configure
[DHI credentials for Actions and Renovate](#dhi-credentials).

Compose runs as UID/GID `10001:10001` with a read-only root filesystem, all Linux capabilities dropped, and privilege
escalation disabled. Temporary files use a 32 MiB `/tmp` mount with execution disabled. The company directory archive is
cached in the `directory-cache` named volume at `/var/cache/opendart-mcp`, so restarts load it at once (a copy older
than a day is served while a fresh one downloads). Only the first start waits for the download: name lookups report that
the directory is still loading for a few minutes, while 8-digit corp codes work. `docker compose down --volumes` removes
the cache. Without Compose, the image caches the directory on `/tmp` and every start downloads it. Limits are one CPU,
512 MiB of memory with swap disabled, and 64 processes/threads. Measured in the container, the server uses about 135 MiB
after startup and peaks near 260 MiB with the directory indexed and a large annual report (1.4 million characters)
cached; the filing-document cache is bounded at about 50 MiB (`OPENDART_MCP_DOCUMENTS__CACHE_CHARS`). The image sets
`PYTHON_CPU_COUNT=1` and `TOKIO_WORKER_THREADS=1` so thread pools follow the CPU limit rather than the host's core
count, and turns off FastMCP's startup banner and update check. Adjust these limits in a Compose override when tools
need more resources. Docker's init process forwards signals and reaps child processes; shutdown has a 10-second grace
period. See the [Compose service reference](https://docs.docker.com/reference/compose-file/services/) and [tmpfs
options](https://docs.docker.com/engine/storage/tmpfs/).

CI exercises these restrictions inside the running image, verifies installed code
is protected and CA certificates exist, and tests loading a synthetic file secret.
The HTTP smoke test also requires hostile Host and Origin requests to be rejected.

The `local` [logging driver](https://docs.docker.com/engine/logging/configure/)
retains service logs with rotation: at most three 10 MiB files. MCP responses
travel over HTTP. The image is built or pulled explicitly, so starting the
service does not fetch a mutable tag. Set `OPENDART_MCP_IMAGE` to use an already
pulled image tag or digest with the same Compose restrictions. Outbound networking
remains available for OpenDART API calls.

## DHI credentials

CI pulls the base images from `dhi.io` with a Docker ID and a Docker personal access
token that has read access to public repositories; create both as described in the
[MCP Docker setup](../README.md#docker). Add them as `DHI_USERNAME` and `DHI_TOKEN`
under **Settings → Secrets and variables → Actions**, or with the GitHub CLI, which
prompts for each value:

```sh
gh secret set DHI_USERNAME
gh secret set DHI_TOKEN
```

Renovate needs its own copy to look up DHI tags and digests. In the
[Mend developer portal](https://developer.mend.io/), open this repository's settings
and add `DHI_USERNAME` and `DHI_TOKEN` under **Credentials**. Renovate stops updating
the repository if a credential that `renovate.json` references is missing.

Only the image check and the publishing workflow receive these secrets, and only
publishing receives `packages: write` and `id-token: write`. Both log in with
`docker/login-action`, which logs out when the job ends. DHI signature checks use the
free Docker Scout CLI, which authenticates through `DOCKER_SCOUT_HUB_USER` and
`DOCKER_SCOUT_HUB_PASSWORD`; logging in to `dhi.io` alone does not authenticate Scout.
The daily scan of the published image needs only `packages: read`.

GitHub does not give repository secrets to pull requests from forks. For a fork change
to the image's inputs, a maintainer must review it and run the pull request from a
branch in this repository. Keep the workflows on `pull_request`; never expose registry
credentials with `pull_request_target`.

When the PAT expires or is rotated, update it in GitHub and in the Mend portal, and run
`docker login dhi.io --username YOUR_DOCKER_ID` again on development machines.

## Image metadata

The Dockerfile declares the standard
[OCI image labels](https://github.com/opencontainers/image-spec/blob/main/annotations.md):
title, description, authors, vendor, project URL, documentation URL, source URL,
version, revision, creation time, and licenses. Both CI workflows supply the
package version from `packages/mcp/pyproject.toml`, the source commit, and the
build timestamp. Registry tags identify a build separately from the package version.

Local builds default to package version `0.1.0`. Revision and creation time stay
empty unless supplied. To include them in a Compose build:

```sh
docker compose -f packages/mcp/docker-compose.yml build \
  --build-arg IMAGE_VERSION="$(uv run --no-sync python -c 'from importlib.metadata import version; print(version("opendart-mcp"))')" \
  --build-arg IMAGE_REVISION="$(git rev-parse HEAD)" \
  --build-arg IMAGE_CREATED="$(date -u +%Y-%m-%dT%H:%M:%SZ)" mcp
```

The repository currently declares no project license, so the Dockerfile leaves
the license label empty. `IMAGE_LICENSES` accepts an SPDX license expression when
a license has been selected. Published builds also use any license declared in
the repository's GitHub metadata.

## Publish to GHCR

Publishing is automatic. When a push to `main` changes the image's inputs (the same
`image` filter that selects the pull request image check in
[ci-paths.toml](../../../.github/ci-paths.toml)) or the publisher itself, and every
selected CI check passes, **CI** calls the **Publish MCP image** workflow. It builds a Linux amd64 candidate once
and pushes it by digest only, so no tag refers to it yet. It runs protocol and
security checks and Trivy scans against that exact digest. After those pass, it
signs and verifies the digest with
[Cosign](https://docs.sigstore.dev/quickstart/quickstart-ci/) and promotes the same
image index to consumer tags without rebuilding. A candidate that fails a check
stays untagged. Local builds support native arm64; publication targets amd64.

Tags in `ghcr.io/orestxherija/opendart-mcp`:

| Tag | Meaning |
| --- | --- |
| `main` | Latest verified build of `main`; moves with each publication |
| `sha-<full-commit>` | Verified build of that `main` commit |
| `vX.Y.Z` | Release; the signed `main` digest of the tagged commit |

Publications run one at a time, and `main` never moves to an older commit: when
pushes finish out of order, the older build receives only its `sha-` tag. A
republished commit's `sha-` tag moves to the new digest, and release tags never
move. The digest is the only immutable reference. OCI labels record the source,
revision, and build date. The image includes
[SBOM and provenance attestations](https://docs.docker.com/build/ci/github-actions/attestations/).

Pushing a `vX.Y.Z` tag that matches the package version, on a commit in `main`,
promotes that commit's published digest after verifying its signature and
rescanning it; see [Preparing release artifacts](../../../docs/RELEASING.md). The
release step does not rebuild, so tag a commit that CI published. Every version
bump publishes, because it changes `packages/mcp/pyproject.toml`.

To republish the tip of `main`, for example to pick up base-image fixes, open
**Actions → Publish MCP image → Run workflow** on `main`. Runs on other branches skip
publishing; pull request images are checked without being pushed. To retry a
release's promotion, run **Release MCP image** on its tag.

Publishing to GHCR uses the built-in `GITHUB_TOKEN` with `packages: write`.
Building the image also requires the `DHI_USERNAME` and `DHI_TOKEN` repository
secrets described in [DHI credentials](#dhi-credentials).
Machines that only pull and run the published GHCR image do not need DHI
credentials; DHI authentication is needed when building from its base images.
Failed candidates remain as untagged package versions. Clean them up by hand if
needed; do not bulk-delete untagged versions, because a tagged image's platform
and attestation manifests are listed as untagged versions too.

### Pull and pin

Pull a tag to try the latest build or a release:

```sh
docker pull ghcr.io/orestxherija/opendart-mcp:main
docker pull ghcr.io/orestxherija/opendart-mcp:v0.1.0
```

For deployments, pin the digest. Each publishing run records the digest in its
summary, and this resolves a tag to its current digest:

```sh
docker buildx imagetools inspect ghcr.io/orestxherija/opendart-mcp:main --format '{{json .Manifest}}' |
  jq --raw-output '.digest'
```

Use the result as `ghcr.io/orestxherija/opendart-mcp@sha256:YOUR_DIGEST`.

### Verify signatures

Signing uses GitHub Actions OIDC and the public Sigstore service, with no separate
subscription or signing key secret. The signature records the repository,
publishing workflow, and branch identity in the public transparency log. The
identity is the **Publish MCP image** workflow on `main`, both when CI calls it and on
manual runs, because the certificate names the workflow that defines the job. Images
published before that workflow was renamed carry `mcp-container.yml` instead.
Release tags reuse the `main` digest and its signature. Verify a digest before
running it:

```sh
cosign verify ghcr.io/orestxherija/opendart-mcp@sha256:YOUR_DIGEST \
  --certificate-identity=https://github.com/orestxherija/opendart/.github/workflows/publish-mcp-image.yml@refs/heads/main \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

**Scheduled image scan** runs daily and can also run manually. It resolves
the current `main` tag once, verifies the default-branch publishing identity,
and rescans that digest for vulnerabilities and secrets without rebuilding it.
An optional manual `digest` input audits an older default-branch build. Reports
include unfixed CVEs; fixable HIGH/CRITICAL CVEs and secrets fail the job.
Updating a base-image pin or lockfile, or republishing `main`, is still required
to deliver fixes.

### Run the published image

To test the published image on a machine with Docker, authenticate to GHCR if the
package is private, then run:

```sh
export OPENDART_MCP_IMAGE=ghcr.io/orestxherija/opendart-mcp@sha256:YOUR_DIGEST
docker pull "$OPENDART_MCP_IMAGE"
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
uv run --no-sync python scripts/check_mcp.py --url http://127.0.0.1:8000/mcp
```

For private packages, use a personal access token (classic) with `read:packages`
when running `docker login ghcr.io --username orestxherija`. New GHCR packages are
private by default; visibility can be changed in the package settings.
See [GitHub's Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Use the same localhost client URL for published images. GHCR stores the image;
the HTTP server runs locally with the Compose restrictions when you start it.
