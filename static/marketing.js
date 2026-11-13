const planForm = document.querySelector("#planForm");
const planEditor = document.querySelector("#planEditor");
const artworkSelect = document.querySelector("#artwork");
const createButton = document.querySelector("#createPlan");
const savedWeeks = document.querySelector("#savedWeeks");
const statusLine = document.querySelector("#marketingStatus");
const startDate = document.querySelector("#startDate");
const editDate = document.querySelector("#editDate");
const editListing = document.querySelector("#editListing");
const dateLabel = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric", timeZone: "UTC",
});
const postGuidance = {
    instagram: "Use a vertical studio clip or a slow pan across the finished piece.",
    pinterest: "Use a tall crop of the artwork and put the listing URL in the destination field.",
    facebook: "Use the finished artwork photo and share the listing link with the post.",
    tiktok: "Start with a close-up, then cut to the full piece.",
};
const captionLimits = { instagram: 2200, pinterest: 500, facebook: 5000, tiktok: 2200 };
let plans = [];
let activePlan = null;
let hasEdits = false;
let busy = false;

function showStatus(message) {
    statusLine.textContent = message;
}

async function request(path, method = "GET", payload) {
    const options = { method };
    if (payload) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) {
        throw new Error(typeof result.detail === "string" ? result.detail : "Check the dates, link, and caption lengths.");
    }
    return result;
}

function setBusy(value) {
    busy = value;
    createButton.disabled = busy || artworkSelect.disabled;
    planEditor.querySelectorAll('button[type="submit"]').forEach(button => { button.disabled = busy; });
}

function postDates() {
    if (!editDate.valueAsDate) return;
    planEditor.querySelectorAll("time[data-offset]").forEach(time => {
        const date = editDate.valueAsDate;
        date.setUTCDate(date.getUTCDate() + Number(time.dataset.offset));
        time.dateTime = date.toISOString().slice(0, 10);
        time.textContent = dateLabel.format(date);
    });
}

function editorField(labelText, name, value, limit, multiline = false) {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement(multiline ? "textarea" : "input");
    input.name = name;
    input.value = value;
    input.maxLength = limit;
    if (multiline) input.rows = 4;
    label.append(input);
    return label;
}

function renderPost(post, firstDate) {
    const card = document.createElement("section");
    card.className = "panel post-card";
    const heading = document.createElement("div");
    heading.className = "post-heading";
    const title = document.createElement("h2");
    title.textContent = `${post.label} · ${post.format}`;
    const time = document.createElement("time");
    time.className = "post-date";
    time.dataset.offset = (Date.parse(post.date) - Date.parse(firstDate)) / 86400000;
    heading.append(title, time);
    const guidance = document.createElement("p");
    guidance.className = "post-media";
    guidance.textContent = postGuidance[post.platform];
    card.append(heading, guidance);
    if (post.platform === "pinterest") {
        card.append(editorField("Pin title", "pinterest_title", post.title, 100));
    }
    const caption = editorField(post.platform === "pinterest" ? "Pin description" : "Caption",
        post.platform, post.caption, captionLimits[post.platform], true);
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = post.platform === "pinterest" ? "Copy Pin details" : "Copy caption";
    copy.onclick = async () => {
        const text = [caption.querySelector("textarea").value];
        if (post.platform === "pinterest") text.unshift(planEditor.elements.pinterest_title.value);
        if (["facebook", "pinterest"].includes(post.platform) && editListing.value.trim()) {
            text.push(editListing.value.trim());
        }
        try {
            await navigator.clipboard.writeText(text.join("\n\n"));
            showStatus(`${post.label} copy ready to paste.`);
        } catch {
            const input = caption.querySelector("textarea");
            input.focus();
            input.select();
            showStatus("Copy the selected text using your device’s copy action.");
        }
    };
    card.append(caption, copy);
    return card;
}

function renderSavedWeeks() {
    const buttons = [...plans].sort((a, b) => b.start_date.localeCompare(a.start_date)).map(plan => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = plan.artwork_title;
        button.setAttribute("aria-pressed", String(plan.id === activePlan?.id));
        const details = document.createElement("small");
        details.textContent = `${plan.start_date} · ${plan.approved ? "Approved" : "Draft"}`;
        button.append(details);
        button.onclick = () => {
            if (busy || (hasEdits && !window.confirm("Discard the unsaved changes to this week?"))) return;
            openPlan(plan);
            showStatus("");
            document.querySelector("#planTitle").focus();
        };
        return button;
    });
    savedWeeks.replaceChildren(...buttons);
    if (!buttons.length) savedWeeks.textContent = "No weeks saved yet.";
}

