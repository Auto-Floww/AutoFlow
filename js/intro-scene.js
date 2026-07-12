import * as THREE from "three";

(function () {
  const TIMING = {
    fadeIn: 300,
    openStart: 300,
    openDuration: 1100,
    zoomStart: 1500,
    zoomDuration: 1500,
    crossfadeStart: 2850,
    crossfadeDuration: 700,
    removeAt: 3600
  };

  const COLORS = {
    accent: "#1FE08A",
    neon: "#8DF65B",
    bg: "#050507",
    chrome: "#242429",
    chromeDark: "#141417"
  };

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const canvas = document.getElementById("intro-canvas");
  const body = document.body;
  const siteParts = [
    document.querySelector(".topbar"),
    document.querySelector("main"),
    document.querySelector(".site-footer")
  ].filter(Boolean);

  if (!canvas) return;

  function finish() {
    if (window.__autoflowIntroDone) return;
    window.__autoflowIntroDone = true;
    canvas.classList.add("hide");
    siteParts.forEach((part) => { part.style.opacity = ""; });
    body.classList.remove("intro-pending");
    window.setTimeout(() => canvas.remove(), 700);
  }

  if (reduceMotion) {
    finish();
    return;
  }

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function easeInOutCubic(t) {
    return t < 0.5
      ? 4 * t * t * t
      : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function lerp(a, b, t) {
    return a + (b - a) * t;
  }

  // Extruded rounded rectangle: compatible with Three.js r128 and later.
  function roundedSlabGeometry(width, depth, height, radius) {
    const x = -width / 2;
    const y = -depth / 2;
    const shape = new THREE.Shape();

    shape.moveTo(x + radius, y);
    shape.lineTo(x + width - radius, y);
    shape.quadraticCurveTo(x + width, y, x + width, y + radius);
    shape.lineTo(x + width, y + depth - radius);
    shape.quadraticCurveTo(x + width, y + depth, x + width - radius, y + depth);
    shape.lineTo(x + radius, y + depth);
    shape.quadraticCurveTo(x, y + depth, x, y + depth - radius);
    shape.lineTo(x, y + radius);
    shape.quadraticCurveTo(x, y, x + radius, y);

    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth: height,
      bevelEnabled: true,
      bevelSegments: 3,
      steps: 1,
      bevelSize: Math.min(radius * 0.22, height * 0.28),
      bevelThickness: Math.min(height * 0.18, 0.012),
      curveSegments: 8
    });

    geometry.center();
    geometry.rotateX(Math.PI / 2);
    geometry.computeVertexNormals();
    return geometry;
  }

  function makeScreenTexture() {
    const textureCanvas = document.createElement("canvas");
    textureCanvas.width = 512;
    textureCanvas.height = 320;
    const ctx = textureCanvas.getContext("2d");

    ctx.fillStyle = "#060608";
    ctx.fillRect(0, 0, textureCanvas.width, textureCanvas.height);

    const accentGlow = ctx.createRadialGradient(150, 90, 10, 150, 90, 260);
    accentGlow.addColorStop(0, COLORS.accent);
    accentGlow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.globalAlpha = 0.48;
    ctx.fillStyle = accentGlow;
    ctx.fillRect(0, 0, textureCanvas.width, textureCanvas.height);

    const neonGlow = ctx.createRadialGradient(390, 235, 10, 390, 235, 260);
    neonGlow.addColorStop(0, COLORS.neon);
    neonGlow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.globalAlpha = 0.34;
    ctx.fillStyle = neonGlow;
    ctx.fillRect(0, 0, textureCanvas.width, textureCanvas.height);

    ctx.globalAlpha = 1;
    const texture = new THREE.CanvasTexture(textureCanvas);
    if ("colorSpace" in texture) {
      texture.colorSpace = THREE.SRGBColorSpace;
    } else {
      texture.encoding = THREE.sRGBEncoding;
    }
    return texture;
  }

  function makeBrandTexture() {
    const textureCanvas = document.createElement("canvas");
    textureCanvas.width = 2048;
    textureCanvas.height = 1280;
    const ctx = textureCanvas.getContext("2d");
    const brandY = 580;

    ctx.clearRect(0, 0, textureCanvas.width, textureCanvas.height);
    ctx.font = '600 224px "Space Grotesk", sans-serif';
    ctx.textBaseline = "middle";
    const autoWidth = ctx.measureText("Auto").width;
    const flowWidth = ctx.measureText("Flow").width;
    const brandX = (textureCanvas.width - autoWidth - flowWidth) / 2;

    ctx.fillStyle = "#F5F5F7";
    ctx.fillText("Auto", brandX, brandY);
    ctx.fillStyle = COLORS.accent;
    ctx.fillText("Flow", brandX + autoWidth, brandY);

    ctx.globalAlpha = 0.92;
    ctx.font = '500 68px "IBM Plex Sans", sans-serif';
    ctx.textAlign = "center";
    ctx.fillStyle = "#F5F5F7";
    ctx.fillText("IA para vendas e atendimento", textureCanvas.width / 2, brandY + 200);

    const texture = new THREE.CanvasTexture(textureCanvas);
    if ("colorSpace" in texture) {
      texture.colorSpace = THREE.SRGBColorSpace;
    } else {
      texture.encoding = THREE.sRGBEncoding;
    }
    return texture;
  }

  function makeReflectionTexture() {
    const textureCanvas = document.createElement("canvas");
    textureCanvas.width = 256;
    textureCanvas.height = 160;
    const ctx = textureCanvas.getContext("2d");
    const reflection = ctx.createLinearGradient(0, 0, 256, 160);
    reflection.addColorStop(0, "rgba(255,255,255,0.20)");
    reflection.addColorStop(0.28, "rgba(255,255,255,0.035)");
    reflection.addColorStop(0.5, "rgba(255,255,255,0)");
    ctx.fillStyle = reflection;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(178, 0);
    ctx.lineTo(80, 160);
    ctx.lineTo(0, 160);
    ctx.closePath();
    ctx.fill();
    return new THREE.CanvasTexture(textureCanvas);
  }

  function makeContactShadowTexture() {
    const textureCanvas = document.createElement("canvas");
    textureCanvas.width = 256;
    textureCanvas.height = 128;
    const ctx = textureCanvas.getContext("2d");
    const shadow = ctx.createRadialGradient(128, 64, 8, 128, 64, 120);
    shadow.addColorStop(0, "rgba(0,0,0,0.72)");
    shadow.addColorStop(0.52, "rgba(0,0,0,0.34)");
    shadow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = shadow;
    ctx.fillRect(0, 0, 256, 128);
    return new THREE.CanvasTexture(textureCanvas);
  }

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(
    35,
    window.innerWidth / window.innerHeight,
    0.01,
    100
  );

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x000000, 0);
  if ("outputColorSpace" in renderer) {
    renderer.outputColorSpace = THREE.SRGBColorSpace;
  } else {
    renderer.outputEncoding = THREE.sRGBEncoding;
  }
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  scene.add(new THREE.AmbientLight(0xffffff, 0.3));

  const keyLight = new THREE.DirectionalLight(0xffffff, 1.05);
  keyLight.position.set(2.5, 4, 3);
  scene.add(keyLight);

  const rimAccent = new THREE.PointLight(new THREE.Color(COLORS.accent), 1.25, 8);
  rimAccent.position.set(-1.5, 0.6, 1.5);
  scene.add(rimAccent);

  const rimGreen = new THREE.PointLight(new THREE.Color(COLORS.neon), 0.65, 8);
  rimGreen.position.set(1.5, 0.4, -1);
  scene.add(rimGreen);

  const laptop = new THREE.Group();
  laptop.position.set(0.16, -0.02, -0.05);
  laptop.rotation.y = -0.035;
  scene.add(laptop);

  const chromeMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(COLORS.chrome),
    metalness: 0.72,
    roughness: 0.3,
    transparent: true,
    opacity: 1
  });

  const deckMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(COLORS.chromeDark),
    metalness: 0.42,
    roughness: 0.48,
    transparent: true,
    opacity: 1
  });

  const base = new THREE.Mesh(roundedSlabGeometry(2.4, 1.6, 0.065, 0.085), chromeMat);
  laptop.add(base);

  const deck = new THREE.Mesh(roundedSlabGeometry(2.25, 1.44, 0.012, 0.065), deckMat);
  deck.position.y = 0.039;
  laptop.add(deck);

  const hingeMat = new THREE.MeshStandardMaterial({
    color: 0x1a1a1e,
    metalness: 0.7,
    roughness: 0.34,
    transparent: true,
    opacity: 1
  });

  [-0.71, 0.71].forEach((x) => {
    const hinge = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.48, 20), hingeMat);
    hinge.rotation.z = Math.PI / 2;
    hinge.position.set(x, 0.045, -0.755);
    laptop.add(hinge);
  });

  const shadowMat = new THREE.MeshBasicMaterial({
    map: makeContactShadowTexture(),
    transparent: true,
    opacity: 0.68,
    depthWrite: false
  });
  const contactShadow = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 2.15), shadowMat);
  contactShadow.rotation.x = -Math.PI / 2;
  contactShadow.position.set(0, -0.055, 0.05);
  contactShadow.renderOrder = -1;
  scene.add(contactShadow);

  const screenMat = new THREE.MeshPhysicalMaterial({
    color: 0x050506,
    emissive: 0xffffff,
    emissiveMap: makeScreenTexture(),
    emissiveIntensity: 0,
    roughness: 0.18,
    metalness: 0.18,
    clearcoat: 0.65,
    clearcoatRoughness: 0.18,
    transparent: true,
    opacity: 1
  });

  const lidPivot = new THREE.Group();
  lidPivot.position.set(0, 0.036, -0.77);
  laptop.add(lidPivot);

  const lidBezel = new THREE.Mesh(roundedSlabGeometry(2.25, 1.5, 0.042, 0.075), chromeMat);
  lidBezel.rotation.x = Math.PI / 2;
  lidBezel.position.set(0, 0.75, 0.021);
  lidPivot.add(lidBezel);

  const screenMesh = new THREE.Mesh(new THREE.PlaneGeometry(2.06, 1.31), screenMat);
  screenMesh.position.set(0, 0.75, 0.044);
  lidPivot.add(screenMesh);

  const brandTexture = makeBrandTexture();
  brandTexture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  brandTexture.minFilter = THREE.LinearMipmapLinearFilter;
  brandTexture.magFilter = THREE.LinearFilter;
  brandTexture.generateMipmaps = true;

  const brandMat = new THREE.MeshBasicMaterial({
    map: brandTexture,
    transparent: true,
    opacity: 0,
    alphaTest: 0.01,
    depthWrite: false,
    toneMapped: false,
    side: THREE.DoubleSide
  });
  const brandMesh = new THREE.Mesh(new THREE.PlaneGeometry(2.04, 1.29), brandMat);
  brandMesh.position.set(0, 0.75, 0.05);
  brandMesh.renderOrder = 3;
  lidPivot.add(brandMesh);

  const reflectionMat = new THREE.MeshBasicMaterial({
    map: makeReflectionTexture(),
    transparent: true,
    opacity: 0,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });
  const reflectionMesh = new THREE.Mesh(new THREE.PlaneGeometry(2.04, 1.29), reflectionMat);
  reflectionMesh.position.set(0, 0.75, 0.046);
  lidPivot.add(reflectionMesh);

  const CLOSED_ROT = -Math.PI / 2 - 0.012;
  const OPEN_ROT = -0.16;
  lidPivot.rotation.x = CLOSED_ROT;

  // Opening composition places the laptop off-center; the end point is normal to
  // the display and looks directly at its world-space center.
  const camStart = {
    pos: new THREE.Vector3(2.85, 1.72, 3.65),
    look: new THREE.Vector3(-0.24, 0.34, -0.28)
  };
  const camEnd = {
    pos: new THREE.Vector3(0.16, 0.79, 0.28),
    look: new THREE.Vector3(0.16, 0.79, -0.87)
  };

  camera.position.copy(camStart.pos);
  camera.lookAt(camStart.look);

  const lookTarget = new THREE.Vector3();
  let startTime = null;

  function frame(now) {
    if (!startTime) startTime = now;
    const t = now - startTime;

    canvas.style.opacity = String(Math.min(1, t / TIMING.fadeIn));

    if (t >= TIMING.openStart) {
      const openProgress = Math.min(1, (t - TIMING.openStart) / TIMING.openDuration);
      const openEase = easeOutCubic(openProgress);
      lidPivot.rotation.x = lerp(CLOSED_ROT, OPEN_ROT, openEase);
      screenMat.emissiveIntensity = lerp(0, 1.05, openEase);
      brandMat.opacity = openEase;
      reflectionMat.opacity = lerp(0, 0.34, openEase);
    }

    if (t > TIMING.openStart + TIMING.openDuration && t < TIMING.zoomStart + 200) {
      screenMat.emissiveIntensity = 1.05 + Math.sin(t / 220) * 0.12;
    }

    const brandFadeStart = TIMING.zoomStart - 200;
    if (t >= brandFadeStart) {
      const brandFadeProgress = Math.min(1, (t - brandFadeStart) / 2200);
      brandMat.opacity = 1 - easeInOutCubic(brandFadeProgress);
    }

    if (t >= TIMING.zoomStart) {
      const zoomProgress = Math.min(1, (t - TIMING.zoomStart) / TIMING.zoomDuration);
      const zoomEase = easeInOutCubic(zoomProgress);
      camera.position.lerpVectors(camStart.pos, camEnd.pos, zoomEase);
      lookTarget.lerpVectors(camStart.look, camEnd.look, zoomEase);
      camera.lookAt(lookTarget);

      const fadeOut = Math.max(0, (zoomEase - 0.55) / 0.45);
      chromeMat.opacity = 1 - fadeOut;
      deckMat.opacity = 1 - fadeOut;
      hingeMat.opacity = 1 - fadeOut;
      shadowMat.opacity = 0.68 * (1 - fadeOut);
      reflectionMat.opacity = 0.34 * (1 - fadeOut * 0.45);
    }

    if (t >= TIMING.crossfadeStart) {
      const crossfadeProgress = Math.min(
        1,
        (t - TIMING.crossfadeStart) / TIMING.crossfadeDuration
      );
      canvas.style.opacity = String(1 - crossfadeProgress);
      siteParts.forEach((part) => { part.style.opacity = String(crossfadeProgress); });
    }

    renderer.render(scene, camera);

    if (t < TIMING.removeAt) {
      requestAnimationFrame(frame);
    } else {
      renderer.dispose();
      finish();
    }
  }

  requestAnimationFrame(frame);
})();
