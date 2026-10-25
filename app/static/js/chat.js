document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chatForm');
    const questionInput = document.getElementById('question');
    const messagesDiv = document.getElementById('messages');

    function scrollToBottom() {
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    scrollToBottom();

    if (chatForm) {
        chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const question = questionInput.value.trim();
            if (!question) return;

            // Add user message
            const userMsg = document.createElement('div');
            userMsg.style.alignSelf = 'flex-end';
            userMsg.style.maxWidth = '70%';
            userMsg.style.background = '#2563eb';
            userMsg.style.color = 'white';
            userMsg.style.padding = '0.75rem 1rem';
            userMsg.style.borderRadius = '1rem 1rem 0 1rem';
            userMsg.textContent = question;
            messagesDiv.appendChild(userMsg);
            
            questionInput.value = '';
            scrollToBottom();
            
            // Show thinking
            const thinkingMsg = document.createElement('div');
            thinkingMsg.style.alignSelf = 'flex-start';
            thinkingMsg.style.maxWidth = '80%';
            thinkingMsg.style.background = '#f3f4f6';
            thinkingMsg.style.padding = '0.75rem 1rem';
            thinkingMsg.style.borderRadius = '1rem 1rem 1rem 0';
            thinkingMsg.style.color = '#6b7280';
            thinkingMsg.textContent = 'Thinking...';
            messagesDiv.appendChild(thinkingMsg);
            scrollToBottom();

            try {
                const response = await fetch(`/chat/${companyId}/message`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question })
                });

                const data = await response.json();
                messagesDiv.removeChild(thinkingMsg);

                if (response.ok) {
                    const assistantMsg = document.createElement('div');
                    assistantMsg.style.alignSelf = 'flex-start';
                    assistantMsg.style.maxWidth = '80%';
                    
                    let citationsHtml = '';
                    if (data.citations && data.citations.length > 0) {
                        citationsHtml = `
                            <details style="margin-left: 0.5rem;">
                                <summary style="cursor: pointer; color: #2563eb; font-size: 0.875rem;">Sources (${data.citations.length})</summary>
                                <div style="margin-top: 0.5rem; display: flex; flex-direction: column; gap: 0.5rem;">
                                    ${data.citations.map(cite => `
                                        <div style="background: white; padding: 0.5rem; border: 1px solid #e5e7eb; border-radius: 0.375rem; font-size: 0.875rem;">
                                            <a href="${cite.url}" target="_blank" style="color: #2563eb;">${cite.url}</a>
                                            <p style="color: #6b7280; margin-top: 0.25rem;">${cite.snippet}</p>
                                        </div>
                                    `).join('')}
                                </div>
                            </details>
                        `;
                    }
                    
                    assistantMsg.innerHTML = `
                        <div style="background: #f3f4f6; padding: 0.75rem 1rem; border-radius: 1rem 1rem 1rem 0; margin-bottom: 0.5rem; white-space: pre-wrap;">${data.answer}</div>
                        ${citationsHtml}
                        ${data.tokens ? `<p style="color: #9ca3af; font-size: 0.75rem; margin-top: 0.25rem; margin-left: 0.5rem;">${data.tokens} tokens · $${data.cost_usd}</p>` : ''}
                    `;
                    messagesDiv.appendChild(assistantMsg);
                } else {
                    thinkingMsg.textContent = `Error: ${data.detail || 'Something went wrong'}`;
                    thinkingMsg.style.color = '#dc2626';
                }
                scrollToBottom();
            } catch (error) {
                messagesDiv.removeChild(thinkingMsg);
                const errorMsg = document.createElement('div');
                errorMsg.style.alignSelf = 'flex-start';
                errorMsg.style.color = '#dc2626';
                errorMsg.textContent = 'Error: Failed to send message';
                messagesDiv.appendChild(errorMsg);
                scrollToBottom();
            }
        });
    }
});
