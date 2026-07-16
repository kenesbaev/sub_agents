import * as THREE from "three";

const canvas = document.querySelector("#heroOfficeCanvas");
const params = new URLSearchParams(window.location.search);
const lowQuality = params.get("quality") === "low" || window.matchMedia("(max-width: 700px)").matches;
const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
let reducedMotion = motionQuery.matches;
let sceneVisible = true;

// Keep the complete office in view, but spend less empty camera margin than the
// full Office app. The desktop scene can therefore read at a useful scale in
// the landing Hero without moving into the copy/CTA area. On compact screens
// the framing reaches closer to the foundation edge without a large crop.
const HERO_VIEW_WIDTH = lowQuality ? 30.0 : 37.8;
const HERO_MIN_VIEW_HEIGHT = lowQuality ? 17.7 : 15.3;

const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-12, 12, 8, -8, 0.1, 100);
camera.position.set(25.2, 21.4, 26.8);

let renderer;
try {
  renderer = new THREE.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: !lowQuality,
    powerPreference: "high-performance",
  });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lowQuality ? 1 : 1.4));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = !lowQuality;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
} catch (error) {
  document.documentElement.dataset.webgl = "unavailable";
  console.warn("Teamora Hero Office could not start WebGL.", error);
}

const office = new THREE.Group();
office.position.y = -0.24;
scene.add(office);

const ambient = new THREE.HemisphereLight(0xffffff, 0xb7c8ef, 1.85);
scene.add(ambient);

const keyLight = new THREE.DirectionalLight(0xffffff, 2.75);
keyLight.position.set(8, 15, 10);
keyLight.castShadow = !lowQuality;
keyLight.shadow.mapSize.set(lowQuality ? 1 : 1024, lowQuality ? 1 : 1024);
keyLight.shadow.camera.near = 1;
keyLight.shadow.camera.far = 44;
keyLight.shadow.camera.left = -20;
keyLight.shadow.camera.right = 20;
keyLight.shadow.camera.top = 20;
keyLight.shadow.camera.bottom = -20;
scene.add(keyLight);

const fillLight = new THREE.PointLight(0x9d8bff, 10, 34, 2.2);
fillLight.position.set(-8, 7, 3);
scene.add(fillLight);

const warmLight = new THREE.PointLight(0x93d8ff, 8, 30, 2.2);
warmLight.position.set(10, 6, -7);
scene.add(warmLight);

const palette = {
  ink: 0x24335d,
  surface: 0xf9fbff,
  base: 0xe2eaff,
  glass: 0xbcd3ff,
  trim: 0xc8d5f3,
  blue: 0x5f7cff,
  violet: 0x9b70ff,
  cyan: 0x51c7ff,
  mint: 0x68d9be,
  peach: 0xffad8c,
};

const agents = [];
const emissivePanels = [];
const conveyorNodes = [];
const targetPointer = new THREE.Vector2();
const smoothPointer = new THREE.Vector2();
const cameraTarget = new THREE.Vector3(0, 0.55, 0.3);
const lookTarget = new THREE.Vector3();
const cameraBase = new THREE.Vector3(25.2, 21.4, 26.8);
const cameraDesired = new THREE.Vector3();
let frameHandle = 0;
let lastFrame = 0;
let startTime = performance.now();

function standardMaterial(color, options = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.54,
    metalness: options.metalness ?? 0.02,
    emissive: options.emissive ?? 0x000000,
    emissiveIntensity: options.emissiveIntensity ?? 0,
    transparent: options.transparent ?? false,
    opacity: options.opacity ?? 1,
    depthWrite: options.depthWrite ?? true,
  });
}

function addBox(parent, size, position, color, options = {}) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), standardMaterial(color, options));
  mesh.position.set(...position);
  mesh.castShadow = !lowQuality && options.castShadow !== false;
  mesh.receiveShadow = !lowQuality && options.receiveShadow !== false;
  parent.add(mesh);
  return mesh;
}

function addCylinder(parent, radiusTop, radiusBottom, height, position, color, options = {}) {
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(radiusTop, radiusBottom, height, options.segments ?? 24),
    standardMaterial(color, options),
  );
  mesh.position.set(...position);
  mesh.castShadow = !lowQuality && options.castShadow !== false;
  mesh.receiveShadow = !lowQuality && options.receiveShadow !== false;
  parent.add(mesh);
  return mesh;
}

