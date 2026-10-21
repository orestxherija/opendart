# Repository-local Python conventions

This repository vendors the three plugins from `~/Projects/python-conventions`:

| Plugin | Version | Skills |
| --- | --- | --- |
| `python-settings` | 1.0.0 | 1 |
| `python-http` | 0.3.0 | 11 |
| `python-db` | 0.1.0 | 12 |

`python-conventions/` contains complete plugin snapshots, including the original
manifests, skills, reference examples, scripts, optional reviewer definitions,
and evaluation cases. Relative links are preserved. These files supply agent
guidance; they do not install Python dependencies or application modules.

`marketplace.json` exposes these plugins to Codex in this repository. The
repository's `.codex/config.toml` enables all three explicitly, including the
shared settings dependency. User-level Codex configuration is not modified.
Codex must trust the repository to load its project configuration. Reload the
project or restart Codex if the plugins do not appear immediately. Skills retain
their plugin namespaces, such as `python-http:client` and `python-db:client`.

The optional HTTP edit checker remains opt-in as documented in
[its README](python-conventions/python-http/scripts/README.md). The bundled
Claude reviewer definitions are preserved; Codex uses the corresponding review
skills directly.

These are local snapshots. Changes in the source directory are not copied
automatically. Update the plugin snapshots together with their versions above
when refreshing them.

See the [official repository plugin configuration documentation](https://developers.openai.com/plugins/build/plugins#enable-or-disable-a-plugin-for-a-repo).
