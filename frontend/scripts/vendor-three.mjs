import { cp, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageRoot = resolve(frontendRoot, "node_modules", "three");
const vendorRoot = resolve(frontendRoot, "public", "office", "vendor", "three");
const files = [
  ["build/three.module.min.js", "three.module.min.js"],
  ["examples/jsm/controls/OrbitControls.js", "examples/jsm/controls/OrbitControls.js"],
  ["examples/jsm/loaders/GLTFLoader.js", "examples/jsm/loaders/GLTFLoader.js"],
  ["examples/jsm/utils/BufferGeometryUtils.js", "examples/jsm/utils/BufferGeometryUtils.js"],
];

for (const [source, destination] of files) {
  const target = resolve(vendorRoot, destination);
  await mkdir(dirname(target), { recursive: true });
  await cp(resolve(packageRoot, source), target);
}
