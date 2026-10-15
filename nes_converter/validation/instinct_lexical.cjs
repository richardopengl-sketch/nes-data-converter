'use strict';
const fs = require('node:fs');
const ts = require(process.env.NES_TYPESCRIPT_MODULE || 'typescript');
if (ts.version !== '5.9.3') throw new Error('TypeScript 5.9.3 required; run npm ci in the project directory');

const marker = '<|user_cursor_is_here|>';
const {text, offset} = JSON.parse(fs.readFileSync(0, 'utf8'));
if (typeof text !== 'string' || !Number.isInteger(offset) ||
    offset < 0 || text.slice(offset, offset + marker.length) !== marker) {
  throw new Error('Invalid cursor span supplied to TypeScript guard');
}
const padded = text.slice(0, offset) + ' '.repeat(marker.length) + text.slice(offset + marker.length);
const file = ts.createSourceFile('excerpt.ts', padded, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
const tokens = [];
let literal = false;
function intersects(start, end) {
  return start < offset + marker.length && offset < end;
}
function visit(node) {
  if ((ts.isStringLiteralLike(node) || ts.isTemplateExpression(node) ||
       node.kind === ts.SyntaxKind.RegularExpressionLiteral) &&
      intersects(node.getStart(file), node.end)) literal = true;
  for (const position of [node.pos, node.end]) {
    const comments = [
      ...(ts.getLeadingCommentRanges(padded, position) || []),
      ...(ts.getTrailingCommentRanges(padded, position) || []),
    ];
    if (comments.some(range => intersects(range.pos, range.end))) literal = true;
  }
  if (node.kind <= ts.SyntaxKind.LastToken) {
    // Parser recovery can manufacture empty identifiers at a missing expression.
    if (node.end > node.getStart(file) && node.kind !== ts.SyntaxKind.EndOfFileToken) tokens.push(node);
  } else {
    for (const child of node.getChildren(file)) visit(child);
  }
}
visit(file);
const unterminated = file.parseDiagnostics.some(diagnostic =>
  /Unterminated|'\*\/' expected/.test(ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')));
let report;
if (literal || unterminated) {
  report = {supported: false, reason: 'CURSOR_LITERAL_UNRESOLVED',
    detail: 'Cursor intersects a literal/comment or the excerpt has an unterminated lexical construct'};
} else {
  const previous = tokens.filter(token => token.end <= offset).at(-1);
  const following = tokens.find(token => token.getStart(file) >= offset + marker.length);
  const boundaries = new Set([
    ts.SyntaxKind.SemicolonToken, ts.SyntaxKind.CommaToken, ts.SyntaxKind.OpenParenToken,
    ts.SyntaxKind.CloseParenToken, ts.SyntaxKind.OpenBraceToken, ts.SyntaxKind.CloseBraceToken,
    ts.SyntaxKind.OpenBracketToken, ts.SyntaxKind.CloseBracketToken, ts.SyntaxKind.ColonToken,
  ]);
  const leading = new Set([
    ts.SyntaxKind.ImportKeyword, ts.SyntaxKind.ExportKeyword, ts.SyntaxKind.ConstKeyword,
    ts.SyntaxKind.LetKeyword, ts.SyntaxKind.FunctionKeyword, ts.SyntaxKind.ClassKeyword,
  ]);
  const anchored = previous
    ? boundaries.has(previous.kind) && /^\s*$/.test(padded.slice(previous.end, offset))
    : following && leading.has(following.kind) && /^\s*$/.test(padded.slice(0, offset));
  const propertyBoundary = previous && following &&
    previous.kind === ts.SyntaxKind.DotToken && following.kind === ts.SyntaxKind.Identifier &&
    ts.isPropertyAccessExpression(previous.parent) && previous.parent === following.parent &&
    previous.parent.name === following &&
    /^\s*$/.test(padded.slice(previous.end, offset)) &&
    /^\s*$/.test(padded.slice(offset + marker.length, following.getStart(file)));
  report = anchored || propertyBoundary
    ? {supported: true, typescript_version: ts.version}
    : {supported: false, reason: 'CURSOR_BOUNDARY_UNSUPPORTED',
       detail: 'Supported subset requires an observed code-token boundary, not a lexical guess'};
}
process.stdout.write(JSON.stringify(report));
