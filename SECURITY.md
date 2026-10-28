# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.5 (the current one) | yes |

Only the latest released version gets security fixes. Assistant X is a prototype: a fix comes as a new version, not
as a patch of an old one.

## Reporting a vulnerability

Please report a vulnerability **privately**, not in a public issue:

- on GitHub, the **Security** tab of the project's repository (https://github.com/AlexandrYalovoy/Assistant_X/security) → **Report a vulnerability** (a private security
  advisory that only the maintainer sees).
- No e-mail address is published. If you cannot use that form, open an issue on GitHub titled **private contact
  request**, with no details of the vulnerability in it; the author replies there with a private channel. Users of the
  GitFlic mirror use the same GitHub path: the mirror has no reporting form of its own.

Say what an attacker can do, the version, and the steps or a file that shows it (a crafted base package, a document,
a command). Please do not attach documents with personal or confidential content.

What to expect:

- an acknowledgement within **7 days**;
- an assessment (accepted or not, and the severity) within **30 days**;
- a fix in a new version as soon as it is ready, for an accepted report usually within **90 days**; the advisory is
  published with the fix, crediting the reporter unless they ask otherwise.

## Trust model

Assistant X runs on the user's own PC, for that user. It reads files the user did not write: documents of every
format, archives in the inbox, base packages received from other people. These are treated as **untrusted data**.

### What the product guarantees

- **Base packages** (`.axbase`, [docs/PACKAGES.md](docs/PACKAGES.md) "Trust"): before anything changes, every string of the manifest is
  validated (id, version, profile, card languages…), every entry name is checked (no `..`, absolute path, drive,
  colon, link, device name), every file against its checksum, every card against the schema, every path a card names
  must lie under `library/` or `index/texts/`, and every move and removal of the install, update, remove or rollback
  is checked to stay inside the workspace. The settings a package gives an empty workspace are written escaped; the
  paths of programs are read only from `assistant_x.local.toml`, never from the shared settings file. Package vectors
  are checked (sizes, dimension, unit length, keys of the package's own fragments only, a sample encoded again when
  the model is on the PC). A package never deletes a file: documents that lose a merge or are removed go to
  `inbox\_to_delete`.
- **Archives in the inbox**: names are checked before anything is written (no absolute path, `..`, link), the
  unpacked size is limited against lying headers, nesting depth is limited, and a refused archive is removed cleanly.
- **Documents**: no document is executed. PDF, office and image files are read by PyMuPDF, LibreOffice (headless
  conversion), Tesseract and DjVuLibre as separate programs; text hidden from a reader (white text, tiny fonts) is cut
  out of the search text and reported.
- **The search server** (MCP) reads the library and returns text; page images are confined to the library folder.
  Over HTTP (the library service `assistant-x service` the apps reach through their stdio bridge, and
  `assistant-x serve --http`) it listens on 127.0.0.1 only, every request needs the bearer token of
  `%LOCALAPPDATA%\AssistantX\mcp_http_token.txt` (the bridge reads it itself: no app setting holds it), and a Host or
  Origin other than 127.0.0.1 or localhost is refused. Every tool carries its annotations (read only, destructive), so
  an app asks the user before a change; DeepSeek Harness and LM Studio get the reading tools only by default.
  The commands that change the library (`base_install`, `base_update`, `base_remove`, `intake_apply`) need two steps:
  the plan, then a confirmation that echoes the token of that plan. The token is random, valid 30 minutes, used once,
  and bound to the action, its target, the workspace and what the plan was made of (the package file by its manifest
  and checksums, the registry entry of the package to remove, the `meta.jsonl` of the batch): a single call written
  into a document cannot change the library, and a token does not confirm a change in another workspace or of a file
  replaced since the plan. Where the client supports MCP elicitation, the server also asks the user itself before
  the change and a "no" stops it. Every such call is logged (`.assistant_x\debug\changes.log`). The server
  instructions tell Claude that document text is data, and a fragment with words addressed to an AI assistant is
  marked "Suspect text".

### What it does not guarantee

- **Content.** The texts and cards of a document or a package are what Claude reads. A document may contain wrong
  facts or text written to steer Claude ("prompt injection"); the marking of suspect text is a simple heuristic and
  misses what it does not know. Claude cites the page so the user can check it.
- **The user's yes.** The token proves that a plan was made in this conversation, not that the user agreed to it: a
  text that makes Claude call the plan and then the confirmation in two steps gets a valid token. Where the client
  cannot ask the user itself (no MCP elicitation), the user's own attention is the last guard: read the plan Claude
  shows, and say yes only to a change you asked for.
- **Ranking.** Vectors that pass the checks still rank a package's fragments by what the model sees in them; a
  package can be written to come up often.
- **The programs it calls.** LibreOffice, Tesseract, 7-Zip and DjVuLibre parse the documents; a vulnerability in one of
  them is a vulnerability in the intake. Keep them updated (an offline medium carries pinned versions).
- **The PC itself.** Anything with the user's rights on the PC can read the library and the settings and call the local
  server; Assistant X is not a sandbox. Use a workspace in a folder only you can read.
- **Who made a package.** A package carries no signature; install packages from people you trust.

## Scope

In scope: the code of this repository, the installer (Setup.bat, [`assistant_x/setup`](assistant_x/setup)), the format of base packages,
the MCP server. Out of scope: vulnerabilities of Claude, of the third-party programs and Python packages (report them
upstream; tell us if Assistant X uses them unsafely), and attacks that need the user's own rights on the PC.
