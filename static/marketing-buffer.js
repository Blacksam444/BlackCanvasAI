const bufferForm = document.querySelector("#bufferForm");
const bufferOrganization = document.querySelector("#bufferOrganization");
const bufferStatus = document.querySelector("#bufferStatus");
const bufferSetup = document.querySelector("#bufferSetup");
const bufferPosts = document.querySelector("#bufferPosts");
let bufferChannels = [];
let bufferLoaded = false;
let loadingChannels = 0;

function addBufferField(parent, labelText, control) {
    const label = document.createElement("label");
    label.append(labelText, control);
    parent.append(label);
    return control;
}

function bufferSelect(placeholder, options) {
    const select = document.createElement("select");
    select.add(new Option(placeholder, ""));
    options.forEach(([id, name]) => select.add(new Option(name, id)));
    select.required = true;
    return select;
}

function bufferPostFields(post, channels) {
    const row = document.createElement("fieldset");
    row.className = "buffer-platform";
    const legend = document.createElement("legend");
    legend.textContent = post.label;
    row.append(legend);
    const existing = activePlan.buffer_posts[post.platform];
    if (existing) {
        const status = document.createElement("p");
        const label = { buffer: "Scheduled", sent: "Published", draft: "Draft in Buffer",
            error: "Check publishing status in Buffer" }[existing.state] || "Accepted by Buffer";
        status.textContent = existing.buffer_id
            ? `${label} · ${existing.channel_name} · ${new Date(existing.due_at).toLocaleString()}`
            : `Check the Buffer queue for ${existing.channel_name}. The submission could not be confirmed.`;
        row.append(status);
        return row;
    }
    if (!channels.length) {
        row.append("Connect an active account in Buffer to schedule this post.");
        return row;
    }

    const include = document.createElement("input");
    include.type = "checkbox";
    const includeLabel = document.createElement("label");
    includeLabel.append(include, "Schedule this post");
    row.append(includeLabel);
    const fields = document.createElement("div");
    fields.hidden = true;
    const account = addBufferField(fields, "Account", bufferSelect("Choose an account",
        channels.map(channel => [channel.id, channel.name])));
    const board = bufferSelect("Choose a board", []);
    if (post.platform === "pinterest") addBufferField(fields, "Pinterest board", board);
    account.onchange = () => {
        const channel = channels.find(item => item.id === account.value);
        board.replaceChildren(new Option("Choose a board", ""), ...(channel?.boards || [])
            .map(item => new Option(item.name, item.serviceId)));
    };
    if (channels.length === 1) {
        account.value = channels[0].id;
        account.onchange();
    }
    const media = document.createElement("input");
    media.type = "url";
    media.required = true;
    const video = ["instagram", "tiktok", "youtube"].includes(post.platform);
    addBufferField(fields, video ? "Public video URL" : "Public image URL", media);
    const time = document.createElement("input");
    time.type = "time";
    time.required = true;
    addBufferField(fields, `Time on ${post.date}`, time);
    const ai = document.createElement("input");
    ai.type = "checkbox";
    if (video) addBufferField(fields, " This video includes AI-generated media", ai);
    const privacy = bufferSelect("Choose visibility", [["public", "Public"], ["unlisted", "Unlisted"], ["private", "Private"]]);
    privacy.value = "public";
    if (post.platform === "youtube") addBufferField(fields, "YouTube visibility", privacy);
    row.append(fields);
    include.onchange = () => {
        fields.hidden = !include.checked;
        fields.querySelectorAll("input, select").forEach(control => { control.disabled = !include.checked; });
    };
    include.onchange();
    row.getSelection = () => {
        if (!include.checked) return null;
        const local = new Date(`${post.date}T${time.value}`);
        const pad = number => String(number).padStart(2, "0");
        if (Number.isNaN(local.getTime()) || `${pad(local.getHours())}:${pad(local.getMinutes())}` !== time.value) {
            throw new Error(`Choose a valid date and time for ${post.label}.`);
        }
        const offset = -local.getTimezoneOffset();
        const zone = `${offset < 0 ? "-" : "+"}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`;
        return {
            platform: post.platform, channel_id: account.value, due_at: `${post.date}T${time.value}:00${zone}`,
            media_url: media.value, board_id: board.value, ai_generated: ai.checked, youtube_privacy: privacy.value,
        };
    };
    return row;
}