function addGlassWall(parent, width, height, position, rotationY, accent) {
  const wall = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    standardMaterial(accent, {
      roughness: 0.1,
      metalness: 0.04,
      transparent: true,
      opacity: 0.13,
      depthWrite: false,
      castShadow: false,
      receiveShadow: false,
    }),
  );
  wall.position.set(...position);
  wall.rotation.y = rotationY;
  parent.add(wall);
  return wall;
}

function addPillar(parent, position, height = 2.35) {
  return addBox(parent, [0.1, height, 0.1], position, palette.trim, {
    roughness: 0.36,
    metalness: 0.18,
  });
}

function createPlant(parent, x, z, scale = 1) {
  const plant = new THREE.Group();
  plant.position.set(x, 0.09, z);
  addCylinder(plant, 0.22 * scale, 0.26 * scale, 0.42 * scale, [0, 0.21 * scale, 0], 0xf4f7ff, {
    roughness: 0.42,
  });
  const leafMaterial = standardMaterial(0x73cdb4, { roughness: 0.55 });
  for (let index = 0; index < 5; index += 1) {
    const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.1 * scale, 0.56 * scale, 8), leafMaterial);
    const angle = (Math.PI * 2 * index) / 5;
    leaf.position.set(Math.cos(angle) * 0.12 * scale, 0.58 * scale, Math.sin(angle) * 0.12 * scale);
    leaf.rotation.x = Math.PI * 0.35;
    leaf.rotation.z = -Math.cos(angle) * 0.46;
    plant.add(leaf);
  }
  parent.add(plant);
}

function createMonitor(parent, position, accent, scale = 1) {
  const holder = new THREE.Group();
  holder.position.set(...position);
  addBox(holder, [1.08 * scale, 0.64 * scale, 0.08 * scale], [0, 0.43 * scale, 0], 0xeef4ff, {
    roughness: 0.24,
    metalness: 0.08,
  });
  const screen = addBox(holder, [0.9 * scale, 0.45 * scale, 0.035 * scale], [0, 0.43 * scale, 0.06 * scale], 0x18264e, {
    roughness: 0.28,
    emissive: accent,
    emissiveIntensity: 0.38,
    castShadow: false,
  });
  addBox(holder, [0.08 * scale, 0.36 * scale, 0.07 * scale], [0, 0.12 * scale, 0], palette.trim, {
    roughness: 0.36,
  });
  addBox(holder, [0.42 * scale, 0.05 * scale, 0.26 * scale], [0, 0.01 * scale, 0], palette.trim, {
    roughness: 0.36,
  });
  parent.add(holder);
  emissivePanels.push({ mesh: screen, phase: position[0] * 0.4 + position[2] });
  return holder;
}

function createDesk(parent, x, z, accent, wide = false) {
  const desk = new THREE.Group();
  desk.position.set(x, 0.1, z);
  const width = wide ? 3.7 : 2.65;
  addBox(desk, [width, 0.18, 1.1], [0, 0.73, 0], palette.surface, {
    roughness: 0.34,
    metalness: 0.03,
  });
  [-1, 1].forEach((side) => {
    addBox(desk, [0.12, 0.68, 0.12], [side * (width / 2 - 0.2), 0.34, 0.32], palette.trim, {
      roughness: 0.35,
      metalness: 0.14,
    });
    addBox(desk, [0.12, 0.68, 0.12], [side * (width / 2 - 0.2), 0.34, -0.32], palette.trim, {
      roughness: 0.35,
      metalness: 0.14,
    });
  });
  createMonitor(desk, [wide ? -0.6 : 0, 0.76, -0.14], accent, wide ? 1.08 : 0.92);
  if (wide) createMonitor(desk, [0.78, 0.76, -0.14], accent, 0.82);
  const chair = new THREE.Group();
  chair.position.set(0, 0.02, 0.86);
  addCylinder(chair, 0.38, 0.38, 0.1, [0, 0.62, 0], 0xd8e2f6, { segments: 20 });
  addBox(chair, [0.74, 0.54, 0.11], [0, 0.96, 0.22], 0xd8e2f6, { roughness: 0.46 });
  addCylinder(chair, 0.07, 0.07, 0.58, [0, 0.32, 0], palette.trim, { segments: 12 });
  desk.add(chair);
  parent.add(desk);
  return desk;
}

