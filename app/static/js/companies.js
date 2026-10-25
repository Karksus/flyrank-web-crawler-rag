document.addEventListener('DOMContentLoaded', () => {
    const createForm = document.getElementById('createForm');
    const messageDiv = document.getElementById('message');

    if (createForm) {
        createForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('name').value;
            const base_url = document.getElementById('base_url').value;

            messageDiv.innerHTML = '<p style="color: #2563eb;">Creating bot and starting crawl...</p>';

            try {
                const response = await fetch('/companies/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name || null, base_url })
                });

                const data = await response.json();
                if (response.ok) {
                    window.location.href = data.redirect;
                } else {
                    messageDiv.innerHTML = `<p style="color: red;">${data.detail || 'Error creating bot'}</p>`;
                }
            } catch (error) {
                messageDiv.innerHTML = '<p style="color: red;">An error occurred</p>';
            }
        });
    }
});
