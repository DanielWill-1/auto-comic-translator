const dynamicSamples = [
  {
    src: "../../datas/japanes/Screenshot%202026-06-29%20122810.png",
    alt: "Japanese comic page added for the dynamic discovery test",
    label: "Japanese portrait (dynamic)",
  },
  {
    src: "../../datas/chinese/Screenshot%202026-09-26%20015428.png",
    alt: "Chinese comic crop added for the dynamic discovery test",
    label: "Chinese landscape (dynamic)",
  },
  {
    src: "../../datas/korean/Screenshot%202026-09-26%20015601.png",
    alt: "Korean comic panel added for the dynamic discovery test",
    label: "Korean landscape (dynamic)",
  },
];

// A real candidate (829 x 472) used by the explicit lazy-source control.
const lazySource =
  "../../datas/chinese/Screenshot%202026-09-26%20015443.png";

const dynamicReader = document.querySelector("#dynamic-reader");
const addButton = document.querySelector("#add-comic-image");
const removeButton = document.querySelector("#remove-comic-image");
const lazyButton = document.querySelector("#load-lazy-image");
const responsiveButton = document.querySelector("#toggle-responsive");
const addedCount = document.querySelector("#added-count");
const lazyImage = document.querySelector("#lazy-comic-image");
const responsiveCard = document.querySelector(".responsive-card");
let addedImages = 0;

function updateCount() {
  addedCount.textContent =
    addedImages === 0
      ? "No extra images added"
      : `${addedImages} dynamic image${addedImages === 1 ? "" : "s"} added`;
}

addButton.addEventListener("click", () => {
  const sample = dynamicSamples[addedImages % dynamicSamples.length];
  const figure = document.createElement("figure");
  const caption = document.createElement("figcaption");
  const image = document.createElement("img");

  figure.className = "comic-panel dynamic-panel";
  caption.textContent = `${sample.label} · added dynamically`;
  image.className = "comic-image";
  image.src = sample.src;
  image.alt = sample.alt;
  figure.append(caption, image);
  dynamicReader.append(figure);

  addedImages += 1;
  updateCount();
});

removeButton.addEventListener("click", () => {
  const panels = dynamicReader.querySelectorAll(".dynamic-panel");
  panels[panels.length - 1]?.remove();
  addedImages = Math.max(0, addedImages - 1);
  updateCount();
});

// Explicit replacement, never a timer: the placeholder is not translatable and
// the real source must become the candidate.
lazyButton.addEventListener("click", () => {
  if (lazyImage.getAttribute("src") === lazySource) {
    return;
  }
  lazyImage.src = lazySource;
  lazyButton.textContent = "Real image loaded";
  lazyButton.disabled = true;
});

responsiveButton.addEventListener("click", () => {
  responsiveCard.classList.toggle("narrow");
  responsiveButton.textContent = responsiveCard.classList.contains("narrow")
    ? "Toggle responsive width (currently narrow)"
    : "Toggle responsive width";
});
