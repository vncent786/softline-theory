(() => {
  const mainImage = document.querySelector('[data-main-image]');
  const thumbs = Array.from(document.querySelectorAll('[data-gallery-thumb]'));
  const activeLabel = document.querySelector('[data-active-image-label]');

  if (!mainImage || thumbs.length === 0) return;

  function selectThumb(button) {
    const full = button.dataset.full;
    const alt = button.dataset.alt || '';
    if (!full) return;

    mainImage.style.opacity = '0.35';
    const preload = new Image();
    preload.onload = () => {
      mainImage.src = full;
      mainImage.alt = alt;
      mainImage.style.opacity = '1';
      if (activeLabel) activeLabel.textContent = button.dataset.label || '';
    };
    preload.src = full;

    thumbs.forEach((item) => {
      item.classList.toggle('active', item === button);
      item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
    });
  }

  thumbs.forEach((button) => button.addEventListener('click', () => selectThumb(button)));
})();