function renderBufferPosts() {
    if (!activePlan?.approved) return;
    const fields = activePlan.posts
        .filter(post => activePlan.buffer_posts[post.platform] || bufferChannels.some(channel => channel.platform === post.platform))
        .map(post => bufferPostFields(post, bufferChannels.filter(channel => channel.platform === post.platform)));
    bufferPosts.replaceChildren(...fields);
    if (!fields.length && bufferOrganization.value) bufferPosts.textContent = "Connect an active social account in Buffer to schedule posts.";
    bufferForm.querySelector('button[type="submit"]').hidden = !fields.some(field => field.getSelection);
}

async function loadBufferChannels() {
    const sequence = ++loadingChannels;
    bufferChannels = [];
    bufferPosts.replaceChildren();
    bufferForm.querySelector('button[type="submit"]').hidden = true;
    if (!bufferOrganization.value) return;
    bufferStatus.textContent = "Loading connected accounts…";
    try {
        const channels = await request(`/api/marketing/buffer/channels?organization_id=${encodeURIComponent(bufferOrganization.value)}`);
        if (sequence !== loadingChannels) return;
        bufferChannels = channels;
        bufferStatus.textContent = "";
        renderBufferPosts();
    } catch (error) {
        if (sequence === loadingChannels) bufferStatus.textContent = error.message;
    }
}

bufferPanel.addEventListener("toggle", async () => {
    if (!bufferPanel.open || bufferLoaded) return;
    bufferStatus.textContent = "Checking Buffer…";
    bufferSetup.hidden = true;
    try {
        const data = await request("/api/marketing/buffer");
        if (!data.configured || !data.organizations.length) {
            bufferStatus.textContent = data.configured
                ? "Connect your social accounts to a Buffer workspace."
                : "Set up a Buffer API key on the Black Canvas AI server to connect your accounts.";
            bufferSetup.hidden = data.configured;
            return;
        }
        bufferLoaded = true;
        bufferOrganization.replaceChildren(new Option("Choose a workspace", ""), ...data.organizations
            .map(item => new Option(item.name, item.id)));
        bufferForm.hidden = false;
        bufferStatus.textContent = "";
        if (data.organizations.length === 1) {
            bufferOrganization.value = data.organizations[0].id;
            await loadBufferChannels();
        }
    } catch (error) {
        bufferStatus.textContent = error.message;
    }
});

bufferPanel.addEventListener("planchange", renderBufferPosts);
bufferOrganization.addEventListener("change", loadBufferChannels);
bufferForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || hasEdits || !activePlan?.approved) return;
    const button = event.submitter;
    try {
        const posts = [...bufferPosts.children].map(row => row.getSelection?.()).filter(Boolean);
        if (!posts.length) throw new Error("Select at least one post to schedule.");
        setBusy(true);
        button.disabled = true;
        const result = await request(`/api/marketing/plans/${activePlan.id}/buffer`, "POST", {
            revision: activePlan.revision, organization_id: bufferOrganization.value, posts,
        });
        rememberPlan(result.plan);
        bufferStatus.textContent = Object.keys(result.errors).length
            ? Object.entries(result.errors).map(([platform, error]) => `${platform}: ${error}`).join(" ")
            : "Buffer accepted the selected posts. Check their status below.";
    } catch (error) {
        bufferStatus.textContent = error.message;
    } finally {
        button.disabled = false;
        setBusy(false);
    }
});
