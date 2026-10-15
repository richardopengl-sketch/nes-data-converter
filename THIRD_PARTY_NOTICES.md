# Third-party sources and publication boundary

The fixed NES instruction text and renderer behavior were transcribed/reimplemented
against `microsoft/vscode@0d983fa97d820490827890c3988225195037fe37`.
The corresponding [MIT notice](third_party/VS_CODE_LICENSE.txt) is retained.

The native input interpretation and synthetic source fixtures use the fixed public
Instinct system instruction and published format semantics. Public producer reference:
`continuedev/instinct@2f888a1b152fdaab37a1c9043b749aabdf55a305`.
The corresponding [Apache-2.0 license](third_party/INSTINCT_LICENSE.txt) is retained.
No dataset code sample, original IDE trajectory, or producer module is bundled.

TypeScript 5.9.3 is an external npm dependency, not vendored source or an embedded environment.
Its distribution supplies its own Apache-2.0 notices when installed.

These notices preserve source attribution; they do not decide this project's ownership,
outbound license, commercial-use permission, dataset rights or external publication approval.
Do not add a guessed project license or infer public sharing authorization from an upstream
license. The team's destination and sharing review must precede any remote publication.