function createAgent(parent, position, accent, phase, scale = 1) {
  const agent = new THREE.Group();
  agent.position.set(...position);
  const body = new THREE.Group();
  body.scale.setScalar(scale);
  const bodyColor = new THREE.Color(accent).lerp(new THREE.Color(0xffffff), 0.34);
  addCylinder(body, 0.31, 0.39, 0.64, [0, 0.66, 0], bodyColor, {
    roughness: 0.3,
    metalness: 0.08,
    emissive: accent,
    emissiveIntensity: 0.045,
  });
  const collar = addCylinder(body, 0.33, 0.33, 0.1, [0, 0.99, 0], accent, {
    roughness: 0.3,
    emissive: accent,
    emissiveIntensity: 0.12,
  });
  collar.scale.y = 0.8;
  const headColor = new THREE.Color(accent).lerp(new THREE.Color(0xffffff), 0.48);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.46, 24, 18), standardMaterial(headColor, {
    roughness: 0.23,
    metalness: 0.11,
    emissive: accent,
    emissiveIntensity: 0.045,
  }));
  head.scale.set(1, 0.86, 0.92);
  head.position.set(0, 1.34, 0);
  head.castShadow = !lowQuality;
  body.add(head);
  const visor = addBox(body, [0.61, 0.19, 0.08], [0, 1.34, 0.39], 0x17264c, {
    roughness: 0.2,
    metalness: 0.12,
    emissive: accent,
    emissiveIntensity: 0.4,
  });
  const eyeMaterial = standardMaterial(0xd7f4ff, {
    roughness: 0.16,
    emissive: 0x88daff,
    emissiveIntensity: 1.4,
  });
  [-0.13, 0.13].forEach((x) => {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.045, 10, 8), eyeMaterial);
    eye.position.set(x, 1.34, 0.45);
    body.add(eye);
  });
  const antenna = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 10), standardMaterial(accent, {
    roughness: 0.2,
    emissive: accent,
    emissiveIntensity: 0.38,
  }));
  antenna.position.set(0, 1.78, 0);
  body.add(antenna);
  [-0.16, 0.16].forEach((x) => {
    addBox(body, [0.12, 0.4, 0.13], [x, 0.23, 0], 0xdfe8fa, { roughness: 0.38 });
    addBox(body, [0.08, 0.36, 0.08], [x * 2.65, 0.73, 0], 0xe5ecfa, { roughness: 0.38 });
  });
  addBox(body, [0.38, 0.22, 0.05], [0, 0.72, 0.39], accent, {
    roughness: 0.24,
    emissive: accent,
    emissiveIntensity: 0.24,
    castShadow: false,
  });
  agent.add(body);
  parent.add(agent);
  agents.push({ group: agent, body, phase, baseY: position[1], visor });
  return agent;
}

