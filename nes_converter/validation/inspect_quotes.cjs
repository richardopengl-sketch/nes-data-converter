// Parse bounded published string assignments as data; never execute dataset code.
const fs = require('node:fs');
const ts = require(process.env.NES_TYPESCRIPT_MODULE || 'typescript');
if (ts.version !== '5.9.3') throw new Error('TypeScript 5.9.3 required; run npm ci --ignore-scripts');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = input.map(item => {
  const file = ts.createSourceFile('published-assignment.ts', item.statement, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const statement = file.statements.length === 1 ? file.statements[0] : undefined;
  const declarations = statement && ts.isVariableStatement(statement) ? statement.declarationList.declarations : [];
  const value = declarations.length === 1 ? declarations[0].initializer : undefined;
  const valid = file.parseDiagnostics.length === 0 && value &&
    (ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value));
  return {
    sha256: item.sha256, validClosedStringAssignment: Boolean(valid),
    initializerKind: value ? ts.SyntaxKind[value.kind] : null,
    diagnostics: file.parseDiagnostics.map(d => ts.flattenDiagnosticMessageText(d.messageText, '\n')),
  };
});
process.stdout.write(JSON.stringify({typescript: ts.version, results}));
