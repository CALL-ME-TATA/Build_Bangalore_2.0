// Writes the PNG app icons (192, 512 and a 512 maskable) into public/, drawing the same mark as
// public/icon.svg with plain Node (zlib + a tiny PNG encoder), so no image tool is needed.
// Run: npm run icons
import { deflateSync } from 'node:zlib';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'public');
const PAPER = [0xfa, 0xf8, 0xf4];
const ACCENT = [0xb3, 0x5c, 0x12];
const WHITE = [0xff, 0xff, 0xff];

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function png(size, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    rgba.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// Signed distances in the 512-unit design space (negative inside).
const sdCircle = (x, y, cx, cy, r) => Math.hypot(x - cx, y - cy) - r;
function sdRoundRect(x, y, x0, y0, w, h, r) {
  const cx = x0 + w / 2;
  const cy = y0 + h / 2;
  const qx = Math.abs(x - cx) - (w / 2 - r);
  const qy = Math.abs(y - cy) - (h / 2 - r);
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
}
function sdArc(x, y) {
  // Lower half circle of radius 76 around (256, 250), stroke 22.
  if (y < 250) return Math.min(Math.hypot(x - 180, y - 250), Math.hypot(x - 332, y - 250)) - 11;
  return Math.abs(Math.hypot(x - 256, y - 250) - 76) - 11;
}
const sdStem = (x, y) => sdRoundRect(x, y, 245, 315, 22, 62, 11);

function draw(size, maskable) {
  const buf = Buffer.alloc(size * size * 4);
  const s = 512 / size;
  // Maskable icons keep the mark inside the central 80% safe zone and fill the whole square.
  const scale = maskable ? 0.72 : 1;
  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      const X = (px + 0.5) * s;
      const Y = (py + 0.5) * s;
      const x = 256 + (X - 256) / scale;
      const y = 256 + (Y - 256) / scale;
      const aa = s / scale;
      const cover = (d) => Math.max(0, Math.min(1, 0.5 - d / aa));
      const bgA = maskable ? 1 : cover(sdRoundRect(X, Y, 0, 0, 512, 512, 112) / 1);
      let c = PAPER.slice();
      const mix = (col, a) => {
        c = c.map((v, i) => v + (col[i] - v) * a);
      };
      mix(ACCENT, cover(sdCircle(x, y, 256, 256, 168)));
      const glyph = Math.max(cover(sdRoundRect(x, y, 216, 150, 80, 140, 40)), cover(sdArc(x, y)), cover(sdStem(x, y)));
      mix(WHITE, glyph);
      const o = (py * size + px) * 4;
      buf[o] = Math.round(c[0]);
      buf[o + 1] = Math.round(c[1]);
      buf[o + 2] = Math.round(c[2]);
      buf[o + 3] = Math.round(255 * bgA);
    }
  }
  return png(size, buf);
}

writeFileSync(join(out, 'icon-192.png'), draw(192, false));
writeFileSync(join(out, 'icon-512.png'), draw(512, false));
writeFileSync(join(out, 'icon-512-maskable.png'), draw(512, true));
console.log('icons written to', out);
