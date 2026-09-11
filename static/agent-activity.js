const money = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(Number(value || 0));
const friendlyDate = (value) => value ? new Date(`${value.replace(' ', 'T')}Z`).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Just now';

fetch('/api/agent-activity').then((response) => response.ok ? response.json() : Promise.reject()).then((data) => {
  document.querySelector('#activitySummary').innerHTML = `
    <article><span>Live Agent requests</span><strong>${data.calls_used} <small>of ${data.calls_limit}</small></strong><p>Your monthly safety limit</p></article>
    <article><span>Tracked since today</span><strong>${data.logged_calls}</strong><p>${data.earlier_unlogged_calls ? `${data.earlier_unlogged_calls} earlier request${data.earlier_unlogged_calls === 1 ? '' : 's'} were made before this log started.` : 'Every recent request is listed below.'}</p></article>
    <article><span>Estimated tracked cost</span><strong>${money(data.estimated_cost)}</strong><p>For the entries below only</p></article>
    <article><span>Current model</span><strong class="model-name">${data.model}</strong><p>Cost-conscious Live Agent</p></article>`;
  const list = document.querySelector('#activityList');
  list.innerHTML = data.activity.length ? data.activity.map((item) => `<article><div><strong>${item.activity_type}</strong><span>${friendlyDate(item.created_at)} · ${item.status}</span></div><div><span>${item.input_tokens.toLocaleString()} in · ${item.output_tokens.toLocaleString()} out</span><b>${money(item.estimated_cost)}</b></div></article>`).join('') : '<div class="activity-empty"><strong>Your first Live Agent request will appear here.</strong><p>Use Chat or analyze an artwork, then come back to see the receipt.</p></div>';
}).catch(() => { document.querySelector('#activitySummary').innerHTML = '<p>Could not load the activity record right now.</p>'; });
