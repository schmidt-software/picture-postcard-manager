// Image previews for the overview and the detail page.

import { translate } from "./i18n.js";

const IMAGES_PREFIX = "/images/";
const THUMBS_PREFIX = "/images/thumbs/";

// Return the server thumbnail URL for a same-origin /images/ file, or null.
// Only direct children of /images/ get a thumbnail URL; the server falls back
// to the original when no thumbnail can be generated (e.g. without Pillow).
export function thumbnailUrl(url) {
  if (!url.pathname.startsWith(IMAGES_PREFIX)) return null;
  const name = url.pathname.slice(IMAGES_PREFIX.length);
  if (!name || name.includes("/")) return null;
  return new URL(THUMBS_PREFIX + name, url.href);
}

// Resolve an image path to a same-origin http(s) URL, or null. Used for all
// previews so external hosts and active-content URLs from imported data are
// never contacted or rendered.
export function sameOriginImageUrl(imagePath) {
  if (typeof imagePath !== "string" || !imagePath.trim()) return null;
  let url;
  try {
    url = new URL(imagePath, window.location.href);
  } catch (error) {
    if (error.name !== "TypeError") throw error;
    return null;
  }
  if (url.origin !== new URL(window.location.href).origin
      || !["http:", "https:"].includes(url.protocol)) return null;
  return url;
}

export function imagePreview(imagePath, side, fullSize = false) {
  const cell = document.createElement(fullSize ? "figure" : "td");
  if (fullSize) {
    cell.className = "detail-photo";
    const caption = document.createElement("figcaption");
    caption.dataset.i18n = side;
    caption.textContent = translate(side);
    cell.append(caption);
  }
  const fallback = document.createElement("span");
  fallback.className = "image-fallback";
  fallback.dataset.i18n = imagePath ? "imageUnavailable" : "noImage";
  fallback.textContent = translate(fallback.dataset.i18n);
  cell.append(fallback);
  const url = sameOriginImageUrl(imagePath);
  if (!url) return cell;

  const image = document.createElement("img");
  image.className = fullSize ? "postcard-photo" : "postcard-thumbnail";
  image.dataset.i18nAlt = side;
  image.alt = translate(side);
  image.loading = fullSize ? "eager" : "lazy";
  if (!fullSize) {
    image.width = 96;
    image.height = 72;
  }
  image.addEventListener("load", () => {
    image.hidden = false;
    image.style.visibility = "visible";
    fallback.hidden = true;
  });
  // Overview previews use the server-side thumbnail of same-origin uploads;
  // if the thumbnail request fails (e.g. an older server), retry once with
  // the original before showing the localized fallback text.
  const thumb = fullSize ? null : thumbnailUrl(url);
  image.addEventListener("error", () => {
    if (thumb && image.src === thumb.href) {
      image.src = url.href;
      return;
    }
    image.hidden = true;
    fallback.hidden = false;
  });
  cell.append(image);
  image.src = (thumb ?? url).href;
  return cell;
}
