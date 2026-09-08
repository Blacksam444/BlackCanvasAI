const grid = document.getElementById('artGrid');
const emptyState = document.getElementById('emptyState');
const count = document.getElementById('collectionCount');
const dialog = document.getElementById('artDialog');
const featuredArtwork = document.getElementById('featuredArtwork');
let artwork = [];
const collectionExhibitions = {
  AfroNova: {
    title: '<span>Afro</span><br>Nova',
    intro: 'A world of future royalty, celestial color, ancestral memory, and unapologetic Black imagination.',
    quote: '“The future is not a place we wait for—it is a world we crown ourselves inside.”',
    first: 'AfroNova places Black identity at the center of imagined futures: luminous, regal, rooted, and expansive.',
    second: 'These works move between portraiture, mythology, and the cosmos—each one carrying a private sense of power.',
    heading: 'AfroNova exhibition',
  },
  'Quiet Nova': {
    title: '<span>Quiet</span><br>Nova',
    intro: 'Interior light, presence, tenderness, and the quiet worlds that exist beneath the noise.',
    quote: '“Stillness is not absence. It is the space where a life becomes visible.”',
    first: 'Quiet Nova honors the emotional weight of an unguarded moment, a familiar room, or a gaze held long enough to be felt.',
    second: 'The collection leaves room for softness, detail, and the kind of strength that does not need to announce itself.',
    heading: 'Quiet Nova exhibition',
  },
  GraffitiX: {
    title: '<span>Graffiti</span><br>X',
    intro: 'Raw color, street rhythm, symbolic marks, and a visual language that refuses to stay inside the lines.',
    quote: '“A mark becomes a message when it carries the pressure of the hand that made it.”',
    first: 'GraffitiX is built from collision: gesture, portraiture, scratched surfaces, paint, symbols, and the memory of a city wall.',
    second: 'Every work keeps the figure emotionally present while the surrounding marks make noise, record history, and leave a trace.',
    heading: 'GraffitiX exhibition',
  },
};
const requestedCollection = new URLSearchParams(window.location.search).get('collection');
let selected = Object.prototype.hasOwnProperty.call(collectionExhibitions, requestedCollection) ? requestedCollection : 'all';
let gallerySettings = {};
let dialogIndex = 0;

const escapeHtml = (value = '') => String(value).replace(/[&<>'\"]/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
const frameClass = (collection = '') => `frame-${collection.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'black-canvas'}`;
const money = (value) => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0}).format(value);

function applyExhibition() {
  const exhibition = collectionExhibitions[selected];
  document.body.classList.remove('collection-afronova', 'collection-quiet-nova', 'collection-graffitix');
  if (!exhibition) {
    document.getElementById('heroKicker').innerHTML = `CURRENT EXHIBITION · <span id="year">${new Date().getFullYear()}</span>`;
    document.getElementById('heroTitle').innerHTML = '<span>Black</span><br>Canvas';
    document.getElementById('galleryIntro').textContent = 'A living archive of color, story, texture, and Black imagination.';
    document.getElementById('statementQuote').textContent = '“Every work begins with a feeling—then becomes a world you can stand inside.”';
    document.getElementById('statementFirst').textContent = 'Black Canvas brings together imagined futures, ancestral memory, quiet interior worlds, and the raw language of the street.';
    document.getElementById('statementSecond').textContent = 'Each collection carries its own visual rhythm while remaining part of one evolving creative archive.';
    document.getElementById('collectionKicker').textContent = 'SELECTED WORKS';
    document.getElementById('collectionHeading').textContent = 'The gallery wall';
    return;
  }
  document.body.classList.add(`collection-${selected.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`);
  document.getElementById('heroKicker').innerHTML = `COLLECTION EXHIBITION · <span id="year">${new Date().getFullYear()}</span>`;
  document.getElementById('heroTitle').innerHTML = exhibition.title;
  document.getElementById('galleryIntro').textContent = exhibition.intro;
  document.getElementById('statementQuote').textContent = exhibition.quote;
  document.getElementById('statementFirst').textContent = exhibition.first;
  document.getElementById('statementSecond').textContent = exhibition.second;
  document.getElementById('collectionKicker').textContent = 'SELECTED COLLECTION';
  document.getElementById('collectionHeading').textContent = exhibition.heading;
}

