const grid = document.getElementById('artGrid');
const emptyState = document.getElementById('emptyState');
const count = document.getElementById('collectionCount');
let artwork = [];
let selected = 'all';

function visibleArtwork() {
  return artwork.filter((item) => selected === 'all' || item.collection === selected);
}

function render() {
  const items = visibleArtwork();
  count.textContent = `${items.length} ${items.length === 1 ? 'work' : 'works'} selected`;
  grid.innerHTML = items.map((item) => {
    const extra = [item.medium, item.dimensions].filter(Boolean).join(' · ') || item.collection;
    return `<article class="art-card"><div class="art-image"><img src="${item.url}" alt="${item.title || 'Black Canvas artwork'}"></div><div class="art-copy"><p>${item.collection || 'Black Canvas'}</p><h3>${item.title || 'Untitled work'}</h3><small>${extra}</small></div></article>`;
  }).join('');
  emptyState.hidden = items.length !== 0;
}

document.querySelectorAll('[data-filter]').forEach((button) => {
  button.addEventListener('click', () => {
    selected = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach((item) => item.classList.toggle('active', item === button));
    render();
  });
});

fetch('/api/artworks').then((response) => response.ok ? response.json() : []).then((items) => {
  artwork = items.filter((item) => item.filename && item.sale_status !== 'Sold' && item.sale_status !== 'Not for sale');
  render();
}).catch(() => { count.textContent = 'Artwork will appear here'; emptyState.hidden = false; });

document.getElementById('year').textContent = new Date().getFullYear();
