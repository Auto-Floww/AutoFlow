import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";
import { createScreenTexture } from "./phone-screen-texture.js";

const canvas = document.getElementById("phoneCanvas");
const visual = document.getElementById("phoneVisual");
const overlay = document.getElementById("phoneScreenOverlay");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(29, 1, 0.1, 100);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
const phoneRoot = new THREE.Group();
const clock = new THREE.Clock();

const screenHelper = createScreenTexture();
const CHAT_START_PROGRESS = 0.56;
const CHAT_END_PROGRESS = 0.98;

let frameId = 0;
let targetProgress = reducedMotion ? 1 : 0;
let currentProgress = targetProgress;
let isRunning = false;
let isReady = false;
let screenMaterial = null;

// State for messages animation
let showChat = false;
let messageOpacities = new Array(screenHelper.messageCount).fill(0);
let targetOpacities = new Array(screenHelper.messageCount).fill(0);

renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.08;
scene.add(phoneRoot);

camera.position.set(0, 0.05, 8.6);

const ambient = new THREE.AmbientLight(0xffffff, 0.52);
const rimLight = new THREE.DirectionalLight(0x25d366, 4.2);
rimLight.position.set(-3.5, 2.6, -4.5);

RectAreaLightUniformsLib.init();
const reflectionLight = new THREE.RectAreaLight(0xffffff, 5.5, 3.6, 5.2);
reflectionLight.position.set(2.4, 1.8, 4.2);
reflectionLight.lookAt(0, 0, 0);

scene.add(ambient, rimLight, reflectionLight);

// Generate simple environment map for reflections
const pmremGenerator = new THREE.PMREMGenerator(renderer);
pmremGenerator.compileEquirectangularShader();
const envScene = new THREE.Scene();
const envLight = new THREE.DirectionalLight(0xffffff, 1.5);
envLight.position.set(1, 1, 1);
envScene.add(envLight);
const envMap = pmremGenerator.fromScene(envScene).texture;
scene.environment = envMap;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const resize = () => {
  if (!visual) return;
  const width = Math.max(1, visual.clientWidth);
  const height = Math.max(1, visual.clientHeight);
  const mobileRatio = window.innerWidth <= 860 ? 1.5 : 2;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, mobileRatio));
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  if (!isRunning) renderer.render(scene, camera);
};

const renderFrame = () => {
  const delta = Math.min(clock.getDelta(), 0.05);
  const damping = 1 - Math.exp(-delta * 7.5);
  currentProgress = THREE.MathUtils.lerp(currentProgress, targetProgress, damping);
  
  let extraRotation = 0;
  if (currentProgress < 0.4) {
    const t = currentProgress / 0.4;
    const ease = t * t * (3 - 2 * t);
    extraRotation = (1 - ease) * Math.PI * 2;
  }
  
  const rotation = THREE.MathUtils.lerp(-0.3, 0, currentProgress) - extraRotation;
  const cameraZ = THREE.MathUtils.lerp(8.6, 8.38, currentProgress);
  const floatOffset = reducedMotion ? 0 : Math.sin(clock.elapsedTime * 1.35) * 0.038 * (1 - currentProgress * 0.7);

  phoneRoot.rotation.y = rotation;
  phoneRoot.position.y = floatOffset;
  camera.position.z = cameraZ;

  // Update opacities for messages
  for (let i = 0; i < messageOpacities.length; i++) {
    if (Math.abs(messageOpacities[i] - targetOpacities[i]) > 0.001) {
      messageOpacities[i] = THREE.MathUtils.lerp(messageOpacities[i], targetOpacities[i], damping * 0.9);
    }
  }

  // Draw 2D canvas if state changed
  screenHelper.update(showChat, messageOpacities);

  renderer.render(scene, camera);

  if (isRunning) frameId = requestAnimationFrame(renderFrame);
};

const loader = new GLTFLoader();
const modelUrl = "assets/iphone-16/1b338ec19f15ad72904b%20(1).gltf";
const stripTextureProperties = (value) => {
  if (!value || typeof value !== "object") return;
  Object.keys(value).forEach((key) => {
    if (key.endsWith("Texture")) {
      delete value[key];
      return;
    }
    stripTextureProperties(value[key]);
  });
};

const mountModel = (gltf) => {
  const model = gltf.scene;
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const scale = 4.08 / Math.max(size.y, 0.001);

  model.scale.setScalar(scale);
  model.position.copy(center).multiplyScalar(-scale);
  model.traverse((object) => {
    if (!object.isMesh) return;
    object.castShadow = true;
    object.receiveShadow = true;
    if (object.material) {
      object.material.envMapIntensity = 1.15;
      
      // Identify the screen material
      if (object.material.name === "4130c6244c49c5d5712e" || object.name === "baf05346569e3be49c2a") {
        screenMaterial = object.material;
        
        // Adjust texture mapping to match the mesh's UV coordinates (U spans from 0.018 to 0.48)
        screenHelper.texture.repeat.set(2.1658, 1);
        screenHelper.texture.offset.set(-0.0393, 0);
        
        screenMaterial.map = screenHelper.texture;
        screenMaterial.emissiveMap = screenHelper.texture;
        screenMaterial.emissive = new THREE.Color(0xffffff);
        screenMaterial.emissiveIntensity = 0.8;
        screenMaterial.needsUpdate = true;
      }
    }
  });

  phoneRoot.add(model);
  phoneRoot.rotation.y = targetProgress === 1 ? 0 : -0.3;
  isReady = true;
  resize();
  if (!isRunning) renderer.render(scene, camera);
};

fetch(modelUrl)
  .then((response) => {
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  })
  .then((gltfJson) => {
    stripTextureProperties(gltfJson.materials);
    delete gltfJson.images;
    delete gltfJson.textures;
    delete gltfJson.samplers;
    loader.parse(
      JSON.stringify(gltfJson),
      "assets/iphone-16/",
      mountModel,
      () => visual?.classList.add("phone-model-error")
    );
  })
  .catch(() => visual?.classList.add("phone-model-error"));

const resizeObserver = new ResizeObserver(resize);
if (visual) resizeObserver.observe(visual);

// Hide overlay element via style since we're drawing on the canvas now
if (overlay) overlay.style.display = "none";

export const phoneScene = {
  setProgress(progress) {
    targetProgress = reducedMotion ? 1 : clamp(progress, 0, 1);
    
    // Logic for chat display
    showChat = targetProgress >= CHAT_START_PROGRESS;
    
    // Stagger messages appearance across a longer part of the scroll.
    if (showChat) {
      const msgProgress = clamp(
        (targetProgress - CHAT_START_PROGRESS) / (CHAT_END_PROGRESS - CHAT_START_PROGRESS),
        0,
        1
      );
      for (let i = 0; i < screenHelper.messageCount; i++) {
        const threshold = (i + 0.22) / screenHelper.messageCount;
        targetOpacities[i] = msgProgress > threshold ? 1 : 0;
      }
    } else {
      targetOpacities.fill(0);
    }
    
    if (reducedMotion) {
      messageOpacities = [...targetOpacities];
    }

    if (!isRunning && isReady) {
      currentProgress = targetProgress;
      renderFrame();
    }
  },
  start() {
    if (isRunning) return;
    isRunning = true;
    clock.start();
    frameId = requestAnimationFrame(renderFrame);
  },
  stop() {
    isRunning = false;
    if (frameId) cancelAnimationFrame(frameId);
    frameId = 0;
    clock.stop();
  },
  resize
};

resize();