function openPlan(plan) {
    activePlan = plan;
    hasEdits = false;
    planEditor.hidden = false;
    document.querySelector("#planEmpty").hidden = true;
    document.querySelector("#planTitle").textContent = plan.artwork_title;
    document.querySelector("#planState").textContent = plan.approved ? "Approved" : "Draft";
    const image = document.querySelector("#featuredArtwork");
    image.hidden = !plan.artwork_url;
    if (plan.artwork_url) image.src = plan.artwork_url;
    else image.removeAttribute("src");
    editDate.value = plan.start_date;
    editListing.value = plan.listing_url;
    document.querySelector("#posts").replaceChildren(...plan.posts.map(post => renderPost(post, plan.start_date)));
    postDates();
    renderSavedWeeks();
}

function rememberPlan(plan) {
    plans = [plan, ...plans.filter(item => item.id !== plan.id)];
    openPlan(plan);
}

function useLastListing() {
    const previous = plans.find(item => String(item.artwork_id) === artworkSelect.value && item.listing_url);
    document.querySelector("#listing").value = previous?.listing_url || "";
}

planForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || (hasEdits && !window.confirm("Discard the unsaved changes to this week?"))) return;
    setBusy(true);
    try {
        const plan = await request("/api/marketing/plans", "POST", {
            artwork_id: Number(artworkSelect.value),
            start_date: startDate.value,
            listing_url: document.querySelector("#listing").value.trim() || null,
            story: document.querySelector("#story").value.trim(),
        });
        rememberPlan(plan);
        showStatus("Week ready to review.");
        document.querySelector("#planTitle").focus();
    } catch (error) {
        showStatus(error.message);
    } finally {
        setBusy(false);
    }
});

planEditor.addEventListener("input", () => {
    hasEdits = true;
    document.querySelector("#planState").textContent = "Unsaved changes";
});
editDate.addEventListener("input", postDates);

planEditor.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    const approved = event.submitter?.value === "approved";
    const captions = Object.fromEntries(new FormData(planEditor));
    setBusy(true);
    try {
        rememberPlan(await request(`/api/marketing/plans/${activePlan.id}`, "PUT", {
            start_date: editDate.value,
            listing_url: editListing.value.trim() || null,
            revision: activePlan.revision,
            approved,
            captions,
        }));
        showStatus(approved ? "Week approved for manual publishing." : "Draft saved.");
    } catch (error) {
        showStatus(error.message);
    } finally {
        setBusy(false);
    }
});

window.addEventListener("beforeunload", event => {
    if (hasEdits) event.preventDefault();
});

async function loadWorkspace() {
    const today = new Date();
    today.setMinutes(today.getMinutes() - today.getTimezoneOffset());
    startDate.value = today.toISOString().slice(0, 10);
    const artworkId = new URLSearchParams(window.location.search).get("artwork");
    try {
        const [artworks, savedPlans] = await Promise.all([request("/api/artworks"), request("/api/marketing/plans")]);
        plans = savedPlans;
        artworks.forEach(artwork => artworkSelect.add(new Option(artwork.title || "Untitled artwork", artwork.id)));
        artworkSelect.disabled = !artworks.length;
        document.querySelector("#noArtwork").hidden = Boolean(artworks.length);
        setBusy(false);
        const hasRequestedArtwork = artworkId && artworks.some(artwork => String(artwork.id) === artworkId);
        if (hasRequestedArtwork) {
            artworkSelect.value = artworkId;
            useLastListing();
        }
        const plan = hasRequestedArtwork ? plans.find(item => String(item.artwork_id) === artworkId) : plans[0];
        if (plan) openPlan(plan);
        else renderSavedWeeks();
    } catch (error) {
        showStatus(`Could not load the marketing workspace. ${error.message}`);
    }
}

artworkSelect.addEventListener("change", useLastListing);

loadWorkspace();