function visibleArtwork() {
  if (selected === 'available') return artwork.filter((item) => ['Ready to list', 'Listed'].includes(item.sale_status));
  if (selected === 'sold') return artwork.filter((item) => item.sale_status === 'Sold');
  if (selected === 'archive') return artwork.filter((item) => !['Ready to list', 'Listed'].includes(item.sale_status));
  return artwork.filter((item) => selected === 'all' || item.collection === selected);
}

function publicArtworkStatus(item) {
  if (['Ready to list', 'Listed'].includes(item.sale_status)) return 'Available to collect';
  if (item.sale_status === 'Sold') return 'Collected';
  if (item.sale_status === 'Not for sale') return 'Not for sale';
  return 'In the studio';
}

function render() {
  const items = visibleArtwork();
  count.textContent = `${items.length} ${items.length === 1 ? 'work' : 'works'} on view`;
  grid.innerHTML = items.map((item, index) => {
    const extra = [item.medium, item.dimensions].filter(Boolean).join(' · ') || item.collection;
    const status = publicArtworkStatus(item);
    return `<button class="art-card ${frameClass(item.collection)} position-${index % 7}" type="button" data-artwork-id="${item.id}">
      <span class="frame-shell"><span class="art-image"><img src="${item.url}" alt="${escapeHtml(item.title || 'Black Canvas artwork')}" loading="lazy"></span></span>
      <span class="art-copy"><span class="work-number">${String(index + 1).padStart(2, '0')}</span><span class="placard-body"><small>${escapeHtml(item.collection || 'Black Canvas')}</small><strong>${escapeHtml(item.title || 'Untitled work')}</strong><em>${escapeHtml(extra)}</em><span class="placard-status">${status}</span></span></span>
    </button>`;
  }).join('');
  emptyState.hidden = items.length !== 0;
}

function dailySpotlight(items) {
  if (!items.length) return null;
  const favorites = items.filter((item) => item.favorite);
  const choices = favorites.length ? favorites : items;
  const start = new Date(new Date().getFullYear(), 0, 0);
  const day = Math.floor((new Date() - start) / 86400000);
  return choices[day % choices.length];
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
  dialogIndex = artwork.indexOf(item);
  document.getElementById('dialogImage').src = item.url;
  document.getElementById('dialogImage').alt = item.title || 'Black Canvas artwork';
  document.getElementById('dialogCollection').textContent = item.collection || 'Black Canvas';
  document.getElementById('dialogTitle').textContent = item.title || 'Untitled work';
  document.getElementById('dialogDescription').textContent = item.notes || 'A selected work from the Black Canvas collection.';
  document.getElementById('dialogPosition').textContent = `${String(dialogIndex + 1).padStart(2, '0')} / ${String(artwork.length).padStart(2, '0')}`;
  document.getElementById('dialogTags').innerHTML = String(item.tags || '').split(',').map((tag) => tag.trim()).filter(Boolean).slice(0, 7).map((tag) => `<span>${escapeHtml(tag)}</span>`).join('');
  document.getElementById('dialogMedium').textContent = item.medium || 'Original artwork';
  document.getElementById('dialogDimensions').textContent = item.dimensions || 'Details available soon';
  document.getElementById('dialogAvailability').textContent = publicArtworkStatus(item);
  const priceRow = document.getElementById('dialogPriceRow');
  priceRow.hidden = !(Number(item.price) > 0 && ['Ready to list', 'Listed'].includes(item.sale_status));
  document.getElementById('dialogPrice').textContent = Number(item.price) > 0 ? money(item.price) : 'Inquire';
  const shopLink = document.getElementById('dialogShopLink');
  const exactListing = item.listing_url || '';
  shopLink.href = exactListing || gallerySettings.shop_url || '#';
  shopLink.textContent = exactListing ? 'View this piece in store ↗' : 'Visit the shop ↗';
  shopLink.hidden = !(exactListing || gallerySettings.shop_url);
  document.getElementById('dialogInquiryLink').href = `/inquire?artwork=${encodeURIComponent(item.id)}`;
  if (!dialog.open) dialog.showModal();
}

function stepArtwork(direction) {
  if (!artwork.length) return;
  dialogIndex = (dialogIndex + direction + artwork.length) % artwork.length;
  showArtwork(artwork[dialogIndex].id);
}

function openSurpriseArtwork() {
  const choices = visibleArtwork();
  if (!choices.length) return;
  const currentId = Number(featuredArtwork.dataset.artworkId || 0);
  const alternatives = choices.length > 1 ? choices.filter((item) => item.id !== currentId) : choices;
  const item = alternatives[Math.floor(Math.random() * alternatives.length)];
  showArtwork(item.id);
}

