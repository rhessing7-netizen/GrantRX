// One-off script: convert grantrx-logo.svg → grantrx-logo.png (512x512)
// Run with: node scripts/generate-logo-png.mjs
import sharp from "sharp";
import { readFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const publicDir = join(__dirname, "..", "public");
const svgPath = join(publicDir, "grantrx-logo.svg");
const pngPath = join(publicDir, "grantrx-logo.png");

const svgBuffer = readFileSync(svgPath);

await sharp(svgBuffer, { density: 384 })
  .resize(512, 512, { fit: "contain" })
  .png()
  .toFile(pngPath);

console.log("PNG generated:", pngPath, "(512x512)");
