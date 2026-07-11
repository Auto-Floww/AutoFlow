import { phoneScene } from "./phone-scene.js";

const section = document.getElementById("demo");
const steps = Array.from(document.querySelectorAll("#scrollTrack .track-step"));
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let visible = false;
let ticking = false;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const updateSteps = (progress) => {
  const activeIndex = reducedMotion ? steps.length - 1 : Math.min(steps.length - 1, Math.floor(progress * steps.length));
  steps.forEach((step, index) => step.classList.toggle("is-active", index === activeIndex));
};

const update = () => {
  ticking = false;
  const stage = document.querySelector(".demo-stage");
  const sticky = document.querySelector(".demo-sticky");
  if (!stage || !sticky) return;

  const stageRect = stage.getBoundingClientRect();
  const stickyRect = sticky.getBoundingClientRect();
  const computedTop = parseFloat(window.getComputedStyle(sticky).top) || 0;

  const scrolled = computedTop - stageRect.top;
  const totalScroll = stageRect.height - stickyRect.height;
  const progress = reducedMotion ? 1 : clamp(totalScroll > 0 ? scrolled / totalScroll : 0, 0, 1);

  phoneScene.setProgress(progress);
  updateSteps(progress);
};

const requestUpdate = () => {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(update);
};

const observer = new IntersectionObserver(
  ([entry]) => {
    visible = entry.isIntersecting;
    if (visible) {
      phoneScene.start();
      window.addEventListener("scroll", requestUpdate, { passive: true });
      requestUpdate();
    } else {
      window.removeEventListener("scroll", requestUpdate);
      phoneScene.stop();
    }
  },
  { rootMargin: "18% 0px", threshold: 0 }
);

if (section) observer.observe(section);

window.addEventListener("resize", () => {
  phoneScene.resize();
  if (visible) requestUpdate();
});

if (reducedMotion) {
  phoneScene.setProgress(1);
  updateSteps(1);
}
