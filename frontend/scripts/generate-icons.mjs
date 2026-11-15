// Rasterises the checked-in SVG sources in icons/ into the PNGs the manifest and
// iOS need. Run with `npm run icons` after editing an SVG; the PNGs are committed.
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Resvg } from '@resvg/resvg-js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const src = (name) => readFileSync(join(root, 'icons', name), 'utf8');
const out = (name) => join(root, 'public', name);

mkdirSync(out('icons'), { recursive: true });

function render(svg, size, file, background) {
  const png = new Resvg(svg, {
    fitTo: { mode: 'width', value: size },
    background,
  }).render().asPng();
  writeFileSync(out(file), png);
  console.log(`wrote public/${file} (${size}px)`);
}

const icon = src('icon.svg');
const maskable = src('maskable.svg');

render(icon, 192, 'icons/icon-192.png');
render(icon, 512, 'icons/icon-512.png');
render(maskable, 512, 'icons/maskable-512.png');
// iOS ignores transparency and rounds corners itself, so use the full-bleed art.
render(maskable, 180, 'apple-touch-icon.png');
copyFileSync(join(root, 'icons', 'icon.svg'), out('favicon.svg'));
console.log('copied icons/icon.svg to public/favicon.svg');