grid.addEventListener('click', (event) => {
  const card = event.target.closest('[data-artwork-id]');
  if (card) showArtwork(card.dataset.artworkId);
});
featuredArtwork.addEventListener('click', () => showArtwork(featuredArtwork.dataset.artworkId));
document.getElementById('closeDialog').addEventListener('click', () => dialog.close());
document.getElementById('previousArtwork').addEventListener('click', () => stepArtwork(-1));
document.getElementById('nextArtwork').addEventListener('click', () => stepArtwork(1));
document.getElementById('surpriseMe').addEventListener('click', openSurpriseArtwork);
document.getElementById('surpriseFilter').addEventListener('click', openSurpriseArtwork);
dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
document.addEventListener('keydown', (event) => {
  if (!dialog.open) return;
  if (event.key === 'ArrowLeft') stepArtwork(-1);
  if (event.key === 'ArrowRight') stepArtwork(1);
});

document.querySelectorAll('[data-filter]').forEach((button) => {
  button.addEventListener('click', () => {
    selected = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach((item) => item.classList.toggle('active', item === button));
    const url = new URL(window.location.href);
    if (collectionExhibitions[selected]) url.searchParams.set('collection', selected);
    else url.searchParams.delete('collection');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    applyExhibition();
    setFeatured(dailySpotlight(visibleArtwork()));
    render();
  });
});

fetch('/api/gallery-artworks').then((response) => response.ok ? response.json() : []).then((items) => {
  artwork = items;
  applyExhibition();
  document.querySelectorAll('[data-filter]').forEach((button) => button.classList.toggle('active', button.dataset.filter === selected));
  setFeatured(dailySpotlight(visibleArtwork()));
  document.getElementById('totalWorks').textContent = `${artwork.length} ${artwork.length === 1 ? 'work' : 'works'} from the studio archive`;
  render();
}).catch(() => { count.textContent = 'Artwork will appear here'; emptyState.hidden = false; });

// A public gallery can discourage easy downloading, but screenshots can never be fully prevented by a website.
document.addEventListener('contextmenu', (event) => {
  if (event.target.closest('.art-image, .dialog-image, .feature-frame')) event.preventDefault();
});
document.addEventListener('dragstart', (event) => {
  if (event.target.closest('.art-image img, .dialog-image img, .feature-frame img')) event.preventDefault();
});

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
  const publicMode = settings.public_mode === true;
  document.getElementById('privateStudioLink').hidden = publicMode;
  document.getElementById('manageGalleryLink').hidden = publicMode;
  document.getElementById('dialogStudioLink').hidden = publicMode;
  const artistName = settings.artist_name || 'Jeffrey McKay';
  document.getElementById('artistName').textContent = artistName;
  document.getElementById('footerArtist').textContent = artistName;
  document.getElementById('galleryIntro').textContent = settings.intro || 'A living archive of color, story, texture, and Black imagination.';
  setExternalLink(document.getElementById('shopNav'), settings.shop_url);
  setExternalLink(document.getElementById('shopLink'), settings.shop_url);
  setExternalLink(document.getElementById('pinterestLink'), settings.pinterest_url);
  setExternalLink(document.getElementById('instagramLink'), settings.instagram_url);
  const contactLink = document.getElementById('contactLink');
  contactLink.href = settings.contact_email ? `mailto:${settings.contact_email}` : '#collection';
  contactLink.hidden = !settings.contact_email;
  document.getElementById('galleryLinkNote').hidden = Boolean(settings.shop_url || settings.pinterest_url || settings.instagram_url || settings.contact_email);
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
    document.getElementById('settingInstagramUrl').value = gallerySettings.instagram_url || '';
    document.getElementById('settingContactEmail').value = gallerySettings.contact_email || '';
    galleryEditor.showModal();
  });
  document.getElementById('saveGallerySettings').addEventListener('click', async (event) => {
    event.preventDefault();
    const settings = {
      artist_name: document.getElementById('settingArtistName').value,
      intro: document.getElementById('settingIntro').value,
      shop_url: document.getElementById('settingShopUrl').value,
      pinterest_url: document.getElementById('settingPinterestUrl').value,
      instagram_url: document.getElementById('settingInstagramUrl').value,
      contact_email: document.getElementById('settingContactEmail').value,
    };
    const response = await fetch('/api/gallery-settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(settings)});
    if (!response.ok) return alert('Please check the links and contact email, then try again.');
    applyGallerySettings(await response.json());
    galleryEditor.close();
  });
}
