const grid = document.getElementById('artGrid');
const emptyState = document.getElementById('emptyState');
const count = document.getElementById('collectionCount');
let artwork = [];
let selected = 'all';
const dialog = document.getElementById('artDialog');
const escapeHtml = (value = '') => String(value).replace(/[&<>'\"]/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));

function visibleArtwork() {
  return artwork.filter((item) => selected === 'all' || item.collection === selected);
}

function render() {
  const items = visibleArtwork();
  count.textContent = `${items.length} ${items.length === 1 ? 'work' : 'works'} selected`;
  grid.innerHTML = items.map((item) => {
    const extra = [item.medium, item.dimensions].filter(Boolean).join(' · ') || item.collection;
    return `<button class="art-card" type="button" data-artwork-id="${item.id}"><div class="art-image"><img src="${item.url}" alt="${escapeHtml(item.title || 'Black Canvas artwork')}"></div><div class="art-copy"><p>${escapeHtml(item.collection || 'Black Canvas')}</p><h3>${escapeHtml(item.title || 'Untitled work')}</h3><small>${escapeHtml(extra)}</small></div></button>`;
  }).join('');
  emptyState.hidden = items.length !== 0;
}

function showArtwork(id) {
  const item = artwork.find((artworkItem) => artworkItem.id === Number(id));
  if (!item) return;
  document.getElementById('dialogImage').src = item.url;
  document.getElementById('dialogImage').alt = item.title || 'Black Canvas artwork';
  document.getElementById('dialogCollection').textContent = item.collection || 'Black Canvas';
  document.getElementById('dialogTitle').textContent = item.title || 'Untitled work';
  document.getElementById('dialogDescription').textContent = item.notes || 'A selected work from the Black Canvas collection.';
  document.getElementById('dialogMedium').textContent = item.medium || 'Original artwork';
  document.getElementById('dialogDimensions').textContent = item.dimensions || 'Details available soon';
  document.getElementById('dialogAvailability').textContent = item.sale_status === 'Ready to list' ? 'Available' : 'In the studio';
  dialog.showModal();
}

grid.addEventListener('click', (event) => {
  const card = event.target.closest('[data-artwork-id]');
  if (card) showArtwork(card.dataset.artworkId);
});

document.getElementById('closeDialog').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });

document.querySelectorAll('[data-filter]').forEach((button) => {
  button.addEventListener('click', () => {
    selected = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach((item) => item.classList.toggle('active', item === button));
    render();
  });
});

fetch('/api/artworks').then((response) => response.ok ? response.json() : []).then((items) => {
  artwork = items.filter((item) => item.filename && item.gallery_visible && item.sale_status !== 'Sold' && item.sale_status !== 'Not for sale');
  render();
}).catch(() => { count.textContent = 'Artwork will appear here'; emptyState.hidden = false; });

document.getElementById('year').textContent = new Date().getFullYear();

const galleryEditor = document.getElementById('galleryEditor');
let gallerySettings = {};
function applyGallerySettings(settings) {
  gallerySettings = settings;
  document.getElementById('artistName').textContent = settings.artist_name.toUpperCase();
  document.getElementById('galleryIntro').textContent = settings.intro;
  const hasShop = Boolean(settings.shop_url);
  const shopNav = document.getElementById('shopNav'); shopNav.href = settings.shop_url || '#collection'; shopNav.hidden = !hasShop;
  const shop = document.getElementById('shopLink'); shop.href = settings.shop_url || '#collection'; shop.hidden = !hasShop;
  const pinterest = document.getElementById('pinterestLink'); pinterest.href = settings.pinterest_url || '#collection'; pinterest.hidden = !settings.pinterest_url;
  document.getElementById('galleryLinkNote').hidden = hasShop || Boolean(settings.pinterest_url);
}
fetch('/api/gallery-settings').then((response) => response.ok ? response.json() : null).then((settings) => { if (settings) applyGallerySettings(settings); });
if (new URLSearchParams(window.location.search).get('edit') === '1') {
  const openButton = document.getElementById('openGalleryEditor');
  openButton.hidden = false;
  openButton.addEventListener('click', () => {
    document.getElementById('settingArtistName').value = gallerySettings.artist_name || '';
    document.getElementById('settingIntro').value = gallerySettings.intro || '';
    document.getElementById('settingShopUrl').value = gallerySettings.shop_url || '';
    document.getElementById('settingPinterestUrl').value = gallerySettings.pinterest_url || '';
    galleryEditor.showModal();
  });
  document.getElementById('saveGallerySettings').addEventListener('click', async (event) => {
    event.preventDefault();
    const settings = { artist_name: document.getElementById('settingArtistName').value, intro: document.getElementById('settingIntro').value, shop_url: document.getElementById('settingShopUrl').value, pinterest_url: document.getElementById('settingPinterestUrl').value };
    const response = await fetch('/api/gallery-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) });
    if (!response.ok) return alert('Please make sure links begin with https://');
    applyGallerySettings(await response.json()); galleryEditor.close();
  });
}
