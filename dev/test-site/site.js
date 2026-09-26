const comicSamples = [
  {
    src: "../../datas/japanes/Screenshot%202026-06-29%20122805.png",
    alt: "Japanese comic page added for the discovery test",
    label: "Japanese portrait page",
  },
  {
    src: "../../datas/chinese/Screenshot%202026-09-26%20015428.png",
    alt: "Chinese landscape snippet added for the discovery test",
    label: "Chinese landscape snippet",
  },
];

const reader = document.querySelector("#comic-reader");
const addButton = document.querySelector("#add-comic-image");
const addedCount = document.querySelector("#added-count");
let addedImages = 0;

addButton.addEventListener("click", () => {
  const sample = comicSamples[addedImages % comicSamples.length];
  const figure = document.createElement("figure");
  const caption = document.createElement("figcaption");
  const image = document.createElement("img");

  figure.className = "comic-panel";
  caption.textContent = `${sample.label} · added dynamically`;
  image.className = "comic-image";
  image.src = sample.src;
  image.alt = sample.alt;
  figure.append(caption, image);
  reader.append(figure);

  addedImages += 1;
  addedCount.textContent = `${addedImages} extra image${
    addedImages === 1 ? "" : "s"
  } added`;
});
