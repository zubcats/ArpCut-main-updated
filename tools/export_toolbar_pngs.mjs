/**
 * Reads toolbar byte literals from src/assets.py and writes PNGs to exe/actions/.
 * Run: node tools/export_toolbar_pngs.mjs
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');
const assetsPath = path.join(root, 'src', 'assets.py');
const outDir = path.join(root, 'exe', 'actions');

/** Parse Python 3 bytes literal body (inside quotes, no prefix). */
function parseBytesBody(body) {
  const out = [];
  for (let i = 0; i < body.length; i++) {
    const c = body[i];
    if (c !== '\\') {
      out.push(body.charCodeAt(i));
      continue;
    }
    i++;
    const e = body[i];
    if (e === undefined) throw new Error('Trailing backslash');
    if (e === 'x') {
      const hex = body.slice(i + 1, i + 3);
      if (!/^[0-9a-fA-F]{2}$/.test(hex)) throw new Error(`Bad \\x at ${i}`);
      out.push(parseInt(hex, 16));
      i += 2;
    } else if (e === 'n') out.push(10);
    else if (e === 'r') out.push(13);
    else if (e === 't') out.push(9);
    else if (e === '\\' || e === "'" || e === '"') out.push(e.charCodeAt(0));
    else if (e >= '0' && e <= '7') {
      let oct = e;
      let j = i + 1;
      while (oct.length < 3 && j < body.length && body[j] >= '0' && body[j] <= '7') {
        oct += body[j];
        j++;
      }
      out.push(parseInt(oct, 8) & 0xff);
      i = j - 1;
    } else {
      out.push(e.charCodeAt(0));
    }
  }
  return Buffer.from(out);
}

const text = fs.readFileSync(assetsPath, 'utf8');
const mapping = {
  kill_icon: 'kill.png',
  killall_icon: 'killall.png',
  scan_easy_icon: 'scan_easy.png',
  scan_hard_icon: 'scan_hard.png',
  settings_icon: 'settings.png',
  unkillall_icon: 'unkillall.png',
};

fs.mkdirSync(outDir, { recursive: true });

function extractBytesLiteralBody(src, startIdx) {
  let i = startIdx;
  let body = '';
  while (i < src.length) {
    if (src[i] === '\\') {
      body += src.slice(i, i + 2);
      if (src[i + 1] === 'x') {
        body += src.slice(i + 2, i + 4);
        i += 4;
      } else {
        i += 2;
      }
      continue;
    }
    if (src[i] === "'") return { body, end: i };
    body += src[i];
    i++;
  }
  throw new Error('Unclosed bytes literal');
}

for (const [pyName, fileName] of Object.entries(mapping)) {
  const re = new RegExp(`^${pyName} = b'`, 'm');
  const m = text.match(re);
  if (!m) throw new Error(`Missing ${pyName}`);
  const start = m.index + m[0].length;
  const { body } = extractBytesLiteralBody(text, start);
  const buf = parseBytesBody(body);
  const dest = path.join(outDir, fileName);
  fs.writeFileSync(dest, buf);
  console.log('Wrote', path.relative(root, dest), `(${buf.length} bytes)`);
}
