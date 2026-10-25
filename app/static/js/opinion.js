document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('publicOpinionBtn');
    const status = document.getElementById('publicOpinionStatus');
    const results = document.getElementById('publicOpinionResults');
    if (!button || !status || !results) return;

    const sentimentColors = {
        positive: '#059669',
        mixed: '#d97706',
        negative: '#dc2626',
        neutral: '#6b7280',
        unknown: '#6b7280',
    };

    let hasChecked = false;

    function safeUrl(value) {
        try {
            const url = new URL(value, window.location.origin);
            if (url.protocol === 'http:' || url.protocol === 'https:') {
                return url.toString();
            }
        } catch (error) {
            // Invalid URL; fall through to the placeholder.
        }
        return '#';
    }

    function el(tag, text, styles) {
        const node = document.createElement(tag);
        if (text !== undefined && text !== null) node.textContent = text;
        if (styles) node.style.cssText = styles;
        return node;
    }

    function renderList(title, values, color) {
        if (!Array.isArray(values) || values.length === 0) return null;
        const wrapper = el('div', null, 'margin-top: 0.75rem;');
        wrapper.appendChild(el('strong', title, `color: ${color}; font-size: 0.875rem;`));
        const list = el('ul', null, 'margin: 0.35rem 0 0 1.1rem; padding: 0; font-size: 0.875rem; color: #374151;');
        values.forEach((value) => list.appendChild(el('li', value, 'margin-bottom: 0.2rem;')));
        wrapper.appendChild(list);
        return wrapper;
    }

    function render(data) {
        results.replaceChildren();
        const sentiment = data.sentiment || {};
        const label = String(sentiment.label || 'unknown').toLowerCase();
        const color = sentimentColors[label] || sentimentColors.unknown;

        const summaryCard = el('div', null, 'border: 1px solid #e5e7eb; border-radius: 0.5rem; padding: 1rem; background: #f9fafb;');
        const badgeRow = el('div', null, 'display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;');
        badgeRow.appendChild(el('span', label.charAt(0).toUpperCase() + label.slice(1), `background: ${color}; color: white; padding: 0.2rem 0.55rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600;`));
        if (data.cached) {
            badgeRow.appendChild(el('span', 'Cached', 'color: #6b7280; font-size: 0.75rem;'));
        }
        summaryCard.appendChild(badgeRow);
        summaryCard.appendChild(el('p', sentiment.summary || 'No summary available.', 'margin: 0.65rem 0 0; color: #111827; font-size: 0.9rem; line-height: 1.5;'));

        const positives = renderList('Positive signals', sentiment.positives, '#059669');
        if (positives) summaryCard.appendChild(positives);
        const negatives = renderList('Concerns', sentiment.negatives, '#dc2626');
        if (negatives) summaryCard.appendChild(negatives);
        const themes = renderList('Themes', sentiment.themes, '#2563eb');
        if (themes) summaryCard.appendChild(themes);

        const sourceLine = (data.sources || [])
            .map((source) => `${source.name}: ${source.status === 'ok' ? `${source.count} mention(s)` : source.status}`)
            .join(' · ');
        if (sourceLine) {
            summaryCard.appendChild(el('p', `Sources checked — ${sourceLine}`, 'margin: 0.75rem 0 0; color: #6b7280; font-size: 0.75rem;'));
        }

        if (data.subreddit && data.subreddit.name) {
            const subreddit = data.subreddit;
            const subredditLine = el('p', null, 'margin: 0.5rem 0 0; color: #6b7280; font-size: 0.75rem;');
            subredditLine.appendChild(document.createTextNode('Company subreddit found: '));
            const subredditLink = el('a', `r/${subreddit.name}`, 'color: #2563eb; text-decoration: none;');
            subredditLink.href = safeUrl(subreddit.url || `https://www.reddit.com/r/${subreddit.name}/`);
            subredditLink.target = '_blank';
            subredditLink.rel = 'noopener noreferrer';
            subredditLine.appendChild(subredditLink);
            if (subreddit.subscribers) {
                subredditLine.appendChild(document.createTextNode(` · ${subreddit.subscribers.toLocaleString()} members`));
            }
            summaryCard.appendChild(subredditLine);
        }

        summaryCard.appendChild(el('p', `Checked ${data.checked_at ? new Date(data.checked_at).toLocaleString() : 'just now'}`, 'margin: 0.5rem 0 0; color: #9ca3af; font-size: 0.75rem;'));
        results.appendChild(summaryCard);

        if (!data.items || data.items.length === 0) {
            results.appendChild(el('p', 'No public discussions were found for this company. Try again later or check a different company name.', 'color: #6b7280; font-size: 0.875rem; margin-top: 1rem;'));
        } else {
            const heading = el('h3', `Top mentions (${data.items.length})`, 'margin: 1.25rem 0 0.25rem; font-size: 0.95rem;');
            results.appendChild(heading);

            data.items.forEach((item) => {
                const row = el('div', null, 'border-top: 1px solid #e5e7eb; padding: 0.8rem 0;');
                const source = el('span', item.source_label || item.source || 'Web', 'display: inline-block; color: #2563eb; background: #eff6ff; border-radius: 0.25rem; padding: 0.1rem 0.4rem; font-size: 0.7rem; margin-bottom: 0.35rem;');
                row.appendChild(source);
                row.appendChild(el('br'));

                const link = el('a', item.title || 'Untitled mention', 'color: #111827; font-weight: 600; font-size: 0.9rem; text-decoration: none;');
                link.href = safeUrl(item.url);
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                row.appendChild(link);

                if (item.snippet) {
                    row.appendChild(el('p', item.snippet, 'margin: 0.35rem 0 0; color: #4b5563; font-size: 0.82rem; line-height: 1.45;'));
                }

                const metaParts = [];
                if (item.score) metaParts.push(`${item.score} points`);
                if (item.comments) metaParts.push(`${item.comments} comments`);
                if (item.author) metaParts.push(`u/${item.author}`);
                if (item.created_at) {
                    const date = new Date(item.created_at);
                    if (!Number.isNaN(date.getTime())) metaParts.push(date.toLocaleDateString());
                }
                if (metaParts.length) {
                    row.appendChild(el('p', metaParts.join(' · '), 'margin: 0.3rem 0 0; color: #9ca3af; font-size: 0.72rem;'));
                }
                results.appendChild(row);
            });
        }

        if (data.disclaimer) {
            results.appendChild(el('p', data.disclaimer, 'margin-top: 1rem; color: #9ca3af; font-size: 0.72rem; line-height: 1.4;'));
        }
    }

    async function check(refresh) {
        button.disabled = true;
        button.textContent = 'Checking...';
        status.textContent = 'Checking Reddit, Hacker News, and news mentions. This can take 10-20 seconds...';
        results.replaceChildren();

        try {
            const url = `/companies/${companyId}/public-opinion${refresh ? '?refresh=true' : ''}`;
            const response = await fetch(url, { credentials: 'include' });
            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                status.textContent = '';
                results.appendChild(el('p', data.detail || `Request failed (${response.status})`, 'color: #dc2626; font-size: 0.875rem;'));
                return;
            }

            status.textContent = '';
            hasChecked = true;
            render(data);
        } catch (error) {
            status.textContent = '';
            results.appendChild(el('p', 'Could not check public opinion. Please try again.', 'color: #dc2626; font-size: 0.875rem;'));
        } finally {
            button.disabled = false;
            button.textContent = hasChecked ? 'Refresh public opinion' : 'Check public opinion';
        }
    }

    button.addEventListener('click', () => check(hasChecked));
});
