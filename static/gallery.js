const grid = document.getElementById('artGrid');
const emptyState = document.getElementById('emptyState');
const count = document.getElementById('collectionCount');
const dialog = document.getElementById('artDialog');
const featuredArtwork = document.getElementById('featuredArtwork');
let artwork = [];
let selected = 'all';
let gallerySettings = {};

const escapeHtml = (value = '') => String(value).replace(/[&<>'\"]/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
const frameClass = (collection = '') => `frame-${collection.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'black-canvas'}`;
const money = (value) => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0}).format(value);

function visibleArtwork() {
  return artwork.filter((item) => selected === 'all' || item.collection === selected);
}

function render() {
  const items = visibleArtwork();
  count.textContent = `${items.length} ${items.length === 1 ? 'work' : 'works'} on view`;
  grid.innerHTML = items.map((item, index) => {
    const extra = [item.medium, item.dimensions].filter(Boolean).join(' · ') || item.collection;
    return `<button class="art-card ${frameClass(item.collection)} position-${index % 7}" type="button" data-artwork-id="${item.id}">
      <span class="frame-shell"><span class="art-image"><img src="${item.url}" alt="${escapeHtml(item.title || 'Black Canvas artwork')}" loading="lazy"></span></span>
      <span class="art-copy"><span class="work-number">${String(index + 1).padStart(2, '0')}</span><span><small>${escapeHtml(item.collection || 'Black Canvas')}</small><strong>${escapeHtml(item.title || 'Untitled work')}</strong><em>${escapeHtml(extra)}</em></span></span>
    </button>`;
  }).join('');
  emptyState.hidden = items.length !== 0;
}

function setFeatured(item) {
  if (!item) return;
  featuredArtwork.disabled = false;
  featuredArtwork.dataset.artworkId = item.id;
  document.getElementById('featuredImage').src = item.url;
  document.getElementById('featuredImage').alt = item.title || 'Featured Black Canvas artwork';
  document.getElementById('featuredTitle').textContent = item.title || 'Untitled work';
  document.getElementById('featuredMeta').textContent = [item.collection, item.medium, item.dimensions].filter(Boolean).join(' · ');
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
  document.getElementById('dialogAvailability').textContent = ['Ready to list', 'Listed'].includes(item.sale_status) ? 'Available to collect' : 'Currently in the studio';
  const priceRow = document.getElementById('dialogPriceRow');
  priceRow.hidden = !(Number(item.price) > 0 && ['Ready to list', 'Listed'].includes(item.sale_status));
  document.getElementById('dialogPrice').textContent = Number(item.price) > 0 ? money(item.price) : 'Inquire';
  const shopLink = document.getElementById('dialogShopLink');
  shopLink.href = gallerySettings.shop_url || '#';
  shopLink.hidden = !gallerySettings.shop_url;
  dialog.showModal();
}

grid.addEventListener('click', (event) => {
  const card = event.target.closest('[data-artwork-id]');
  if (card) showArtwork(card.dataset.artworkId);
});
featuredArtwork.addEventListener('click', () => showArtwork(featuredArtwork.dataset.artworkId));
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
  setFeatured(artwork[0]);
  document.getElementById('totalWorks').textContent = `${artwork.length} ${artwork.length === 1 ? 'work' : 'works'} from the studio archive`;
  render();
}).catch(() => { count.textContent = 'Artwork will appear here'; emptyState.hidden = false; });

const year = new Date().getFullYear();
document.getElementById('year').textContent = year;
document.getElementById('footerYear').textContent = year;

const galleryEditor = document.getElementById('galleryEditor');
function setExternalLink(element, url) {
  element.href = url || '#collection';
  element.hidden = !url;
  if (url) { element.target = '_blank'; element.rel = 'noreferrer'; }
}
function applyGallerySettings(settings) {
  gallerySettings = settings;
  const artistName = settings.artist_name || 'Jeffrey McKay';
  document.getElementById('artistName').textContent = artistName;
  document.getElementById('footerArtist').textContent = artistName;
  document.getElementById('galleryIntro').textContent = settings.intro || 'A living archive of color, story, texture, and Black imagination.';
  setExternalLink(document.getElementById('shopNav'), settings.shop_url);
  setExternalLink(document.getElementById('shopLink'), settings.shop_url);
  setExternalLink(document.getElementById('pinterestLink'), settings.pinterest_url);
  document.getElementById('galleryLinkNote').hidden = Boolean(settings.shop_url || settings.pinterest_url);
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
    const settings = {
      artist_name: document.getElementById('settingArtistName').value,
      intro: document.getElementById('settingIntro').value,
      shop_url: document.getElementById('settingShopUrl').value,
      pinterest_url: document.getElementById('settingPinterestUrl').value,
    };
    const response = await fetch('/api/gallery-settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(settings)});
    if (!response.ok) return alert('Please make sure links begin with https://');
    applyGallerySettings(await response.json());
    galleryEditor.close();
  });
}