function createPod({ x, z, width, depth, accent, variant, phase }) {
  const pod = new THREE.Group();
  pod.position.set(x, 0, z);
  const floor = addBox(pod, [width, 0.13, depth], [0, 0.08, 0], 0xf6f9ff, {
    roughness: 0.49,
  });
  floor.material.color.offsetHSL(0, 0, variant === "coordinator" ? 0.01 : 0);
  addBox(pod, [width - 0.3, 0.035, depth - 0.3], [0, 0.16, 0], accent, {
    roughness: 0.38,
    emissive: accent,
    emissiveIntensity: 0.035,
    castShadow: false,
  });

  const wallHeight = variant === "coordinator" ? 2.45 : 2.05;
  addGlassWall(pod, width - 0.25, wallHeight, [0, wallHeight / 2 + 0.13, -depth / 2 + 0.06], 0, palette.glass);
  addGlassWall(pod, depth - 0.25, wallHeight, [-width / 2 + 0.06, wallHeight / 2 + 0.13, 0], Math.PI / 2, palette.glass);
  addGlassWall(pod, depth - 0.25, wallHeight, [width / 2 - 0.06, wallHeight / 2 + 0.13, 0], -Math.PI / 2, palette.glass);
  [-1, 1].forEach((sideX) => {
    [-1, 1].forEach((sideZ) => addPillar(pod, [sideX * (width / 2 - 0.06), wallHeight / 2 + 0.13, sideZ * (depth / 2 - 0.06)], wallHeight));
  });

  if (variant === "coordinator") {
    addCylinder(pod, 2.08, 2.28, 0.52, [0, 0.42, 0.18], 0xffffff, { segments: 48, roughness: 0.34 });
    addCylinder(pod, 1.7, 1.96, 0.07, [0, 0.72, 0.18], accent, {
      segments: 48,
      emissive: accent,
      emissiveIntensity: 0.13,
      castShadow: false,
    });
    createMonitor(pod, [0, 0.75, -0.4], accent, 1.4);
    createAgent(pod, [0, 0.16, 1.9], accent, phase, 1.55);
    createPlant(pod, -2.58, 1.35, 0.9);
    createPlant(pod, 2.58, 1.35, 0.9);
  } else if (variant === "automation") {
    createDesk(pod, 0, -0.9, accent, true);
    createAgent(pod, [0, 0.16, 1.5], accent, phase, 1.34);
    const belt = addBox(pod, [width - 2.1, 0.18, 0.5], [0, 0.4, 1.26], 0x27385d, {
      roughness: 0.33,
      emissive: accent,
      emissiveIntensity: 0.1,
    });
    conveyorNodes.push({ mesh: belt, phase });
    [-1.65, -0.55, 0.55, 1.65].forEach((nodeX, index) => {
      const node = addBox(pod, [0.48, 0.3, 0.48], [nodeX, 0.66, 1.26], 0xf5f8ff, {
        roughness: 0.32,
        emissive: accent,
        emissiveIntensity: 0.08,
      });
      conveyorNodes.push({ mesh: node, phase: phase + index * 0.6 });
    });
  } else {
    createDesk(pod, 0, -0.3, accent);
    createAgent(pod, [0, 0.16, 1.64], accent, phase, 1.32);
    createPlant(pod, -width / 2 + 0.63, depth / 2 - 0.7, 0.72);
  }
  office.add(pod);
}

function addConnector(from, to, color) {
  const start = new THREE.Vector3(from[0], 0.2, from[1]);
  const end = new THREE.Vector3(to[0], 0.2, to[1]);
  const middle = start.clone().add(end).multiplyScalar(0.5);
  const length = start.distanceTo(end);
  const link = new THREE.Mesh(
    new THREE.BoxGeometry(0.18, 0.065, length),
    standardMaterial(color, { roughness: 0.32, emissive: color, emissiveIntensity: 0.1, castShadow: false }),
  );
  link.position.copy(middle);
  link.rotation.y = Math.atan2(end.x - start.x, end.z - start.z);
  office.add(link);
}

function buildOffice() {
  addBox(office, [30.3, 0.44, 20.3], [0, -0.25, 0], palette.base, {
    roughness: 0.56,
    metalness: 0.03,
  });
  addBox(office, [29.55, 0.08, 19.55], [0, 0.01, 0], 0xf9fbff, {
    roughness: 0.4,
    castShadow: false,
  });

  createPod({ x: 0, z: -0.65, width: 8.2, depth: 5.2, accent: palette.violet, variant: "coordinator", phase: 0.1 });
  createPod({ x: -10.2, z: -4.55, width: 7.1, depth: 5.0, accent: palette.cyan, variant: "marketing", phase: 1.1 });
  createPod({ x: 10.2, z: -4.55, width: 7.1, depth: 5.0, accent: palette.blue, variant: "sales", phase: 2.1 });
  createPod({ x: -10.2, z: 4.25, width: 7.1, depth: 4.15, accent: palette.mint, variant: "research", phase: 3.1 });
  createPod({ x: 10.2, z: 4.25, width: 7.1, depth: 4.15, accent: palette.peach, variant: "support", phase: 4.1 });
  createPod({ x: 0, z: 6.55, width: 8.6, depth: 3.6, accent: palette.violet, variant: "automation", phase: 5.1 });

  addConnector([-5.1, -2.8], [0, -1.8], palette.cyan);
  addConnector([5.1, -2.8], [0, -1.8], palette.blue);
  addConnector([-5.1, 2.8], [0, 4.8], palette.mint);
  addConnector([5.1, 2.8], [0, 4.8], palette.peach);
}

