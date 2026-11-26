English | [Русский](AUDIT-0.7.2.ru.md)

# Engineering audit of Assistant X 0.7.2

The review covers the repository and its release pipeline, using synthetic documents and temporary workspaces. The operational question is whether an engineer can trace a value to the correct page, check its scope, and recover a library after an interrupted change.

| Area | Evidence reviewed | Consequence for use |
| --- | --- | --- |
| Engineering answers | Citation parser, OCR flags, page windows, edition and jurisdiction metadata. The fixture includes two editions, a wrong unit, a misleading table row, a scan and a missing answer. | A verified page gives traceability. A reviewer must still judge whether the passage supports a claim and whether the edition applies. |
| Search quality and cost | Five fixture questions over three modes and two search routes. Balanced delivered five expected page groups and two marked numbers with five combined calls versus fourteen separate calls. | Use balanced as the default. Grading real client answers and measuring actual billed usage require client session records. |
| Data integrity and recovery | Intake dry run, refusal, duplicates, revised editions, interrupted apply and resume. Package install, update, removal and rollback have separate tests. | Keep the journal and source documents together when restoring a workspace. Release tests cover modeled interruptions, not every power or storage failure. |
| Permissions and privacy | Local HTTP binding and bearer token, scoped bridge actions, reader export, plan binding, local auto-apply setting. Export writes files and cloud clients receive selected evidence. | Limit write access to the inbox workflow where possible and review the local policy before transfer. A plan token binds an operation; the client handles user consent. |
| Packaging and portability | Version, generated references, bilingual documentation, dependency closure, wheel inventory and release CI. | The supported test matrix is Python 3.11 on Windows and Linux. The browser integration and other platform combinations require separate qualification. |
| Maintenance | Corrected the compact-mode limits, confirmation wording and missing dependency pin. Added checks for local document links and version attribution. | Update generated documents through their templates. Preserve historical measurements with the corpus and scoring method that produced them. |

## Dependency findings and remaining work

OSV matched the previous pins for filelock, opentelemetry-api and torch. After upgrading them to 4.3.1, 1.45.2 and 2.13.0 respectively, a second OSV query on 2026-11-26 returned no advisory matches across the 76 release pins. A clean Python 3.11 environment also exposed an offline build failure with setuptools 65.5.0. The installer now requests the project build minimum of 77. A version match alone does not establish reachability in this application. Assistant X does not directly import filelock or invoke TorchScript compilation in its Python source. Transitive calls and external document converters remain within the review scope for future qualification.

| Priority | Next check | Acceptance evidence |
| --- | --- | --- |
| High | Qualify patched dependencies in a separate environment, including the Windows CUDA wheel and offline installation. | Dependency resolution, advisory recheck, model loading, search quality, GPU use and offline installation on supported platforms. |
| Medium | Exercise real client intake and browser permissions on a disposable workspace. | Independent confirmation, cancellation and a cited result after indexing. |
| Medium | Measure cost per correct answer on a representative library. | Fixed model and corpus, human-reviewed conclusions and client-reported usage, including failed attempts. |

The release procedure and security reporting channel are documented in [Contributing](../CONTRIBUTING.md) and [Security](../SECURITY.md). The measurement method is described in [Answer cost](COST.md).