buildOffice();

function resize() {
  if (!renderer) return;
  const width = Math.max(canvas.clientWidth, 1);
  const height = Math.max(canvas.clientHeight, 1);
  const aspect = width / height;
  const viewHeight = Math.max(HERO_MIN_VIEW_HEIGHT, HERO_VIEW_WIDTH / Math.max(aspect, 0.22));
  camera.top = viewHeight / 2;
  camera.bottom = -viewHeight / 2;
  camera.left = (-viewHeight * aspect) / 2;
  camera.right = (viewHeight * aspect) / 2;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
  renderFrame(performance.now());
}

function renderFrame(now) {
  if (!renderer) return;
  const elapsed = (now - startTime) / 1000;
  const movement = reducedMotion ? 0 : 1;
  smoothPointer.lerp(targetPointer, movement ? 0.07 : 1);
  const driftX = movement ? Math.sin(elapsed * 0.18) * 0.42 : 0;
  const driftY = movement ? Math.cos(elapsed * 0.14) * 0.18 : 0;
  cameraDesired.set(
    cameraBase.x + smoothPointer.x * 0.72 + driftX,
    cameraBase.y - smoothPointer.y * 0.42 + driftY,
    cameraBase.z + smoothPointer.x * 0.32,
  );
  camera.position.lerp(cameraDesired, movement ? 0.055 : 1);
  lookTarget.set(
    cameraTarget.x + smoothPointer.x * 0.36,
    cameraTarget.y - smoothPointer.y * 0.15,
    cameraTarget.z,
  );
  camera.lookAt(lookTarget);

  office.position.y = -0.24 + (movement ? Math.sin(elapsed * 0.58) * 0.045 : 0);
  office.rotation.y = movement ? Math.sin(elapsed * 0.16) * 0.006 : 0;
  agents.forEach((agent) => {
    agent.group.position.y = agent.baseY + (movement ? Math.sin(elapsed * 1.75 + agent.phase) * 0.045 : 0);
    agent.body.rotation.z = movement ? Math.sin(elapsed * 1.28 + agent.phase) * 0.028 : 0;
    agent.visor.material.emissiveIntensity = 0.16 + (movement ? (Math.sin(elapsed * 2.1 + agent.phase) + 1) * 0.07 : 0.05);
  });
  emissivePanels.forEach(({ mesh, phase }) => {
    mesh.material.emissiveIntensity = 0.24 + (movement ? (Math.sin(elapsed * 1.65 + phase) + 1) * 0.1 : 0.04);
  });
  conveyorNodes.forEach(({ mesh, phase }) => {
    mesh.material.emissiveIntensity = 0.08 + (movement ? (Math.sin(elapsed * 2.5 + phase) + 1) * 0.11 : 0.03);
  });
  renderer.render(scene, camera);
}

function requestRender() {
  if (frameHandle || !renderer || !sceneVisible || document.hidden) return;
  frameHandle = window.requestAnimationFrame((now) => {
    frameHandle = 0;
    const interval = lowQuality ? 1000 / 22 : 1000 / 30;
    if (reducedMotion || now - lastFrame >= interval) {
      lastFrame = now;
      renderFrame(now);
    }
    if (!reducedMotion) requestRender();
  });
}

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  const message = event.data || {};
  if (message.type === "teamora-hero-parallax") {
    targetPointer.set(
      THREE.MathUtils.clamp(Number(message.x) || 0, -1, 1),
      THREE.MathUtils.clamp(Number(message.y) || 0, -1, 1),
    );
    requestRender();
  }
  if (message.type === "teamora-hero-visibility") {
    sceneVisible = Boolean(message.visible);
    if (sceneVisible) requestRender();
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) requestRender();
});

motionQuery.addEventListener("change", (event) => {
  reducedMotion = event.matches;
  renderFrame(performance.now());
  if (!reducedMotion) requestRender();
});

window.addEventListener("resize", resize, { passive: true });
resize();
requestRender();
